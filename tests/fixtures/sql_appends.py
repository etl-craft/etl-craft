"""Append retry and table adoption assertions shared by warehouse suites."""

import pytest

from etl_craft.core.errors import HandlerError, InjectedFaultError, SqlGuardError
from etl_craft.services.adopt_target import AdoptRequest, adopt_target
from etl_craft.warehouse.connection import warehouse_dialect


def check_append_retries(w, target):
    """Keep another load, replace a retried batch and retain both task runs across runs."""
    params = {"SQL_ACTION": "APPEND_TABLE", "TARGET_OBJECT": target}
    w.setup(target, "SELECT CAST(1 AS BIGINT) AS id", "APPEND_TABLE")
    w.run("seed_append", SELECT_QUERY="SELECT CAST(10 AS BIGINT) AS id", **params)
    for point in ("after_insert", "after_delete"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("ETL_CRAFT_FAULT", f"sql.append.{point}")
            with pytest.raises(InjectedFaultError):
                w.run(
                    "retry_append",
                    SELECT_QUERY="SELECT CAST(1 AS BIGINT) AS id UNION ALL SELECT 2",
                    **params,
                )
        result = w.run(
            "retry_append",
            SELECT_QUERY="SELECT CAST(1 AS BIGINT) AS id UNION ALL SELECT 2",
            **params,
        )
        assert (result.source_count, result.insert_count, result.target_count) == (2, 2, 3)
        assert sorted(w.rows(f"SELECT id FROM {w.name(target)}")) == [(1,), (2,), (10,)]
    loads = w.rows(f"SELECT task_run_id FROM {w.name(target)}")
    assert all(row[0] is not None for row in loads)
    assert len({row[0] for row in loads}) == 2
    keys = w.rows(f"SELECT row_id FROM {w.name(target)}")
    assert len(set(keys)) == 3
    w.new_run()
    w.run("retry_append", SELECT_QUERY="SELECT CAST(3 AS BIGINT) AS id", **params)
    assert sorted(w.rows(f"SELECT id FROM {w.name(target)}")) == [(1,), (2,), (3,), (10,)]


def create_target_without_task_run_id(w, target, loads=0):
    """Build an append shape without TASK_RUN_ID, retaining each warehouse's ROW_ID strategy.

    ``loads`` rows of ``id`` 1 stand for appends whose task run is unknown.
    """
    from datetime import UTC, datetime

    from etl_craft.handlers.sql.session import Session
    from etl_craft.handlers.sql.tables import build_stage, create_target_shape

    with w.warehouse.begin() as conn:
        session = Session(
            conn,
            warehouse_dialect(w.config),
            catalog=w.catalog,
            action="SETUP_TABLE",
            target_object=f"{w.schema}.{target}",
            task_run_id=0,
            params={},
        )
        try:
            stage = build_stage(session, "SELECT CAST(1 AS BIGINT) AS id", empty=True)
            create_target_shape(session, stage, ("CREATE_DATE",))
            if loads:
                rows = " UNION ALL ".join(["SELECT CAST(1 AS BIGINT) AS id"] * loads)
                history = build_stage(session, rows)
                row_id_columns, row_id_values = session.row_id_insert_parts()
                session.run(
                    f"INSERT INTO {session.target} (id, PIPELINE_RUN_ID, CREATE_DATE"
                    f"{row_id_columns}) SELECT id, 0, :now{row_id_values} FROM {history}",
                    {"now": datetime.now(UTC)},
                    step="seed earlier appends",
                )
        finally:
            session.sweep()


def check_identity_inputs(w, target):
    """Resolve named SQL inputs and persist the same identities in the target's audit columns."""
    from etl_craft.handlers import sql

    for code in ("first_dummy", "second_dummy"):
        w.task(code, SQL_ACTION="CREATE_TABLE", TARGET_OBJECT=target, SELECT_QUERY="SELECT 1 AS id")
    w.new_run()
    context = w.task(
        "identity_inputs",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=target,
        SELECT_QUERY="SELECT CAST($$pipeline_id AS BIGINT) AS source_pipeline_id, "
        "CAST($$pipeline_run_id AS BIGINT) AS source_pipeline_run_id, "
        "CAST($$task_run_id AS BIGINT) AS source_task_run_id",
        PIPELINE_ID_SUBSTITUTION="true",
        PIPELINE_RUN_ID_SUBSTITUTION="true",
        TASK_RUN_ID_SUBSTITUTION="true",
    )
    expected = (context.pipeline_id, context.pipeline_run_id, context.task_run_id)
    assert len(set(expected)) == 3
    sql.run(context, w.engine_db)
    assert w.rows(
        f"SELECT source_pipeline_id, source_pipeline_run_id, source_task_run_id, "
        f"pipeline_id, pipeline_run_id, task_run_id FROM {w.name(target)}"
    ) == [expected + expected]


def adopt(w, target, **options):
    """Adopt ``target`` in the world's schema with the service the CLI and API call."""
    return adopt_target(
        w.engine_db,
        w.config,
        AdoptRequest(
            f"{w.schema}.{target}",
            options.get("select"),
            options.get("keep_original", False),
            options.get("dry_run", False),
        ),
    )


def create_foreign_table(w, target, select):
    """Create a table the way another tool would, without any etl-craft column."""
    w.execute(f"CREATE TABLE {w.name(target)} AS {select}")


def check_append_adoption(w, target):
    """Adopt a foreign table for appends, dropping the original by default."""
    create_foreign_table(w, target, "SELECT CAST(1 AS BIGINT) AS id UNION ALL SELECT 2")
    params = {
        "SQL_ACTION": "APPEND_TABLE",
        "TARGET_OBJECT": target,
        "SELECT_QUERY": "SELECT CAST(3 AS BIGINT) AS id",
    }
    with pytest.raises(SqlGuardError, match=r"no TASK_RUN_ID column.*adopt-target --target"):
        w.run("adopted_append", **params)
    planned = adopt(w, target, dry_run=True)
    assert planned.adopted and planned.dry_run and planned.kept is None
    assert any(sql.startswith("INSERT INTO") for sql in planned.sql)
    assert "task_run_id" not in w.columns(target)
    done = adopt(w, target)
    assert (done.adopted, done.rows, done.kept, done.action) == (True, 2, None, "APPEND_TABLE")
    assert {"task_run_id", "pipeline_id", "create_date", "row_id"} <= set(w.columns(target))
    assert not [t for t in w.tables() if t.endswith("_pre_adopt")]
    assert w.rows(
        f"SELECT id FROM {w.name(target)} WHERE task_run_id IS NULL AND create_date IS NOT NULL "
        "ORDER BY id"
    ) == [(1,), (2,)]
    assert not adopt(w, target).adopted
    w.run("adopted_append", **params)
    assert sorted(w.rows(f"SELECT id FROM {w.name(target)}")) == [(1,), (2,), (3,)]


def check_merge_adoption(w, target):
    """Map existing flags and stamps, keep the original on request, then merge normally."""
    create_foreign_table(
        w,
        target,
        "SELECT CAST(1 AS BIGINT) AS id, CAST('Ann' AS VARCHAR(20)) AS name, "
        "CAST('N' AS VARCHAR(1)) AS gone UNION ALL SELECT 2, 'Bo', 'Y'",
    )
    params = {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": target,
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
        "SELECT_QUERY": "SELECT CAST(1 AS BIGINT) AS id, CAST('Anna' AS VARCHAR(20)) AS name",
    }
    w.task("adopted_merge", **params)
    mapping = (
        f"SELECT id, name, gone AS DELETE_FLAG, "
        f"CASE WHEN gone = 'Y' THEN 'N' ELSE 'Y' END AS ACTIVE_FLAG FROM {w.name(target)}"
    )
    with pytest.raises(HandlerError, match=r"NULL or invalid managed values.*original table"):
        adopt(w, target, select=f"SELECT id, name, 'X' AS ACTIVE_FLAG FROM {w.name(target)}")
    assert w.columns(target) == ["id", "name", "gone"]
    done = adopt(w, target, select=mapping, keep_original=True)
    assert done.kept == f"{w.name(target)}_pre_adopt" and done.rehash is not None
    assert done.mapped == ("DELETE_FLAG", "ACTIVE_FLAG")
    assert set(done.defaulted) == {"CREATE_DATE", "CREATED_BY", "UPDATE_DATE", "UPDATED_BY"}
    assert w.rows(f"SELECT id, name, gone FROM {w.name(target + '_pre_adopt')} ORDER BY id") == [
        (1, "Ann", "N"),
        (2, "Bo", "Y"),
    ]
    assert w.rows(
        f"SELECT id, active_flag, delete_flag, created_by FROM {w.name(target)} ORDER BY id"
    ) == [(1, "Y", "N", "adopt-target"), (2, "N", "Y", "adopt-target")]
    w.run("adopted_merge", **params)
    assert w.rows(f"SELECT name FROM {w.name(target)} WHERE id = 1") == [("Anna",)]


def check_kept_name_collision(w, target):
    """Refuse --keep-original when the kept name exists, leaving both tables unchanged."""
    create_foreign_table(w, target, "SELECT CAST(1 AS BIGINT) AS id")
    create_foreign_table(w, f"{target}_pre_adopt", "SELECT CAST(9 AS BIGINT) AS id")
    w.task(
        "collide",
        SQL_ACTION="APPEND_TABLE",
        TARGET_OBJECT=target,
        SELECT_QUERY="SELECT CAST(1 AS BIGINT) AS id",
    )
    with pytest.raises(HandlerError, match=r"_pre_adopt already exists.*drop or rename"):
        adopt(w, target, keep_original=True)
    assert w.columns(target) == ["id"]
    assert w.rows(f"SELECT id FROM {w.name(target + '_pre_adopt')}") == [(9,)]
