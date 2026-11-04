"""Reference publication, validation refusals and immutable stewardship decisions."""

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl_craft.core.actor import acting_as
from etl_craft.core.enums import ActionName, ApiRole, RunStatus
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.engine import transitions
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task
from fixtures.seeds import seed_project as seed_project


def rows(ctx):
    import duckdb

    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        return conn.execute("SELECT id,name FROM ds.agents ORDER BY id").fetchall()


def test_changed_seed_replaces_exact_rows_and_unchanged_creates_no_run(seed_project):
    ctx, folder, publish = seed_project
    first = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert first.status == SeedStatus.LOADED, first.message
    assert rows(ctx) == [(1, "Ada"), (2, "Bob")]
    # Working-tree bytes are not deployment bytes.
    (folder / "data.csv").write_text("id|name\n3|Cy\n")
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.UNCHANGED
    publish()
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOADED
    assert rows(ctx) == [(3, "Cy")]
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0
        records = (
            conn.execute(
                text(
                    "SELECT STATUS AS status,CREATED_BY AS actor,ERROR_MESSAGE AS error FROM "
                    "AUD_SEED_LOADS"
                )
            )
            .mappings()
            .all()
        )
    assert [row["status"] for row in records] == ["LOADED", "UNCHANGED", "LOADED"]
    assert all(row["actor"] == ctx.actor.name and row["error"] is None for row in records)


@pytest.mark.parametrize("broken", ["catalog", "columns", "value"])
def test_validate_refuses_bad_seed_with_file_row_column_value_and_remedy(seed_project, broken):
    ctx, folder, publish = seed_project
    if broken == "catalog":
        folder.parent.parent.rename(folder.parent.parent.with_name("foreign"))
        expected = ("foreign", "catalog", "warehouse", "move")
    elif broken == "columns":
        (folder / "columns.csv").unlink()
        expected = ("columns.csv", "missing", "expected", "add")
    else:
        (folder / "data.csv").write_text("id|name\nno-integer|Ada\n")
        expected = ("data.csv", "row 2", "column id", "no-integer", "INT", "correct")
    publish()
    report = act(replace(ctx, role=ApiRole.DEVELOPER), ActionName.VALIDATE)
    assert report.failed
    messages = " ".join(f.message for f in report.findings)
    for part in expected:
        assert part.lower() in messages.lower()
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_SEED_LOADS")).scalar_one() == 0


def test_failed_load_records_the_reported_masked_message(seed_project, monkeypatch):
    ctx, _, _ = seed_project
    monkeypatch.setenv("ETL_CRAFT_FAULT", "sql.replace.after_clear")
    result = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert result.status == SeedStatus.FAILED
    for part in ("warehouse.ds.agents", result.seed_load_id, "value=", "expected", "retry"):
        assert part in result.message
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT ERROR_MESSAGE FROM AUD_SEED_LOADS WHERE SEED_LOAD_ID=:id"),
                {"id": result.seed_load_id},
            ).scalar_one()
            == result.message
        )
    assert "Traceback" not in result.message


def test_seed_audit_is_append_only_and_checks_error_pairing(seed_project):
    ctx, _, _ = seed_project
    act(ctx, ActionName.SEED_APPLY)
    for sql in ("UPDATE AUD_SEED_LOADS SET STATUS='UNCHANGED'", "DELETE FROM AUD_SEED_LOADS"):
        with (
            pytest.raises(DBAPIError, match="append-only"),
            acting_as(ctx.actor),
            ctx.engine.begin() as conn,
        ):
            conn.execute(text(sql))
    for status, error in (("FAILED", None), ("LOADED", "bad")):
        with pytest.raises(DBAPIError), acting_as(ctx.actor), ctx.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO AUD_SEED_LOADS SELECT "
                    "PROJECT_ID,CATALOG_NAME,SCHEMA_NAME,TABLE_NAME,CONTENT_SHA256,"
                    ":id,:status,:error,CREATED_BY,CREATED_AT "
                    "FROM AUD_SEED_LOADS LIMIT 1"
                ),
                {"id": status, "status": status, "error": error},
            )


def test_seed_apply_requires_developer(seed_project):
    ctx, _, _ = seed_project
    with pytest.raises(PermissionDeniedError):
        act(replace(ctx, role=ApiRole.OPERATOR), ActionName.SEED_APPLY)


@pytest.mark.parametrize("status", [RunStatus.SUCCESS, RunStatus.FAILED])
@pytest.mark.parametrize("retarget", [False, True])
def test_lock_uses_successful_upload_run_pinned_target(seed_project, status, retarget):
    ctx, folder, publish = seed_project
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOADED
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "STEWARD")
        task = add_task(
            conn,
            pipeline,
            "merge",
            "SQL",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="ds.agents",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
            SELECT_QUERY="SELECT 1 AS id, 'x' AS name",
        )
        run = transitions.create_active_run(conn, pipeline)
        conn.execute(
            text(
                "INSERT INTO AUD_UPLOADS "
                "(PIPELINE_ID,ACCOUNT,FILE_NAME,SIZE_BYTES,PIPELINE_RUN_ID,STATUS,UPLOADED_AT) "
                "VALUES (:pipeline,'alice','data.csv',1,:run,'LOADED',"
                "'2026-11-01 00:00:00+00:00')"
            ),
            {"pipeline": pipeline, "run": run},
        )
        transitions.finalize_pipeline_run(conn, run, status)
        if retarget:
            from fixtures.metadata import add_table

            target = add_table(conn, "warehouse.ds.other")
            conn.execute(
                text("UPDATE CFG_TASKS SET TARGET_TABLE_ID=:target WHERE TASK_ID=:task"),
                {"target": target, "task": task},
            )
    (folder / "data.csv").write_text("id|name\n3|Cy\n")
    publish()
    outcome = act(ctx, ActionName.SEED_APPLY).loads[0]
    if status == RunStatus.SUCCESS:
        assert outcome.status == SeedStatus.LOCKED, outcome.message
        assert rows(ctx) == [(1, "Ada"), (2, "Bob")]
        assert "upload" in outcome.message and "STEWARD" in outcome.message
    else:
        assert outcome.status == SeedStatus.LOADED, outcome.message
        assert rows(ctx) == [(3, "Cy")]


def test_retargeting_toward_a_seed_does_not_add_a_lock(seed_project):
    ctx, _, _ = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "STEWARD")
        task = add_task(
            conn, pipeline, "write", TARGET_OBJECT="ds.other", SQL_ACTION="CREATE_TABLE"
        )
        run = transitions.create_active_run(conn, pipeline)
        conn.execute(
            text(
                "INSERT INTO AUD_UPLOADS (PIPELINE_ID,ACCOUNT,FILE_NAME,SIZE_BYTES,"
                "PIPELINE_RUN_ID,STATUS,UPLOADED_AT) VALUES (:pipeline,'alice','data.csv',1,"
                ":run,'LOADED','2026-11-01 00:00:00+00:00')"
            ),
            {"pipeline": pipeline, "run": run},
        )
        transitions.finalize_pipeline_run(conn, run, RunStatus.SUCCESS)
        from fixtures.metadata import add_table

        target = add_table(conn, "warehouse.ds.agents")
        conn.execute(
            text("UPDATE CFG_TASKS SET TARGET_TABLE_ID=:target WHERE TASK_ID=:task"),
            {"target": target, "task": task},
        )
    result = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert result.status == SeedStatus.LOADED, result.message


@pytest.mark.parametrize("upload_status", ["REFUSED", "FAILED", "LOADED"])
def test_lock_normalizes_case_and_quoting_and_ignores_unaccepted_uploads(
    seed_project, upload_status
):
    ctx, _, _ = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "STEWARD")
        add_task(
            conn,
            pipeline,
            "write",
            TARGET_OBJECT='"WAREHOUSE"."DS"."AGENTS"',
            SQL_ACTION="CREATE_TABLE",
        )
        run = transitions.create_active_run(conn, pipeline)
        conn.execute(
            text(
                "INSERT INTO AUD_UPLOADS (PIPELINE_ID,ACCOUNT,FILE_NAME,SIZE_BYTES,"
                "PIPELINE_RUN_ID,STATUS,UPLOADED_AT) VALUES (:pipeline,'alice','data.csv',1,"
                ":run,:status,'2026-11-01 00:00:00+00:00')"
            ),
            {"pipeline": pipeline, "run": run, "status": upload_status},
        )
        transitions.finalize_pipeline_run(conn, run, RunStatus.SUCCESS)
        conn.execute(
            text("UPDATE AUD_UPLOADS SET STATUS=:status WHERE PIPELINE_RUN_ID=:run"),
            {"status": upload_status, "run": run},
        )
    outcome = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert outcome.status == (
        SeedStatus.LOCKED if upload_status == "LOADED" else SeedStatus.LOADED
    ), outcome.message


def test_seed_and_merge_serialize_on_the_same_target(seed_project, monkeypatch):
    import threading
    from contextlib import contextmanager

    from etl_craft.handlers import sql
    from etl_craft.handlers.registry import TaskContext
    from etl_craft.handlers.resources import LocalLocker
    from fixtures.races import two_at_once

    ctx, folder, publish = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "MERGE")
        task_id = add_task(
            conn,
            pipeline,
            "merge",
            TARGET_OBJECT="ds.agents",
            SQL_ACTION="SCD1_MERGE",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
            SELECT_QUERY="SELECT 9 AS id, 'Nine' AS name",
        )
        run = transitions.create_active_run(conn, pipeline)
        task_run = transitions.find_or_create_task_run(conn, task_id, run).task_run_id
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOADED
    (folder / "data.csv").write_text("id|name\n3|Cy\n")
    publish()
    from datetime import UTC, datetime

    context = TaskContext(
        ctx.config,
        pipeline,
        "MERGE",
        task_id,
        "merge",
        run,
        task_run,
        1,
        "SQL",
        "FULL",
        {
            "TARGET_OBJECT": "ds.agents",
            "SQL_ACTION": "SCD1_MERGE",
            "MERGE_KEY": "id",
            "MERGE_COMPARE_COLUMNS": "name",
            "SELECT_QUERY": "SELECT 9 AS id, 'Nine' AS name",
        },
        started_at=datetime.now(UTC),
        writer=ctx.actor.name,
    )
    original = LocalLocker.hold
    active = []
    acquired = []
    guard = threading.Lock()

    @contextmanager
    def observed(self, key, name, wait_seconds):
        with original(self, key, name, wait_seconds):
            if name.startswith("target "):
                with guard:
                    assert not active
                    active.append(name)
                    acquired.append(key)
            try:
                yield
            finally:
                if name.startswith("target "):
                    with guard:
                        active.remove(name)

    monkeypatch.setattr(LocalLocker, "hold", observed)
    result, _ = two_at_once(
        lambda: act(ctx, ActionName.SEED_APPLY),
        lambda: sql.run(context, ctx.engine),
        at=(LocalLocker, "hold"),
        timeout=30,
    )
    assert result.loads[0].status == SeedStatus.LOADED, result.loads[0].message
    assert len(acquired) == 2 and len(set(acquired)) == 1
    assert rows(ctx) in ([(3, "Cy")], [(3, "Cy"), (9, "Nine")])


def test_failed_load_masks_urls_and_secret_values_before_return_and_audit(
    seed_project, monkeypatch
):
    from etl_craft.core.errors import HandlerError
    from etl_craft.services.operations import seeds

    ctx, _, _ = seed_project
    monkeypatch.setenv("SEED_TEST_SECRET", "do-not-record-this")

    def refuse(*args):
        raise HandlerError(
            "jdbc:postgresql://alice:url-password@host/db?token=url-token do-not-record-this"
            "\nTraceback vendor frame must not be retained"
        )

    monkeypatch.setattr(seeds, "replace_seed", refuse)
    result = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert result.status == SeedStatus.FAILED
    assert "Traceback" not in result.message
    for secret in ("url-password", "url-token", "do-not-record-this"):
        assert secret not in result.message
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT ERROR_MESSAGE FROM AUD_SEED_LOADS")).scalar_one()
            == result.message
        )


@pytest.mark.parametrize(
    "table,content,column,key,value,expected",
    [
        (
            "support_areas",
            b"area_code|area_name\nbilling|Billing corrections\n",
            "area_name",
            "area_code",
            "billing",
            "Billing corrections",
        ),
        (
            "agents",
            b"agent_code|agent_name|team|email\nA01|Ann corrected|east|ann@example.com\n",
            "agent_name",
            "agent_code",
            "A01",
            "Ann corrected",
        ),
        (
            "customer_types",
            b"customer_type_code|customer_type_name\nbusiness|Business corrected\n",
            "customer_type_name",
            "customer_type_code",
            "business",
            "Business corrected",
        ),
    ],
)
def test_demo_reference_seeds_lock_after_real_stewardship_upload(
    seed_project, table, content, column, key, value, expected
):
    import shutil
    from pathlib import Path

    import duckdb

    from etl_craft.core.actor import SYSTEM_ACTOR, Actor
    from etl_craft.core.enums import ActorKind
    from etl_craft.dialects.engine import for_engine
    from etl_craft.engine.queries import run_script
    from etl_craft.engine.runlog import RunSelector
    from etl_craft.execution.pipeline import run_pipeline
    from etl_craft.services.operations.uploads import UploadRequest, receive

    ctx, _, publish = seed_project
    demo = Path(__file__).resolve().parents[3] / "tests/fixtures/seed_demo"
    for name in ("seeds", "python_scripts", "validation_scripts"):
        shutil.copytree(demo / name, ctx.config.project_dir / name, dirs_exist_ok=True)
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE SCHEMA info; CREATE SCHEMA lnd")
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        run_script(
            conn,
            for_engine(conn).split_statements((demo / "metadata/seed_stewardship.sql").read_text()),
        )
    publish()
    first = act(ctx, ActionName.SEED_APPLY)
    assert len(first.loads) == 5
    assert all(load.status == SeedStatus.LOADED for load in first.loads), first
    act(ctx, ActionName.ACCOUNT_ADD, name="steward", role=ApiRole.ADMIN, oidc_subject="steward")
    uploader = replace(ctx, actor=Actor("steward", ActorKind.USER))
    pipeline_code = f"SI_STEWARD_DS_{table.upper()}"
    with receive(uploader, UploadRequest(pipeline_code=pipeline_code)) as receipt:
        receipt.begin_file("corrections.csv", "text/csv")
        receipt.write(content)
    run_id = receipt.result["pipeline_run_id"]
    with acting_as(SYSTEM_ACTOR):
        result = run_pipeline(
            ctx.engine,
            ctx.config,
            pipeline_code,
            selector=RunSelector(run_id=run_id),
        )
    assert result.status == RunStatus.SUCCESS
    outcomes = {load.table: load for load in act(ctx, ActionName.SEED_APPLY).loads}
    assert outcomes[f"warehouse.ds.{table}"].status == SeedStatus.LOCKED
    assert outcomes["warehouse.ds.sources"].status == SeedStatus.UNCHANGED
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute(
            f"SELECT {column} FROM ds.{table} WHERE {key}=?", [value]
        ).fetchone() == (expected,)


def test_first_successful_completion_owns_handover_even_after_an_older_upload_is_repaired(
    seed_project,
):
    from datetime import UTC, datetime

    ctx, _, _ = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        for code, day in (("OLDER_UPLOAD", 3), ("FIRST_SUCCESS", 2)):
            pipeline = add_pipeline(conn, code)
            add_task(conn, pipeline, "write", TARGET_OBJECT="ds.agents", SQL_ACTION="CREATE_TABLE")
            run = transitions.create_active_run(conn, pipeline)
            conn.execute(
                text(
                    "INSERT INTO AUD_UPLOADS (PIPELINE_ID,ACCOUNT,FILE_NAME,SIZE_BYTES,"
                    "PIPELINE_RUN_ID,STATUS,UPLOADED_AT) VALUES (:pipeline,'alice','data.csv',1,"
                    ":run,'LOADED',:uploaded)"
                ),
                {"pipeline": pipeline, "run": run, "uploaded": datetime(2020, 1, 1, tzinfo=UTC)},
            )
            transitions.finalize_pipeline_run(conn, run, RunStatus.SUCCESS)
            conn.execute(
                text("UPDATE AUD_PIPELINES_RUN_LOG SET END_DATE=:ended WHERE PIPELINE_RUN_ID=:run"),
                {"ended": datetime(2020, 1, day, tzinfo=UTC), "run": run},
            )
    outcome = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert outcome.status == SeedStatus.LOCKED
    assert "FIRST_SUCCESS" in outcome.message and "upload 2" in outcome.message


def test_reopening_and_failing_a_successful_upload_run_never_unlocks_its_seed(seed_project):
    from datetime import UTC, datetime

    from etl_craft.core.actor import purpose
    from etl_craft.engine.queries import statement

    ctx, _, _ = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "STEWARD")
        add_task(conn, pipeline, "write", TARGET_OBJECT="ds.agents", SQL_ACTION="CREATE_TABLE")
        run = transitions.create_active_run(conn, pipeline)
        conn.execute(
            text(
                "INSERT INTO AUD_UPLOADS (PIPELINE_ID,ACCOUNT,FILE_NAME,SIZE_BYTES,"
                "PIPELINE_RUN_ID,STATUS,UPLOADED_AT) VALUES (:pipeline,'alice','data.csv',1,"
                ":run,'LOADED',:uploaded)"
            ),
            {"pipeline": pipeline, "run": run, "uploaded": datetime(2020, 1, 1, tzinfo=UTC)},
        )
        transitions.finalize_pipeline_run(conn, run, RunStatus.SUCCESS)
        transitions.reopen_run(conn, run, ctx.actor, reason="correct a task")
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOCKED
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        transitions.finalize_pipeline_run(conn, run, RunStatus.FAILED)
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOCKED
    token = purpose.set("retention")
    try:
        with acting_as(ctx.actor), ctx.engine.begin() as conn:
            parameters = {"project_id": 1, "cutoff": datetime(2030, 1, 1, tzinfo=UTC)}
            assert (
                conn.execute(
                    statement(conn, "retention_aud_run_interventions_count"), parameters
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    statement(conn, "retention_aud_run_interventions"), parameters
                ).rowcount
                == 0
            )
    finally:
        purpose.reset(token)
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOCKED


def test_omitted_seed_column_is_unchanged_on_reapplication(seed_project):
    ctx, folder, publish = seed_project
    with (folder / "columns.csv").open("a") as stream:
        stream.write("upload_id|BIGINT|N\n")
    publish()
    loaded = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert loaded.status == SeedStatus.LOADED, loaded.message
    assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.UNCHANGED
    import duckdb

    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute("SELECT id,upload_id FROM ds.agents ORDER BY id").fetchall() == [
            (1, None),
            (2, None),
        ]
