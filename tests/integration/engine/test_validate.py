"""``validate``: every problem in the metadata, found without running anything, both Engine DBs."""

import json
import logging
import re
from dataclasses import replace

import pytest
import yaml
from sqlalchemy import text

from etl_craft.cli import main
from etl_craft.config import load_config
from etl_craft.core.errors import ExitCode, MetadataError
from etl_craft.services.doctor import Status
from etl_craft.services.validate import validate
from fixtures.auth import service_token
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_pipeline_dependency,
    add_table,
    add_task,
)
from fixtures.metadata import insert as insert_row

GOOD_SCRIPT = "def run(task):\n    return None\n"


@pytest.fixture(autouse=True)
def restore_logger():
    logger = logging.getLogger("etl_craft")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


@pytest.fixture
def project(engine_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ETL_CRAFT_TOKEN", service_token(engine_db.engine))
    """A project with a DuckDB warehouse, email, a SQL file and an Python script."""
    profile = engine_db.config.engine
    schema = "public" if profile.jdbc_url.startswith("jdbc:postgresql") else "main"
    block = {"Jdbc_url": profile.jdbc_url, "Schema": schema}
    if profile.auth_mode != "NONE":
        block |= {
            "User": profile.user,
            "Auth_mode": profile.auth_mode,
            "Secret": profile.secret_var,
        }
    root = (engine_db.config.config_path or tmp_path / "craft-connector.yml").parent
    raw = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {
            "Project": "default",
            "Email": {"Host": "localhost", "Port": 1025, "From_address": "etl@x.io"},
        },
        "Engine": {"dev": block},
        "Warehouse": {"dev": {"Jdbc_url": "jdbc:duckdb:analytics.duckdb", "Schema": "main"}},
    }
    (root / "craft-connector.yml").write_text(yaml.safe_dump(raw, sort_keys=False), "utf-8")
    (root / "sql_scripts").mkdir(exist_ok=True)
    (root / "sql_scripts" / "orders.sql").write_text("SELECT id, amount FROM raw.orders", "utf-8")
    (root / "python_scripts").mkdir(exist_ok=True)
    (root / "python_scripts" / "load.py").write_text(GOOD_SCRIPT, "utf-8")
    monkeypatch.chdir(root)
    return engine_db.engine, load_config(root / "craft-connector.yml"), root


def add_rule(conn, pipeline, task, name, *, key="id", target="sales.orders", sql=None):
    return insert_row(
        conn,
        "INSERT INTO CFG_BUSINESS_RULES (BUSINESS_RULE_NAME, PIPELINE_ID, TASK_ID, "
        "BUSINESS_RULE_SQL, BUSINESS_RULE_TYPE, BUSINESS_RULE_KEY_COLUMN, TARGET_TABLE_ID, "
        "SEQUENCE_NUMBER) VALUES (:name, :p, :t, :rule_sql, 'REJECT', :key, :target, 1)",
        "BUSINESS_RULE_ID",
        name=name,
        p=pipeline,
        t=task,
        rule_sql=sql or f"SELECT {key} FROM $$rows_in_scope t WHERE t.amount < 0",
        key=key,
        target=add_table(conn, target),
    )


def good_pipeline(conn, code="SALES"):
    """ingest, then stage (from a file) and setup, then load, rules and alert."""
    p = add_pipeline(conn, code)
    ingest = add_task(
        conn, p, "ingest", "PYTHON", SCRIPT_FILE="python_scripts/load.py", INPUT_PARAMS='{"a": 1}'
    )
    setup = add_task(
        conn,
        p,
        "setup",
        SQL_ACTION="SETUP_TABLE",
        TARGET_OBJECT="sales.orders",
        SCRIPT_FILE="sql_scripts/orders.sql",
    )
    load = add_task(
        conn,
        p,
        "load",
        SQL_ACTION="SCD1_MERGE",
        TARGET_OBJECT="sales.orders",
        SELECT_QUERY="SELECT id, amount FROM staging.orders",
        MERGE_KEY="id",
        MERGE_COMPARE_COLUMNS="amount",
        DOCUMENTATION="Merges orders.",
    )
    rules = add_task(conn, p, "rules", "BUSINESS_RULES")
    add_rule(conn, p, rules, "negative amount")
    email_channel(conn)
    add_task(
        conn,
        p,
        "alert",
        "ALERT",
        ALERT_CHANNEL="ops",
        ALERT_SUBJECT="$$pipeline_code: $$trigger",
        ALERT_BODY="Run $$pipeline_run_id finished.",
    )
    add_dependency(conn, p, setup, ingest)
    add_dependency(conn, p, load, setup)
    add_dependency(conn, p, rules, load, "HAS_DATA")
    return p


def email_channel(conn):
    """The project's EMAIL channel ``ops``, once."""
    conn.execute(
        text(
            "INSERT INTO CFG_ALERT_CHANNELS(PROJECT_ID,CHANNEL_NAME,KIND,RECIPIENTS) "
            "SELECT 1,'ops','EMAIL','ops@x.io' WHERE NOT EXISTS "
            "(SELECT 1 FROM CFG_ALERT_CHANNELS WHERE CHANNEL_NAME='ops')"
        )
    )


def found(report):
    return [(f.where, f.status, f.message) for f in report.findings]


def test_a_clean_project_has_no_findings(project):
    engine, config, _ = project
    with engine.begin() as conn:
        good_pipeline(conn)
    report = validate(engine, config)
    assert found(report) == []
    assert (report.pipelines, report.tasks, report.failed) == (1, 5, False)


def test_task_definitions_are_checked_with_the_handlers_own_rules(project):
    engine, config, root = project
    (root / "python_scripts" / "two.py").write_text("def run(a, b):\n    pass\n", "utf-8")
    (root / "python_scripts" / "broken.py").write_text("def run(:\n", "utf-8")
    (root / "python_scripts" / "none.py").write_text("x = 1\n", "utf-8")
    with engine.begin() as conn:
        p = add_pipeline(conn, "BAD")
        add_task(conn, p, "no_action", TARGET_OBJECT="s.t", SELECT_QUERY="SELECT 1 AS a")
        add_task(
            conn,
            p,
            "writes",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="s.t",
            SELECT_QUERY="DELETE FROM s.t",
        )
        add_task(
            conn,
            p,
            "no_file",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="s.u",
            SCRIPT_FILE="sql_scripts/missing.sql",
        )
        add_task(
            conn,
            p,
            "typo",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="s.v",
            SELECT_QUERY="SELECT 1 AS a",
            MERGE_KEYS="a",
            TASK_TIMEOUT_SECONDS="soon",
            SOURCE_SQL_FILE="sql_scripts/old.sql",
        )
        add_task(
            conn,
            p,
            "orphan_setup",
            SQL_ACTION="SETUP_TABLE",
            TARGET_OBJECT="s.w",
            SELECT_QUERY="SELECT 1 AS a",
        )
        add_task(
            conn,
            p,
            "iceberg_path",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="s.x",
            SELECT_QUERY="SELECT 1 AS a",
            EXTERNAL_LOCATION="s3://b/x",
        )
        add_task(
            conn,
            p,
            "engine_columns",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="s.z",
            SELECT_QUERY="SELECT id, PIPELINE_RUN_ID, row_id AS ROW_ID FROM s.y",
        )
        add_task(conn, p, "two_args", "PYTHON", SCRIPT_FILE="python_scripts/two.py")
        add_task(conn, p, "syntax", "PYTHON", SCRIPT_FILE="python_scripts/broken.py")
        add_task(
            conn, p, "no_run", "PYTHON", SCRIPT_FILE="python_scripts/none.py", INPUT_PARAMS="[1]"
        )
        add_task(conn, p, "no_script", "PYTHON", SCRIPT_FILE="python_scripts/gone.py")
        add_task(conn, p, "no_rules", "BUSINESS_RULES")
        add_task(
            conn,
            p,
            "rebuild",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="s.y",
            SELECT_QUERY="SELECT 1 AS a",
        )
        rules = add_task(conn, p, "rules", "BUSINESS_RULES")
        add_rule(conn, p, rules, "on row id", key="ROW_ID", target="s.y")
        add_rule(conn, p, rules, "two statements", target="s.y", sql="SELECT 1; SELECT 2")
        add_task(
            conn,
            p,
            "alert",
            "ALERT",
            ALERT_CHANNEL="nowhere",
        )
        for code in (
            "no_action",
            "writes",
            "no_file",
            "typo",
            "orphan_setup",
            "iceberg_path",
            "engine_columns",
            "two_args",
            "syntax",
            "no_run",
            "no_script",
            "no_rules",
            "rules",
        ):
            upstream = conn.execute(
                text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE = :c AND PIPELINE_ID = :p"),
                {"c": code, "p": p},
            ).scalar_one()
            alert = conn.execute(
                text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE = 'alert'")
            ).scalar_one()
            add_dependency(conn, p, alert, upstream, "ALWAYS")
    report = validate(engine, config)
    by_task = {}
    for f in report.findings:
        by_task.setdefault(f.where, []).append((f.status, f.message))
    assert report.failed
    fail = Status.FAIL

    def only(task):
        ((status, message),) = by_task[f"BAD.{task}"]
        assert status is fail
        return message

    assert only("no_action").startswith("SQL_ACTION is required")
    assert "read-only" in only("writes")
    assert "missing.sql" in only("no_file")
    assert all(status is fail for status, _ in by_task["BAD.typo"])
    messages = "\n".join(message for _, message in by_task["BAD.typo"])
    for part in ("TASK_TIMEOUT_SECONDS='soon'", "MERGE_KEYS", "SOURCE_SQL_FILE", "upgrade"):
        assert part in messages
    assert "set SETUP_FOR" in only("orphan_setup")
    assert "EXTERNAL_LOCATION does not apply to DuckDB" in only("iceberg_path")
    assert only("engine_columns") == (
        "the SELECT returns PIPELINE_RUN_ID, ROW_ID, which etl-craft writes itself; leave them "
        "out, or alias them"
    )
    assert only("two_args") == (
        "python_scripts/two.py: run takes 2 arguments; it takes the task, or nothing"
    )
    assert only("syntax").startswith(
        "SCRIPT_FILE='python_scripts/broken.py' has a syntax error at line 1"
    )
    assert "INPUT_PARAMS must be a JSON object" in only("no_run")
    assert "gone.py" in only("no_script")
    assert "no active row in CFG_BUSINESS_RULES" in only("no_rules")
    rules_messages = [m for _, m in by_task["BAD.rules"]]
    assert any(
        "BUSINESS_RULE_KEY_COLUMN is ROW_ID, but BAD.rebuild rebuilds s.y" in m
        for m in rules_messages
    )
    assert any("must be one read-only SELECT" in m for m in rules_messages)
    assert only("alert").startswith("ALERT_CHANNEL='nowhere': missing or inactive")
    assert "BAD.rebuild" not in by_task


def test_dependencies_and_pipeline_settings(project):
    engine, config, _ = project
    with engine.begin() as conn:
        good = good_pipeline(conn, "GOOD")
        up = add_pipeline(conn, "UP")
        off = add_task(conn, up, "off", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        down = add_pipeline(conn, "DOWN")
        waits = add_task(conn, down, "waits", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        rules_data = add_task(
            conn, down, "after_rules", "PYTHON", SCRIPT_FILE="python_scripts/load.py"
        )
        alert = add_task(conn, down, "alert", "ALERT", ALERT_CHANNEL="ops")
        add_dependency(conn, down, waits, off, upstream_pipeline=up)
        rules = conn.execute(
            text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE = 'rules'")
        ).scalar_one()
        add_dependency(conn, down, rules_data, rules, "HAS_DATA", upstream_pipeline=good)
        add_dependency(conn, down, alert, waits, "SUCCESS")
        conn.execute(text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID = :t"), {"t": off})
        add_pipeline_dependency(conn, down, good)
        add_pipeline_dependency(conn, good, down)
        gone = add_pipeline(conn, "GONE")
        add_pipeline_dependency(conn, down, gone)
        conn.execute(
            text("UPDATE CFG_PIPELINES SET ACTIVE_FLAG = 'N' WHERE PIPELINE_ID = :p"), {"p": gone}
        )
        conn.execute(
            text("UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS = :v WHERE PIPELINE_ID = :p"),
            {"p": down, "v": json.dumps({"RETRIES": "3", "TAG": ["x"]})},
        )
        # Legacy metadata must still receive a useful validator diagnostic.
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        else:
            conn.exec_driver_sql("ALTER TABLE CFG_PIPELINES DROP CONSTRAINT ck_pipelines_code")
            conn.exec_driver_sql("ALTER TABLE CFG_TASKS DROP CONSTRAINT ck_tasks_code")
        bad_code = add_pipeline(conn, "bad code")
        add_task(conn, bad_code, "x.y", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    report = validate(engine, config)
    got = found(report)
    fail = Status.FAIL
    assert (
        "DOWN.waits",
        fail,
        "depends on UP.off, whose task is inactive and no longer runs, so once its last run is "
        "consumed the dependency is never satisfied again; deactivate the dependency too, or "
        "reactivate it",
    ) in got
    assert (
        "DOWN.after_rules",
        fail,
        "has a HAS_DATA dependency on GOOD.rules, which is a BUSINESS_RULES task and reports no "
        "target rows, so the dependency is never satisfied and the task is always skipped; use "
        "SUCCESS",
    ) in got
    # Alerts start from events, so their dependencies are never judged as reporting order.
    assert [g for g in got if g[0] == "DOWN.alert"] == []
    assert (
        "DOWN",
        fail,
        "pipeline dependencies form a cycle (DOWN -> GOOD -> DOWN), so none of these pipelines "
        "can start",
    ) in got
    for key in ("RETRIES", "TAG"):
        assert any(
            where == "DOWN" and status is fail and key in message and "TAGS" in message
            for where, status, message in got
        )
    assert any(w == "DOWN" and "GONE, which is inactive" in m for w, _, m in got)
    assert any(
        w == "bad code" and m.startswith("PIPELINE_CODE='bad code' must start") for w, _, m in got
    )
    assert any(w == "bad code.x.y" and m.startswith("TASK_CODE='x.y'") for w, _, m in got)
    # The rules task reports no rows, but its own pipeline is clean apart from the cycle.
    assert [f for f in got if f[0].startswith("GOOD.")] == []


def test_a_cycle_inside_a_pipeline(project):
    engine, config, _ = project
    with engine.begin() as conn:
        p = add_pipeline(conn, "LOOP")
        a = add_task(conn, p, "a", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        b = add_task(conn, p, "b", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        add_dependency(conn, p, a, b)
        add_dependency(conn, p, b, a)
    (finding,) = validate(engine, config).findings
    assert finding.where == "LOOP" and "cycle" in finding.message


def test_the_command(project, capsys):
    engine, _, _ = project
    with engine.begin() as conn:
        good_pipeline(conn)
        p = add_pipeline(conn, "OTHER")
        add_task(conn, p, "bad", "PYTHON")
    assert main(["validate", "--pipeline-code", "SALES"]) == ExitCode.SUCCESS
    assert (
        capsys.readouterr().out == "checked 1 pipeline(s) and 5 task(s): 0 failed, 0 warning(s)\n"
    )
    assert main(["validate"]) == ExitCode.FAILURE
    assert capsys.readouterr().out.splitlines() == [
        "[FAIL] OTHER.bad: SCRIPT_FILE is required for HANDLER=PYTHON, such as "
        "python_scripts/load.py",
        "checked 2 pipeline(s) and 6 task(s): 1 failed, 0 warning(s)",
    ]
    assert main(["validate", "--pipeline-code", "NOPE"]) == ExitCode.METADATA
    with pytest.raises(MetadataError):
        validate(engine, load_config("craft-connector.yml"), "NOPE")


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "ALERT_CHANNEL is required for HANDLER=ALERT"),
        ({"ALERT_CHANNEL": "ops", "ALERT_ON": "FAILED"}, "ALERT_ON='FAILED': expected FAILURE"),
        ({"ALERT_CHANNEL": "ops", "ALERT_BODY": "$$when"}, r"unknown token\(s\) \$\$when"),
        ({"ALERT_CHANNEL": "hooks", "EMAIL_PIPELINES": "ALL"}, "EMAIL channels only"),
    ],
)
def test_alert_tasks_are_checked_against_their_channel(project, params, message):
    engine, config, _ = project
    with engine.begin() as conn:
        p = good_pipeline(conn, "WATCHED")
        conn.execute(
            text(
                "INSERT INTO CFG_ALERT_CHANNELS(PROJECT_ID,CHANNEL_NAME,KIND,URL_SECRET,"
                "SIGNING_SECRET) VALUES(1,'hooks','WEBHOOK','HOOK_URL','HOOK_KEY')"
            )
        )
        add_task(conn, p, "watcher", "ALERT", **params)
    got = found(validate(engine, config))
    assert [w for w, _, _ in got] == ["WATCHED.watcher"]
    assert re.search(message, got[0][2]), got


@pytest.mark.parametrize("default", ["NATIVE", "ICEBERG"])
@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("active", [False, True])
def test_target_formats_are_compared_across_pipelines_and_qualified_names(
    project, default, conflicting, active
):
    engine, config, _ = project
    profile = replace(
        config.warehouse,
        jdbc_url="jdbc:snowflake://account.snowflakecomputing.com/?db=analytics",
    )
    config = replace(config, warehouse=profile, warehouse_table_format=default)
    with engine.begin() as conn:
        p = add_pipeline(conn, "A")
        q = add_pipeline(conn, "B")
        add_task(
            conn,
            p,
            "setup",
            SQL_ACTION="SETUP_TABLE",
            SETUP_FOR="APPEND_TABLE",
            TARGET_OBJECT="sales.orders",
            SELECT_QUERY="SELECT 1 AS id",
        )
        other = add_task(
            conn,
            q,
            "append",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="ANALYTICS.SALES.ORDERS",
            TABLE_FORMAT=("ICEBERG" if default == "NATIVE" else "NATIVE")
            if conflicting
            else default,
            SELECT_QUERY="SELECT 1 AS id",
        )
        add_task(
            conn,
            q,
            "separate",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="elsewhere.sales.orders",
            SELECT_QUERY="SELECT 1 AS id",
        )
        if not active:
            conn.execute(
                text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID = :id"), {"id": other}
            )
    report = validate(engine, config)
    conflicts = [f for f in report.findings if "different table formats" in f.message]
    if not conflicting or not active:
        assert conflicts == []
        return
    assert {f.where for f in conflicts} == {"A.setup", "B.append"}
    assert all(
        "analytics.sales.orders" in f.message and "A.setup" in f.message and "B.append" in f.message
        for f in conflicts
    )
    scoped = validate(engine, config, "A")
    assert any(f.where == "A.setup" and "B.append" in f.message for f in scoped.findings)


@pytest.mark.parametrize(
    "parameters",
    [
        {"RETRIES": "-1"},
        {"RETRY_DELAY_SECONDS": "later"},
        {"RETRY_BACKOFF": "nan"},
    ],
)
def test_validate_rejects_invalid_retry_parameters(project, parameters):
    engine, config, _ = project
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(conn, pipeline, "load", handler="PYTHON", PYTHON_SCRIPT="load.py", **parameters)
    report = validate(engine, config)
    assert any("CFG_TASK_PARAMETERS." in check.message for check in report.findings)


def test_managed_sql_parse_failure_is_an_error_naming_the_line_column_and_remedy(project):
    engine, config, root = project
    (root / "sql_scripts" / "orders.sql").write_text(
        "SELECT id,\n       amount FROM raw.orders WHERE", "utf-8"
    )
    with engine.begin() as conn:
        p = good_pipeline(conn)
        rules = conn.execute(
            text("SELECT TASK_ID AS task_id FROM CFG_TASKS WHERE TASK_CODE = 'rules'")
        ).scalar_one()
        add_rule(conn, p, rules, "unfinished", sql="SELECT 1 FROM sales.limits l WHERE")

    report = validate(engine, config)

    assert report.failed
    assert any(
        "could not verify BUSINESS_RULE_SQL output" in finding.message
        for finding in report.findings
    )
    warnings = {where: message for where, status, message in found(report) if status is Status.WARN}
    errors = {where: message for where, status, message in found(report) if status is Status.FAIL}
    assert errors["SALES.setup"].startswith(
        "SCRIPT_FILE='sql_scripts/orders.sql': managed SELECT must parse as duckdb SQL; "
        "sqlglot: line 2, column "
    )
    assert "fix the SQL" in errors["SALES.setup"]
    assert "SQL_SCRIPT" in errors["SALES.setup"]
    assert "SALES.setup" not in warnings
    assert warnings["SALES.rules"].startswith(
        "business rule 'unfinished': sqlglot cannot read it as duckdb SQL (line 1, column "
    )


@pytest.mark.parametrize("parameter", ["MERGE_KEY", "MERGE_COMPARE_COLUMNS"])
def test_validate_refuses_repeated_merge_columns_with_the_handler_message(project, parameter):
    engine, config, _ = project
    params = {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": "sales.orders",
        "SELECT_QUERY": "SELECT id, amount FROM staging.orders",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "amount",
    }
    params[parameter] = "id|ID"
    with engine.begin() as conn:
        add_task(conn, add_pipeline(conn, "SALES"), "load", **params)
    report = validate(engine, config)
    matching = [
        finding
        for finding in report.findings
        if finding.where == "SALES.load"
        and finding.status == Status.FAIL
        and parameter in finding.message
    ]
    assert report.failed
    assert len(matching) == 1
    assert "SALES.load" in matching[0].message
    assert "repeats column 'ID'" in matching[0].message
    assert "keep each column once" in matching[0].message


@pytest.mark.parametrize(
    "key",
    [
        "CATCHUP",
        "DEPENDS_ON_PAST",
        "EMAIL_ON_FAILURE",
        "RETRIES",
        "RETRY_DELAY_MINUTES",
        "TYPO",
    ],
)
def test_unknown_pipeline_parameters_fail_with_allowed_keys_and_remedy(project, key):
    engine, config, _ = project
    with engine.begin() as conn:
        pipeline = good_pipeline(conn, "P")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS=:value WHERE PIPELINE_ID=:id"),
            {"value": json.dumps({key: True}), "id": pipeline},
        )
    findings = [finding for finding in validate(engine, config).findings if finding.where == "P"]
    assert any(
        f.status is Status.FAIL
        and key in f.message
        and "TAGS" in f.message
        and "remove" in f.message
        for f in findings
    )


@pytest.mark.parametrize(
    ("sql", "status", "part"),
    [
        (
            "SELECT amount FROM $$rows_in_scope",
            Status.FAIL,
            "expected BUSINESS_RULE_KEY_COLUMN='id'",
        ),
        ("VALUES (1)", Status.FAIL, "read-only SELECT"),
        (
            "SELECT 1 WHERE t.amount < 0",
            Status.FAIL,
            'SELECT t."id" FROM $$rows_in_scope t WHERE EXISTS',
        ),
        ("SELECT id FROM sales.orders", Status.WARN, "has no $$rows_in_scope"),
    ],
)
def test_validate_complete_business_rule_contract(project, sql, status, part):
    engine, config, _ = project
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "BR")
        task = add_task(conn, pipeline, "rules", "BUSINESS_RULES")
        add_rule(conn, pipeline, task, "contract", sql=sql)
    report = validate(engine, config)
    assert any(
        f.where == "BR.rules" and f.status is status and part in f.message for f in report.findings
    )


@pytest.mark.parametrize("sources", ["not json", "{}", "[3]", '["SALES","SALES"]', '["UNKNOWN"]'])
def test_bounded_source_findings_are_shared_by_validate_refresh_and_config_apply(project, sources):
    import csv

    from etl_craft.core.actor import current_actor
    from etl_craft.core.enums import ActionName, ApiRole, RunStatus
    from etl_craft.services.operations import OperationContext
    from fixtures.actions import act, deploy_config

    engine, config, root = project
    from etl_craft.config.object_models import Artifacts

    config = replace(config, artifacts=Artifacts((root / "artifacts").as_uri()))
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "SALES")
        task = add_task(
            conn,
            pipeline,
            "window",
            "SQL",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="mart.events",
            SELECT_QUERY="SELECT changed FROM raw.events WHERE changed >= $$watermark "
            "AND changed < $$watermark_max",
            WATERMARK_COLUMN="changed",
            WATERMARK_TYPE="TIMESTAMP",
            WATERMARK_START="2000-01-01T00:00:00+00:00",
            WATERMARK_SOURCE_PIPELINES=sources,
        )
    report = validate(engine, config)
    assert any(
        f.status == Status.FAIL and "WATERMARK_SOURCE_PIPELINES" in f.message
        for f in report.findings
    )
    ctx = OperationContext(engine, config, current_actor(), role=ApiRole.ADMIN)
    refresh = act(ctx, ActionName.PIPELINE_REFRESH, pipeline_code="SALES").refreshes[0]
    assert refresh.status == RunStatus.FAILED
    assert any(f.failed and "WATERMARK_SOURCE_PIPELINES" in f.message for f in refresh.findings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='[]' "
                "WHERE TASK_ID=:id AND PARAMETER_NAME='WATERMARK_SOURCE_PIPELINES'"
            ),
            {"id": task},
        )
    directory = root / "config"
    directory.mkdir(exist_ok=True)
    with (directory / "task_parameters.csv").open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(
            ["PIPELINE_CODE", "TASK_CODE", "PARAMETER_NAME", "PARAMETER_VALUE", "ACTIVE_FLAG"]
        )
        writer.writerow(["SALES", "window", "WATERMARK_SOURCE_PIPELINES", sources, "Y"])
    applied = deploy_config(ctx, directory).config
    assert not applied.applied
    assert any(
        f.status == Status.FAIL and "WATERMARK_SOURCE_PIPELINES" in f.message
        for f in applied.findings
    )


@pytest.mark.parametrize("cte", [False, True])
@pytest.mark.parametrize("column", ["UPDATE_DATE", "changed"])
def test_known_coarse_timestamp_definitions_are_validation_findings(project, column, cte):
    from fixtures.metadata import add_source_column

    engine, config, _ = project
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "MICROSECONDS")
        target = "mart.events"
        params = {
            "SQL_ACTION": "SCD1_MERGE",
            "TARGET_OBJECT": target,
            "SELECT_QUERY": "SELECT id, changed FROM raw.events WHERE changed >= $$watermark "
            "AND changed < $$watermark_max",
            "MERGE_KEY": "id",
            "MERGE_COMPARE_COLUMNS": "id",
            "WATERMARK_TYPE": "TIMESTAMP",
            "WATERMARK_COLUMN": "changed",
            "WATERMARK_START": "2000-01-01T00:00:00+00:00",
        }
        if cte:
            params["SELECT_QUERY"] = (
                "WITH recent AS (SELECT id, changed FROM raw.events) "
                "SELECT id, changed FROM recent WHERE changed >= $$watermark "
                "AND changed < $$watermark_max"
            )
        add_task(conn, pipeline, "read", "SQL", **params)
        add_source_column(
            conn, target if column == "UPDATE_DATE" else "raw.events", column, "TIMESTAMP(0)", 1
        )
    report = validate(engine, config)
    assert any(
        "precision 0" in f.message and "migration" in f.message and column in f.message
        for f in report.findings
    )
    if column == "changed":
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE CFG_COLUMNS SET DATA_TYPE='TIMESTAMP(6)' WHERE COLUMN_NAME='changed'")
            )
            add_source_column(conn, "raw.other", "changed", "TIMESTAMP(0)", 1)
            conn.execute(
                text(
                    "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE=:query "
                    "WHERE PARAMETER_NAME='SELECT_QUERY'"
                ),
                {
                    "query": "SELECT s.id, s.changed FROM raw.events s "
                    "JOIN raw.other b ON s.id=b.id "
                    "WHERE s.changed >= $$watermark AND s.changed < $$watermark_max"
                },
            )
        assert all("precision 0" not in f.message for f in validate(engine, config).findings)


def _validated_upload_pipeline(conn, root, *, kind="HAS_DATA", validators=1, schedule=None):
    (root / "validation_scripts").mkdir(exist_ok=True)
    (root / "validation_scripts" / "check.py").write_text("def validate(task):\n    return None\n")
    p = add_pipeline(conn, "CORRECTIONS")
    load = add_task(
        conn, p, "land", "PYTHON", SCRIPT_FILE="python_scripts/load.py", SCRIPT_KIND="INGESTION"
    )
    for number in range(validators):
        check = add_task(
            conn,
            p,
            f"check{number}",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
        )
        add_dependency(conn, p, load, check, kind)
    conn.execute(
        text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y', RUN_SCHEDULE=:cron"),
        {"cron": schedule},
    )
    return p


def test_a_scheduled_stewardable_pipeline_with_has_data_after_validation_is_clean(project):
    engine, config, root = project
    with engine.begin() as conn:
        _validated_upload_pipeline(conn, root, schedule="0 6 * * *")
    assert found(validate(engine, config)) == []


def test_a_success_dependency_on_file_validation_is_refused_with_the_remedy(project):
    engine, config, root = project
    with engine.begin() as conn:
        _validated_upload_pipeline(conn, root, kind="SUCCESS")
    messages = [message for _, _, message in found(validate(engine, config))]
    assert any(
        "depends on FILE_VALIDATION task check0 with SUCCESS" in m and "HAS_DATA" in m
        for m in messages
    ), messages


def test_a_pipeline_that_takes_uploads_needs_one_validation_task(project):
    engine, config, root = project
    with engine.begin() as conn:
        _validated_upload_pipeline(conn, root, validators=0)
    messages = [message for _, _, message in found(validate(engine, config))]
    assert any("FILE_VALIDATION tasks=0 on a pipeline that takes uploads" in m for m in messages)


@pytest.mark.parametrize("entrypoint", ["validate", "refresh"])
def test_stewardable_nested_merge_columns_fail_early_in_validate_and_refresh(project, entrypoint):
    from etl_craft.core.actor import SYSTEM_ACTOR
    from etl_craft.core.enums import ActionName, ApiRole, RunStatus
    from etl_craft.services.operations import OperationContext
    from fixtures.actions import act
    from fixtures.metadata import add_source_column

    engine, config, root = project
    raw = yaml.safe_load(config.config_path.read_text())
    raw["Artifacts"] = {"Store": (root / "store").as_uri()}
    config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    config = load_config(config.config_path)
    with engine.begin() as conn:
        pipeline = _validated_upload_pipeline(conn, root)
        add_task(
            conn,
            pipeline,
            "merge",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="main.people",
            SELECT_QUERY="SELECT 1 AS id, 'a' AS name, ARRAY[1,2] AS numbers, 1 AS UPLOAD_ID",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
            MERGE_DEDUPE_ORDER="UPLOAD_ID ASC",
        )
        add_source_column(conn, "main.people", "numbers", "INTEGER[]", 1)
    if entrypoint == "validate":
        report = validate(engine, config)
        assert report.failed
        messages = [finding.message for finding in report.findings]
    else:
        ctx = OperationContext(
            engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN, project="default", project_id=1
        )
        result = act(ctx, ActionName.PIPELINE_REFRESH).refreshes[0]
        assert result.status == RunStatus.FAILED
        messages = [finding.message for finding in result.findings]
    for part in (
        "main.people",
        "numbers",
        "INTEGER[]",
        "canonical scalar hash",
        "cast it to a scalar type in the SELECT",
    ):
        assert any(part in message for message in messages), messages


@pytest.mark.parametrize("entrypoint", ["validate", "refresh"])
@pytest.mark.parametrize("problem", ["target", "stage"])
def test_locked_upload_control_refused_early_by_validate_and_refresh(project, entrypoint, problem):
    from etl_craft.core.actor import SYSTEM_ACTOR
    from etl_craft.core.enums import ActionName, ApiRole, RunStatus
    from etl_craft.services.operations import OperationContext
    from fixtures.actions import act
    from fixtures.metadata import add_source_column

    engine, config, root = project
    raw = yaml.safe_load(config.config_path.read_text())
    raw["Artifacts"] = {"Store": (root / "store").as_uri()}
    config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    config = load_config(config.config_path)
    with engine.begin() as conn:
        pipeline = _validated_upload_pipeline(conn, root)
        add_task(
            conn,
            pipeline,
            "merge",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="main.people",
            SELECT_QUERY=(
                "SELECT 1 AS id,'a' AS name,CAST('true' AS VARCHAR) AS LOCKED,1 AS UPLOAD_ID"
            )
            if problem == "stage"
            else "SELECT 1 AS id,'a' AS name,1 AS UPLOAD_ID",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
            MERGE_DEDUPE_ORDER="UPLOAD_ID ASC",
        )
        if problem == "target":
            add_source_column(conn, "main.people", "LOCKED", "BOOLEAN", 1)
    if entrypoint == "validate":
        result = validate(engine, config)
        assert result.failed
        messages = [finding.message for finding in result.findings]
    else:
        ctx = OperationContext(
            engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN, project="default", project_id=1
        )
        result = act(ctx, ActionName.PIPELINE_REFRESH).refreshes[0]
        assert result.status == RunStatus.FAILED
        messages = [finding.message for finding in result.findings]
    parts = (
        ("main.people", "LOCKED", "rename")
        if problem == "target"
        else ("merge", "LOCKED", "TEXT", "BOOLEAN", "CAST", "landing")
    )
    for part in parts:
        assert any(part in message for message in messages), messages


@pytest.mark.parametrize("kind", [None, "HAS_DATA", "FAILURE", "SUCCESS"])
def test_rule_flag_scope_requires_success_dependency(project, kind):
    engine, config, _ = project
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "FLAGS")
        rules = add_task(conn, pipeline, "rules", "BUSINESS_RULES")
        add_rule(conn, pipeline, rules, "bad")
        consumer = add_task(
            conn,
            pipeline,
            "consume",
            "SQL",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="sales.clean",
            SELECT_QUERY="SELECT id FROM sales.orders WHERE CAST(id AS VARCHAR) "
            "NOT IN ($$rule_flags(rules, REJECT))",
        )
        if kind is not None:
            add_dependency(conn, pipeline, consumer, rules, kind)
    report = validate(engine, config)
    failures = [
        f for f in report.findings if f.where == "FLAGS.consume" and f.status == Status.FAIL
    ]
    if kind == "SUCCESS":
        assert not failures
    else:
        assert any(
            "$$rule_flags(rules, REJECT)" in f.message
            and "SUCCESS" in f.message
            and "remedy" in f.message
            for f in failures
        )


def test_required_uploads_refuses_a_pipeline_that_cannot_receive_files(project):
    engine, config, root = project
    folder = root / "validation_scripts"
    folder.mkdir()
    (folder / "check.py").write_text("def validate(task):\n    return None\n")
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "UPLOAD_REQUIRED")
        add_task(
            conn,
            pipeline,
            "validate_file",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
            REQUIRE_UPLOADS="Y",
        )
    report = validate(engine, config)
    findings = [
        f
        for f in report.findings
        if f.where == "UPLOAD_REQUIRED.validate_file" and f.status == Status.FAIL
    ]
    assert any(
        "REQUIRE_UPLOADS=Y" in f.message
        and "STEWARDABLE_FLAG=N" in f.message
        and "remedy" in f.message
        for f in findings
    )
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y' WHERE PIPELINE_ID=:id"),
            {"id": pipeline},
        )
    report = validate(engine, config)
    assert not [
        f
        for f in report.findings
        if f.where == "UPLOAD_REQUIRED.validate_file" and f.status == Status.FAIL
    ]
