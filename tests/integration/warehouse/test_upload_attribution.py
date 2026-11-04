"""The production SQL actions retain the writer of each admitted upload."""

from dataclasses import replace

import pytest

from etl_craft.core.errors import SqlGuardError
from etl_craft.core.uploads import UploadWriter
from etl_craft.handlers import sql
from etl_craft.warehouse.connection import warehouse_dialect


def apply_upload_action(w, context):
    from etl_craft.dialects.warehouse.uploads import writer_parameters
    from etl_craft.handlers.registry import task_store
    from etl_craft.handlers.sql.actions import ACTIONS
    from etl_craft.handlers.sql.context import ActionContext
    from etl_craft.handlers.sql.session import Session
    from etl_craft.handlers.sql.spec import read_sql_task

    task = read_sql_task(context)
    store = task_store(context, w.engine_db)
    state = store.state(task.action)
    with w.warehouse.begin() as conn:
        session = Session(
            conn,
            sql.task_dialect(context),
            catalog=w.catalog,
            action=task.action,
            target_object=task.target_object,
            task_run_id=context.task_run_id,
            params=context.task_params,
        )
        session.uploads = context.uploads
        session.bindings = writer_parameters(context.uploads)
        try:
            ACTIONS[task.action](
                session,
                ActionContext(
                    task,
                    context,
                    store,
                    context.writer,
                    context.started_at,
                    state=state,
                    uploads=context.uploads,
                ),
            )
        finally:
            session.sweep()


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_upload_rows_name_their_own_writer(sql_world, kind):
    w = sql_world
    source = "SELECT 1 AS id, 'first' AS name, CAST(10 AS BIGINT) AS upload_id"
    w.setup("uploaded", source, kind)
    context = w.task(
        "upload_merge",
        SQL_ACTION=kind,
        TARGET_OBJECT="uploaded",
        SELECT_QUERY=source + " UNION ALL SELECT 2, 'second', 11",
        MERGE_KEY="id",
        MERGE_COMPARE_COLUMNS="name",
    )
    uploads = (UploadWriter(10, "alice"), UploadWriter(11, "bob"))
    apply_upload_action(w, replace(context, uploads=uploads))
    with w.warehouse.connect() as conn:
        from sqlalchemy import text

        rows = (
            conn.execute(
                text(
                    f"SELECT id AS id, created_by AS creator, updated_by AS writer "
                    f"FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y' ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert [(row["id"], row["creator"], row["writer"]) for row in rows] == [
        (1, "alice", "alice"),
        (2, "bob", "bob"),
    ]

    updated = w.task(
        "upload_merge",
        SQL_ACTION=kind,
        TARGET_OBJECT="uploaded",
        SELECT_QUERY="SELECT 1 AS id,'corrected first' AS name,20 AS upload_id "
        "UNION ALL SELECT 2,'corrected second',21",
        MERGE_KEY="id",
        MERGE_COMPARE_COLUMNS="name",
    )
    apply_upload_action(
        w,
        replace(
            updated,
            uploads=(
                UploadWriter(20, "bob"),
                UploadWriter(21, "alice"),
            ),
        ),
    )
    with w.warehouse.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT id AS id,CREATED_BY AS creator,UPDATED_BY AS writer "
                    f"FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y' ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert [(r["id"], r["creator"], r["writer"]) for r in rows] == [
        (1, "bob", "bob"),
        (2, "alice", "alice"),
    ]


@pytest.mark.parametrize("value", ["NULL", "99"])
def test_unowned_upload_rows_fail_before_target_changes(sql_world, value):
    w = sql_world
    source = "SELECT 1 AS id, 'first' AS name, CAST(10 AS BIGINT) AS upload_id"
    w.setup("unowned", source, "SCD2_MERGE")
    context = w.task(
        "upload_merge",
        SQL_ACTION="SCD2_MERGE",
        TARGET_OBJECT="unowned",
        SELECT_QUERY=f"SELECT 1 AS id, 'first' AS name, CAST({value} AS BIGINT) AS upload_id",
        MERGE_KEY="id",
        MERGE_COMPARE_COLUMNS="name",
    )
    with pytest.raises(SqlGuardError) as failure:
        apply_upload_action(w, replace(context, uploads=(UploadWriter(10, "alice"),)))
    for expected in (w.name("unowned"), "1 staged rows", "sample=", "(10,)", "corrected file"):
        assert expected in str(failure.value)
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('unowned')}") == [(0,)]


@pytest.mark.parametrize("action", ["APPEND_TABLE", "OVERWRITE_TABLE"])
@pytest.mark.parametrize("declared_actors", [True, False])
def test_ordinary_upload_rows_retain_ids_and_stamp_declared_actors(
    sql_world, action, declared_actors
):
    from uuid import uuid4

    w = sql_world
    target = "uploaded_append_" + uuid4().hex[:10]
    try:
        source = "SELECT 1 AS id, CAST(10 AS BIGINT) AS upload_id"
        uploads = (UploadWriter(10, "alice"), UploadWriter(11, "bob"))
        setup = w.task(
            "upload_setup",
            SQL_ACTION="SETUP_TABLE",
            SETUP_FOR=action,
            TARGET_OBJECT=target,
            SELECT_QUERY=source,
        )
        sql.run(replace(setup, uploads=uploads) if declared_actors else setup, w.engine_db)
        context = w.task(
            "upload_append",
            SQL_ACTION=action,
            TARGET_OBJECT=target,
            SELECT_QUERY=source + " UNION ALL SELECT 2, 11",
        )
        sql.run(replace(context, uploads=uploads), w.engine_db)
        assert w.rows(f"SELECT id,upload_id FROM {w.name(target)} ORDER BY id") == [
            (1, 10),
            (2, 11),
        ]
        if declared_actors:
            assert w.rows(f"SELECT id,created_by,updated_by FROM {w.name(target)} ORDER BY id") == [
                (1, "alice", "alice"),
                (2, "bob", "bob"),
            ]
        else:
            assert not {"created_by", "updated_by"} & set(w.columns(target))
    finally:
        w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")


def test_two_uploads_retain_identity_until_their_merges_stamp_ods(sql_world):
    """Land ordinary file ids, then carry each account through every steward layer."""
    from uuid import uuid4

    from sqlalchemy import text

    from etl_craft.core.enums import Handler
    from etl_craft.handlers.python_scripts import script_task
    from etl_craft.handlers.registry import task_store
    from fixtures.metadata import add_source_column

    w = sql_world
    suffix = uuid4().hex[:10]
    landing = "landing_uploads_" + suffix
    owned = [landing] + [
        name + "_" + suffix
        for name in ("prs_uploads", "cdc_uploads", "preods_uploads", "ods_uploads")
    ]
    text_type = warehouse_dialect(w.config).string_type
    shape = (
        f"SELECT CAST(NULL AS BIGINT) AS id, CAST(NULL AS {text_type}) AS name, "
        "CAST(NULL AS BIGINT) AS upload_id WHERE 1=0"
    )
    try:
        w.setup(landing, shape, "APPEND_TABLE")
        context = replace(
            w.task("landing_loader", TARGET_OBJECT=landing, SCRIPT_KIND="INGESTION"),
            handler=Handler.PYTHON,
        )
        with w.engine_db.begin() as conn:
            conn.execute(
                text("UPDATE CFG_TASKS SET HANDLER='PYTHON' WHERE TASK_ID=:id"),
                {"id": context.task_id},
            )
            for number, (name, kind) in enumerate(
                [("id", "BIGINT"), ("name", "VARCHAR"), ("upload_id", "BIGINT")], 1
            ):
                add_source_column(conn, w.name(landing), name, kind, number)
        helper = script_task(context, task_store(context, w.engine_db), None, {})
        assert (
            helper.replace_landing(
                iter(
                    [
                        {"id": 1, "name": "first", "upload_id": 10},
                        {"id": 2, "name": "second", "upload_id": 11},
                    ]
                )
            )
            == 2
        )
        assert not {"created_by", "updated_by"} & set(w.columns(landing))
        assert w.rows(f"SELECT id,upload_id FROM {w.name(landing)} ORDER BY id") == [
            (1, 10),
            (2, 11),
        ]
        uploads = (UploadWriter(10, "alice"), UploadWriter(11, "bob"))
        previous = landing
        for layer, action in [
            ("prs_uploads", "SCD2_MERGE"),
            ("cdc_uploads", "OVERWRITE_TABLE"),
            ("preods_uploads", "APPEND_TABLE"),
            ("ods_uploads", "SCD1_MERGE"),
        ]:
            target = layer + "_" + suffix
            setup = w.task(
                "setup_" + layer,
                SQL_ACTION="SETUP_TABLE",
                SETUP_FOR=action,
                TARGET_OBJECT=target,
                SELECT_QUERY=shape,
            )
            sql.run(setup, w.engine_db)
            params = (
                {"MERGE_KEY": "id", "MERGE_COMPARE_COLUMNS": "name"}
                if action in {"SCD1_MERGE", "SCD2_MERGE"}
                else {}
            )
            step = w.task(
                "load_" + layer,
                SQL_ACTION=action,
                TARGET_OBJECT=target,
                SELECT_QUERY=f"SELECT id,name,upload_id FROM {w.name(previous)}",
                **params,
            )
            apply_upload_action(w, replace(step, uploads=uploads))
            previous = target
        assert w.rows(
            f"SELECT id,created_by,updated_by FROM {w.name('ods_uploads_' + suffix)} ORDER BY id"
        ) == [
            (1, "alice", "alice"),
            (2, "bob", "bob"),
        ]
    finally:
        for target in reversed(owned):
            w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")


@pytest.mark.parametrize("action", ["APPEND_TABLE", "OVERWRITE_TABLE", "SCD1_MERGE", "SCD2_MERGE"])
def test_upload_write_refuses_a_target_without_upload_id(sql_world, action):
    w = sql_world
    text_type = warehouse_dialect(w.config).string_type
    shape = f"SELECT CAST(NULL AS BIGINT) AS id, CAST(NULL AS {text_type}) AS name WHERE 1=0"
    w.setup("missing_upload", shape, action)
    params = (
        {"MERGE_KEY": "id", "MERGE_COMPARE_COLUMNS": "name"}
        if action in {"SCD1_MERGE", "SCD2_MERGE"}
        else {}
    )
    step = w.task(
        "upload_missing_target",
        SQL_ACTION=action,
        TARGET_OBJECT="missing_upload",
        SELECT_QUERY="SELECT 1 AS id, 'x' AS name, CAST(10 AS BIGINT) AS upload_id",
        **params,
    )
    with pytest.raises(SqlGuardError) as failure:
        apply_upload_action(w, replace(step, uploads=(UploadWriter(10, "alice"),)))
    for part in (
        "P.upload_missing_target",
        w.name("missing_upload"),
        "target UPLOAD_ID is missing",
        "declare UPLOAD_ID",
    ):
        assert part in str(failure.value)
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('missing_upload')}") == [(0,)]
