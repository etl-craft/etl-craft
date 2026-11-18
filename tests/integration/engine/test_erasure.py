"""Standing erasure deletes only direct identifier descendants and keeps keys private."""

import pytest
from sqlalchemy import text

from etl_craft.core.actor import acting_as
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ConfigurationError, HandlerError
from fixtures.actions import act
from fixtures.erasure import erasure_project as erasure_project
from fixtures.metadata import add_pipeline, add_task
from fixtures.seeds import seed_project as seed_project


def test_preview_register_erase_list_and_lift(erasure_project):
    ctx = erasure_project
    args = {
        "table": "ds.people",
        "column": "person",
        "value": "private-person-key",
        "reason": "request",
    }
    report = act(ctx, ActionName.ERASE, **args, dry_run=True)
    assert sum(t.rows for t in report.tables) == 1
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 0
    report = act(ctx, ActionName.ERASE, **args)
    assert sum(t.rows for t in report.tables) == 1
    listed = act(ctx, ActionName.ERASURE_LIST)
    assert "private-person-key" not in str(listed)
    assert len(listed.entries) == 1
    act(ctx, ActionName.ERASE, **args, lift=True)
    with pytest.raises(HandlerError, match="already lifted"):
        act(ctx, ActionName.ERASE, **args, lift=True)


def test_missing_secret_refuses_before_registration(erasure_project, monkeypatch):
    monkeypatch.delenv("ERASURE_HMAC")
    with pytest.raises(ConfigurationError, match="Hmac_secret"):
        act(
            erasure_project,
            ActionName.ERASE,
            table="ds.people",
            column="person",
            value="private-person-key",
            reason="request",
        )


def test_failing_delete_never_exposes_bound_key(erasure_project):
    import io
    import logging

    import duckdb
    from sqlalchemy import inspect

    from etl_craft.core.log import configure
    from etl_craft.services.operations.serialization import to_json

    ctx = erasure_project
    key = "private-person-key"
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("ALTER TABLE ds.people RENAME TO people_source")
        conn.execute("CREATE VIEW ds.people AS SELECT * FROM ds.people_source")
    stream = io.StringIO()
    handler = configure("DEBUG", stream=stream)
    try:
        with pytest.raises(HandlerError) as raised:
            act(
                ctx,
                ActionName.ERASE,
                table="ds.people",
                column="person",
                value=key,
                reason=f"request for {key}",
            )
        assert key not in str(raised.value)
        assert "row-level deletion failed" in str(raised.value)
        assert key not in stream.getvalue()
        assert key not in str(to_json(act(ctx, ActionName.ERASURE_LIST)))
        with ctx.engine.connect() as conn:
            quote = conn.dialect.identifier_preparer.quote
            for table in inspect(conn).get_table_names():
                if table.upper().startswith("AUD_") and table.upper() != "AUD_ERASURE_SUBJECTS":
                    rows = conn.execute(text(f"SELECT * FROM {quote(table)}")).mappings().all()
                    assert key not in str(rows), table
    finally:
        logging.getLogger("etl_craft").removeHandler(handler)


@pytest.mark.parametrize("table,column", [("ds.missing", "person"), ("ds.people", "missing")])
def test_unknown_table_or_column_refused_without_registering(erasure_project, table, column):
    ctx = erasure_project
    with pytest.raises(HandlerError) as raised:
        act(
            ctx,
            ActionName.ERASE,
            table=table,
            column=column,
            value="private-person-key",
            reason="request",
        )
    message = str(raised.value)
    assert table in message and column in message and "correct" in message.lower()
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 0


def test_crash_after_upstream_commit_is_finished_by_repeating_erase(erasure_project):
    import os
    import subprocess
    import sys

    import duckdb

    ctx = erasure_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "DOWNSTREAM")
        add_task(
            conn,
            pipeline,
            "COPY",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="ds.copy",
            SELECT_QUERY="SELECT person AS customer,n FROM ds.people",
        )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE TABLE ds.copy AS SELECT person AS customer,n FROM ds.people")
    refreshed = act(ctx, ActionName.PIPELINE_REFRESH)
    assert all(str(r.status) == "SUCCESS" for r in refreshed.refreshes), refreshed
    code = """
import sys
from etl_craft.config import load_config
from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActionName, ActorKind, ApiRole
from etl_craft.engine.connection import engine_db
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.erasure import EraseInput
config = load_config(sys.argv[1])
ctx = OperationContext(engine_db(config), config, Actor('eraser', ActorKind.USER),
                       role=ApiRole.ADMIN, project='default', project_id=1)
invoke(ctx, ActionName.ERASE, EraseInput(table='ds.people',column='person',
       value='private-person-key',reason='request'))
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(ctx.config.config_path)],
        env=os.environ | {"ETL_CRAFT_FAULT": "erasure.after_table:kill"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 137, child.stderr
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ds.people WHERE n=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ds.copy WHERE n=1").fetchone()[0] == 1
    result = act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="finish the earlier request",
    )
    assert sum(t.rows for t in result.tables) == 1
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 1


def test_doctor_reports_unfollowed_table_with_reason_and_remedy(erasure_project):
    import duckdb

    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    ctx = erasure_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        mark_packaged_migrations_applied(conn)
        pipeline = add_pipeline(conn, "AGGREGATE")
        add_task(
            conn,
            pipeline,
            "GROUPED",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="ds.grouped",
            SELECT_QUERY="SELECT person,COUNT(*) AS n FROM ds.people GROUP BY person",
        )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute(
            "CREATE TABLE ds.grouped AS SELECT person,COUNT(*) AS n FROM ds.people GROUP BY person"
        )
    refreshed = act(ctx, ActionName.PIPELINE_REFRESH)
    assert all(str(r.status) == "SUCCESS" for r in refreshed.refreshes), refreshed
    act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="request",
    )
    report = act(ctx, ActionName.DOCTOR)
    messages = " ".join(check.detail for check in report.checks if check.name == "Erasure coverage")
    assert "ds.grouped" in messages
    assert "aggregate" in messages.lower() and "further entry" in messages
    assert "private-person-key" not in messages


def test_case_and_quoting_use_the_same_native_erasure_identity(erasure_project):
    ctx = erasure_project
    act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="request",
    )
    act(
        ctx,
        ActionName.ERASE,
        table='"WAREHOUSE"."DS"."PEOPLE"',
        column='"PERSON"',
        value="private-person-key",
        reason="corrected",
        lift=True,
    )
    assert act(ctx, ActionName.ERASURE_LIST).entries[0]["active_flag"] == "N"


def test_register_guards_allow_only_one_lift_and_no_delete(erasure_project):
    from sqlalchemy.exc import DBAPIError

    ctx = erasure_project
    args = {
        "table": "ds.people",
        "column": "person",
        "value": "private-person-key",
        "reason": "request",
    }
    act(ctx, ActionName.ERASE, **args)
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT CREATED_BY FROM AUD_ERASURE_SUBJECTS")).scalar_one()
            == ctx.actor.name
        )
    for sql in (
        "UPDATE AUD_ERASURE_SUBJECTS SET REASON='changed'",
        "DELETE FROM AUD_ERASURE_SUBJECTS",
    ):
        with pytest.raises(DBAPIError), acting_as(ctx.actor), ctx.engine.begin() as conn:
            conn.execute(text(sql))
    act(ctx, ActionName.ERASE, **args, lift=True)
    with pytest.raises(DBAPIError), acting_as(ctx.actor), ctx.engine.begin() as conn:
        conn.execute(text("UPDATE AUD_ERASURE_SUBJECTS SET LIFT_REASON='changed'"))


def test_opaque_python_and_unmanaged_sql_targets_are_reported_and_untouched(erasure_project):
    import duckdb

    from etl_craft.engine.project_files import collect
    from fixtures.metadata import add_dependency

    ctx = erasure_project
    script = ctx.config.project_dir / "python_scripts/opaque.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "from etl_craft.scripting import ScriptResult\n"
        "def run():\n    return ScriptResult(row_count=0)\n"
    )
    sql = ctx.config.project_dir / "sql_scripts/team.sql"
    sql.parent.mkdir(exist_ok=True)
    sql.write_text("INSERT INTO ds.team SELECT person,n FROM ds.people")
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE='ERASURE_TEST'")
        ).scalar_one()
        source = conn.execute(
            text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE='LAND'")
        ).scalar_one()
        python = add_task(
            conn,
            pipeline,
            "OPAQUE",
            handler="PYTHON",
            SCRIPT_KIND="INGESTION",
            TARGET_OBJECT="ds.opaque",
            SCRIPT_FILE="python_scripts/opaque.py",
        )
        add_dependency(conn, pipeline, python, source)
        add_task(conn, pipeline, "TEAM", handler="SQL_SCRIPT", SCRIPT_FILE="sql_scripts/team.sql")
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE TABLE ds.opaque AS SELECT * FROM ds.people")
        conn.execute("CREATE TABLE ds.team AS SELECT * FROM ds.people")
    act(ctx, ActionName.DEPLOY, files=collect(ctx.config.project_dir))
    result = act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="request",
    )
    blocked = {b.table: b for b in result.unfollowed}
    assert "warehouse.ds.opaque" in blocked and "warehouse.ds.team" in blocked
    assert "Python" in blocked["warehouse.ds.opaque"].reason
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert set(conn.execute("SELECT person FROM ds.opaque").fetchall()) == {
            ("private-person-key",),
            ("retained",),
        }
        assert set(conn.execute("SELECT person FROM ds.team").fetchall()) == {
            ("private-person-key",),
            ("retained",),
        }


def test_cli_preview_apply_retry_and_list_are_safe_json(erasure_project, monkeypatch, capsys):
    import json

    from etl_craft.cli import main
    from etl_craft.core.errors import ExitCode
    from etl_craft.engine.migrations import mark_packaged_migrations_applied
    from fixtures.auth import service_token

    ctx = erasure_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        mark_packaged_migrations_applied(conn)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", service_token(ctx.engine))
    prefix = ["--config", str(ctx.config.config_path), "erase", "--project", "default"]
    args = [
        "--table",
        "ds.people",
        "--column",
        "person",
        "--value",
        "private-person-key",
        "--reason",
        "request",
        "--format",
        "json",
    ]
    assert main(prefix + args + ["--dry-run"]) == ExitCode.SUCCESS
    preview = capsys.readouterr()
    assert json.loads(preview.out)["dry_run"] is True
    for expected in (1, 0):
        assert main(prefix + args) == ExitCode.SUCCESS
        captured = capsys.readouterr()
        assert "private-person-key" not in captured.out + captured.err
        assert sum(t["rows"] for t in json.loads(captured.out)["tables"]) == expected
    assert main([*prefix, "--list", "--format", "json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)["entries"]) == 1
    assert "private-person-key" not in preview.out + preview.err + captured.out + captured.err


@pytest.mark.parametrize("spoofed", ["SQL_ACTION", "SCRIPT_KIND"])
def test_unmanaged_target_cannot_be_made_managed_by_stray_parameters(erasure_project, spoofed):
    import duckdb

    from etl_craft.engine.project_files import collect

    ctx = erasure_project
    script = ctx.config.project_dir / "sql_scripts/team.sql"
    script.parent.mkdir(exist_ok=True)
    script.write_text("INSERT INTO ds.team SELECT person,n FROM ds.people")
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "TEAM")
        add_task(
            conn,
            pipeline,
            "WRITE",
            handler="SQL_SCRIPT",
            TARGET_OBJECT="ds.team",
            SCRIPT_FILE="sql_scripts/team.sql",
            **{spoofed: "CREATE_TABLE" if spoofed == "SQL_ACTION" else "INGESTION"},
        )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE TABLE ds.team AS SELECT * FROM ds.people")
    act(ctx, ActionName.DEPLOY, files=collect(ctx.config.project_dir))
    result = act(
        ctx,
        ActionName.ERASE,
        table="ds.team",
        column="person",
        value="private-person-key",
        reason="request",
    )
    assert not result.tables
    assert any(
        b.table == "warehouse.ds.team" and "unmanaged" in b.reason.lower()
        for b in result.unfollowed
    )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ds.team").fetchone()[0] == 2


def test_short_identifier_does_not_change_its_derived_hmac(erasure_project):
    import duckdb

    ctx = erasure_project
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("INSERT INTO ds.people VALUES ('a',9)")
    result = act(
        ctx, ActionName.ERASE, table="ds.people", column="person", value="a", reason="request"
    )
    with ctx.engine.connect() as conn:
        digest = conn.execute(text("SELECT KEY_HMAC FROM AUD_ERASURE_SUBJECTS")).scalar_one()
    assert all(table.key_hmac == digest for table in result.tables)
    assert act(ctx, ActionName.ERASURE_LIST).entries[0]["key_hmac"] == digest


def test_rename_validates_active_erasure_entries_in_its_writer_transaction(erasure_project):
    ctx = erasure_project
    act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="request",
    )
    result = act(
        ctx,
        ActionName.RENAME,
        pipeline_code="ERASURE_TEST",
        to="ERASURE_RENAMED",
        reason="preserve the standing erasure",
    )
    assert result.pipeline_id is not None
    entries = act(ctx, ActionName.ERASURE_LIST)
    assert len(entries.entries) == 1


def test_failed_register_insert_never_exposes_bound_subject_key(erasure_project, engine_db):
    import traceback

    ctx = erasure_project
    key = "-".join(("private", "person", "key"))
    if engine_db.config.engine.jdbc_url.startswith("jdbc:sqlite:"):
        statements = (
            "CREATE TRIGGER fail_erasure_registration BEFORE INSERT ON AUD_ERASURE_SUBJECTS "
            "BEGIN SELECT RAISE(ABORT,'forced register failure'); END",
        )
    else:
        statements = (
            "CREATE FUNCTION fail_erasure_registration() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'forced register failure'; END $$",
            "CREATE TRIGGER fail_erasure_registration BEFORE INSERT ON AUD_ERASURE_SUBJECTS "
            "FOR EACH ROW EXECUTE FUNCTION fail_erasure_registration()",
        )
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    with pytest.raises(HandlerError, match=r"register|registration") as error:
        act(
            ctx,
            ActionName.ERASE,
            table="ds.people",
            column="person",
            value=key,
            reason="request",
        )
    assert key not in "".join(traceback.format_exception(error.value))
    with ctx.engine.connect() as conn:
        rows = conn.execute(text("SELECT ARGUMENTS AS arguments FROM AUD_ACTIONS")).mappings().all()
    assert key not in str(rows)


def test_sql_writers_never_write_erased_keys_and_keep_null_identifiers(erasure_project):
    import duckdb

    from etl_craft.engine import transitions
    from etl_craft.engine.runlog import RunSelector
    from etl_craft.execution import runner

    ctx = erasure_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "COPYING")
        add_task(
            conn,
            pipeline,
            "COPY",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="ds.copy",
            SELECT_QUERY="SELECT person AS customer,n FROM ds.people",
        )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE TABLE ds.copy AS SELECT person AS customer,n FROM ds.people")
    refreshed = act(ctx, ActionName.PIPELINE_REFRESH)
    assert all(str(r.status) == "SUCCESS" for r in refreshed.refreshes), refreshed
    args = {"table": "ds.people", "column": "person", "value": "private-person-key"}
    act(ctx, ActionName.ERASE, **args, reason="request")
    # A source resends the erased identifier, next to a row with no identifier at all.
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("INSERT INTO ds.people VALUES ('private-person-key',3),(NULL,4)")
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        run = transitions.create_active_run(conn, pipeline)
    with acting_as(ctx.actor):
        runner.run_task(ctx.engine, ctx.config, "COPYING", "COPY", selector=RunSelector(run_id=run))
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute("SELECT customer,n FROM ds.copy ORDER BY n").fetchall() == [
            ("retained", 2),
            (None, 4),
        ]
    act(ctx, ActionName.ERASE, **args, reason="entry corrected", lift=True)
    with acting_as(ctx.actor):
        runner.run_task(
            ctx.engine, ctx.config, "COPYING", "COPY", selector=RunSelector(run_id=run), force=True
        )
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ds.copy WHERE n=3").fetchone()[0] == 1


@pytest.mark.parametrize("fails", [False, True])
def test_a_script_that_resends_an_erased_key_has_it_removed_in_the_same_attempt(
    erasure_project, fails
):
    import duckdb

    from etl_craft.engine import transitions
    from etl_craft.engine.runlog import RunSelector
    from etl_craft.execution import runner

    ctx = erasure_project
    warehouse = ctx.config.project_dir / "warehouse.db"
    script = ctx.config.project_dir / "python_scripts" / "resend.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "import duckdb\n"
        "from etl_craft.scripting import ScriptResult\n"
        "ROWS = \"('private-person-key',7),('new',8)\"\n"
        "def run(task):\n"
        f"    with duckdb.connect({str(warehouse)!r}) as conn:\n"
        "        conn.execute('INSERT INTO ds.people VALUES ' + ROWS)\n"
        + ("    raise RuntimeError('source closed mid-load')\n" if fails else "")
        + "    return ScriptResult(row_count=2)\n"
    )
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "RESENDING")
        add_task(
            conn,
            pipeline,
            "RESEND",
            "PYTHON",
            SCRIPT_FILE="python_scripts/resend.py",
            TARGET_OBJECT="ds.people",
        )
    refreshed = act(ctx, ActionName.PIPELINE_REFRESH)
    assert all(str(r.status) == "SUCCESS" for r in refreshed.refreshes), refreshed
    act(
        ctx,
        ActionName.ERASE,
        table="ds.people",
        column="person",
        value="private-person-key",
        reason="request",
    )
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        run = transitions.create_active_run(conn, pipeline)
    with acting_as(ctx.actor):
        outcome = runner.run_task(
            ctx.engine, ctx.config, "RESENDING", "RESEND", selector=RunSelector(run_id=run)
        )
    assert str(outcome.status) == ("FAILED" if fails else "SUCCESS"), outcome
    with duckdb.connect(str(warehouse)) as conn:
        assert conn.execute("SELECT person FROM ds.people ORDER BY n").fetchall() == [
            ("retained",),
            ("new",),
        ]
