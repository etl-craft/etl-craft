"""``run --pipeline-code``: whole pipelines in waves, init and finalize, gates, SLA and the CLI.

Tasks run in real task processes whose handlers are fakes (``fixtures.task_child``), against a
real Engine DB on both dialects.
"""

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from etl_craft.cli import main as cli_main
from etl_craft.config import (
    ConnectionProfile,
    load_config,
)
from etl_craft.core.actor import current_actor
from etl_craft.core.counts import Counts
from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import (
    ConnectionTestError,
    ExitCode,
    RunStateError,
)
from etl_craft.engine import runlog, transitions
from etl_craft.execution.attempt_types import ChildOptions
from etl_craft.execution.gates import Clock
from etl_craft.execution.pipeline import run_pipeline
from etl_craft.execution.run_types import RunHooks
from fixtures.auth import service_token
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_pipeline_dependency,
    add_task,
    finalize_pipeline,
    finish_run,
    start_run,
    task_run,
    upstream_run,
)

TESTS_DIR = Path(__file__).parents[2]
CHILD = ChildOptions(module="fixtures.task_child", kill_grace_seconds=2)
NO_WAIT = Clock(sleep=lambda seconds: None)


@pytest.fixture(autouse=True)
def child_can_import_fixtures(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(TESTS_DIR))


@pytest.fixture(autouse=True)
def restore_logger():
    logger = logging.getLogger("etl_craft")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


@pytest.fixture
def config(engine_db, tmp_path):
    """A craft-connector.yml naming the test Engine DB, loaded."""
    profile = engine_db.config.engine
    schema = "public" if profile.jdbc_url.startswith("jdbc:postgresql") else "main"
    block = {"Jdbc_url": profile.jdbc_url, "Schema": schema}
    if profile.auth_mode != "NONE":
        block |= {
            "User": profile.user,
            "Auth_mode": profile.auth_mode,
            "Secret": profile.secret_var,
        }
    raw = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {
            "Gate_wait_minutes": 0,
            "Project": "default",
            "Task_timeout_seconds": 60,
            "Local_warehouse_slots": 2,
        },
        "Engine": {"dev": block},
        "Artifacts": {"Store": (tmp_path / "artifacts").as_uri()},
    }
    path = (engine_db.config.config_path or tmp_path / "craft-connector.yml").parent / (
        "craft-connector.yml"
    )
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(path)


@pytest.fixture
def pipeline(engine_db):
    """Pipeline P: extract, then transform; broken fails, and after_broken waits on it;
    alert runs only if extract fails."""
    engine = engine_db.engine
    ids = {}
    with engine.begin() as conn:
        ids["P"] = add_pipeline(conn, "P")
        for code, behaviour in (
            ("extract", "succeed"),
            ("transform", "succeed"),
            ("broken", "fail"),
            ("after_broken", "succeed"),
            ("alert", "succeed"),
        ):
            ids[code] = add_task(conn, ids["P"], code, BEHAVIOUR=behaviour)
        add_dependency(conn, ids["P"], ids["transform"], ids["extract"])
        add_dependency(conn, ids["P"], ids["after_broken"], ids["broken"])
        add_dependency(conn, ids["P"], ids["alert"], ids["extract"], "FAILURE")
    return engine, ids


def statuses(engine, pipeline_run_id):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.TASK_CODE AS code, r.STATUS AS status, r.ATTEMPT_COUNT AS attempts, "
                "r.TARGET_COUNT AS target_count "
                "FROM AUD_TASK_RUN_LOG r JOIN CFG_TASKS t ON t.TASK_ID = r.TASK_ID "
                "WHERE r.PIPELINE_RUN_ID = :id"
            ),
            {"id": pipeline_run_id},
        )
        return {row.code: (row.status, row.attempts, row.target_count) for row in rows}


def run_row(engine, pipeline_run_id):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT STATUS AS status, END_DATE AS end_date, SLA_STATUS AS sla_status "
                "FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID = :id"
            ),
            {"id": pipeline_run_id},
        ).one()


def test_a_pipeline_dispatches_ready_tasks_and_fails_when_a_task_fails(config, pipeline, caplog):
    engine, _ = pipeline
    caplog.set_level(logging.INFO, "etl_craft.execution")
    outcome = run_pipeline(engine, config, "P", child=CHILD, clock=NO_WAIT)
    run_id = outcome.pipeline_run_id
    assert outcome.status == RunStatus.FAILED
    assert outcome.message == (
        f"P: pipeline_run_id={run_id} FAILED — 1 task(s) did not succeed: broken (FAILED) "
        "[FAIL_PIPELINE_IF_FAILED=Y]; "
        "skipped because of the failure: after_broken"
    )
    assert statuses(engine, run_id) == {
        "extract": ("SUCCESS", 1, 9),
        "transform": ("SUCCESS", 1, 9),
        "broken": ("FAILED", 1, None),
        # No retry comes for broken in this run, so what waits on it is skipped, not left.
        "after_broken": ("SKIPPED", 1, None),
        "alert": ("SKIPPED", 1, None),
    }
    assert run_row(engine, run_id).status == "FAILED"
    dispatches = [r.getMessage() for r in caplog.records if ": dispatch " in r.getMessage()]
    assert dispatches == ["P: dispatch extract", "P: dispatch broken", "P: dispatch transform"]


def test_an_interrupted_run_is_resumed_without_repeating_finished_tasks(config, pipeline):
    engine, ids = pipeline
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID IN (:b, :a)"),
            {"b": ids["broken"], "a": ids["after_broken"]},
        )
        run_id = start_run(conn, ids["P"])
        task_run(conn, ids["extract"], run_id, "SUCCESS", 42)
    finished = []
    outcome = run_pipeline(
        engine, config, "P", child=CHILD, hooks=RunHooks(on_finalized=finished.append)
    )
    assert (outcome.status, outcome.pipeline_run_id) == (RunStatus.SUCCESS, run_id)
    # extract kept its row from before; the rest ran.
    assert statuses(engine, run_id) == {
        "extract": ("SUCCESS", 1, 42),
        "transform": ("SUCCESS", 1, 9),
        "alert": ("SKIPPED", 1, None),
    }
    assert run_row(engine, run_id).end_date is not None
    assert finished == [outcome]


def test_force_runs_every_task_again(config, pipeline):
    engine, ids = pipeline
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID <> :e"),
            {"e": ids["extract"]},
        )
        run_id = start_run(conn, ids["P"])
        task_run(conn, ids["extract"], run_id, "SUCCESS", 42)
    outcome = run_pipeline(engine, config, "P", child=CHILD, force=True)
    assert outcome.status == RunStatus.SUCCESS
    assert statuses(engine, run_id) == {"extract": ("SUCCESS", 2, 9)}


def test_an_unsatisfied_pipeline_dependency_skips_the_run(config, pipeline):
    engine, ids = pipeline
    with engine.begin() as conn:
        upstream = add_pipeline(conn, "UP")
        edge = add_pipeline_dependency(conn, ids["P"], upstream)
    finished = []
    outcome = run_pipeline(
        engine,
        config,
        "P",
        child=CHILD,
        clock=NO_WAIT,
        hooks=RunHooks(on_finalized=finished.append),
    )
    assert outcome.status == RunStatus.SKIPPED
    assert outcome.message.endswith(
        "SKIPPED — start condition [UP.SUCCESS]: UP.SUCCESS=unknown; UP has no finished run"
    )
    assert run_row(engine, outcome.pipeline_run_id).status == "SKIPPED"
    assert statuses(engine, outcome.pipeline_run_id) == {}
    assert finished == [outcome]

    # Once UP has succeeded, the next run starts, and on success consumes UP's run.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID = :b"), {"b": ids["broken"]}
        )
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID = :a"),
            {"a": ids["after_broken"]},
        )
        up_run, _ = upstream_run(conn, upstream, {})
    assert run_pipeline(engine, config, "P", child=CHILD, clock=NO_WAIT).status == "SUCCESS"
    with engine.connect() as conn:
        consumed = conn.execute(
            text(
                "SELECT CONSUMED_PIPELINE_RUN_ID FROM AUD_DEPENDENCY_CONSUMPTION "
                "WHERE PIPELINE_DEPENDENCY_ID = :id"
            ),
            {"id": edge},
        ).scalar_one()
    assert consumed == up_run


def test_a_refused_gate_leaves_a_run_another_process_started_alone(config, pipeline):
    # While this run waits for a running upstream, another process starts a run of P, and the
    # upstream then fails. The gate refuses, and the other process's run must stay as it is.
    engine, ids = pipeline
    with engine.begin() as conn:
        upstream = add_pipeline(conn, "UP")
        add_pipeline_dependency(conn, ids["P"], upstream)
        up_run = start_run(conn, upstream)
    started_elsewhere = []

    def another_process_meanwhile(seconds):
        if started_elsewhere:
            return
        with engine.begin() as conn:
            started_elsewhere.append(start_run(conn, ids["P"]))
            finish_run(conn, up_run, "FAILED")

    config = replace(config, limits=replace(config.limits, gate_wait_minutes=60))
    with pytest.raises(RunStateError, match="another process started pipeline_run_id="):
        run_pipeline(engine, config, "P", child=CHILD, clock=Clock(sleep=another_process_meanwhile))
    assert run_row(engine, started_elsewhere[0]).status == "IN-PROGRESS"


def test_a_run_is_not_ended_while_another_process_runs_one_of_its_tasks(config, pipeline):
    engine, ids = pipeline
    with engine.begin() as conn:
        run = start_run(conn, ids["P"])
        elsewhere = task_run(conn, ids["extract"], run, status="IN-PROGRESS")

    held = run_pipeline(engine, config, "P", child=CHILD, clock=NO_WAIT)
    assert (held.status, held.pipeline_run_id) == (RunStatus.IN_PROGRESS, run)
    assert f"extract (task_run_id={elsewhere}) is still IN-PROGRESS in another process" in (
        held.message
    )
    assert run_row(engine, run).status == "IN-PROGRESS"
    assert "transform" not in statuses(engine, run)

    # The other process finishes extract; the next run goes on and ends the run.
    with engine.begin() as conn:
        transitions.finish_task_run(
            conn, elsewhere, status=RunStatus.SUCCESS, counts=Counts(target_count=1)
        )
    done = run_pipeline(engine, config, "P", child=CHILD, clock=NO_WAIT)
    assert done.pipeline_run_id == run
    assert done.status == RunStatus.FAILED  # broken fails, as in every run of P
    assert statuses(engine, run)["transform"][0] == "SUCCESS"


def test_the_sla_is_marked_breached_while_the_run_is_still_going(config, engine_db):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "LATE", sla_in_hours=0.0001)
        add_task(conn, pipeline_id, "slow", BEHAVIOUR="sleep", TASK_TIMEOUT_SECONDS=2)
    lapses = []
    outcome = run_pipeline(engine, config, "LATE", child=CHILD, hooks=RunHooks(lapses.append))
    assert outcome.status == RunStatus.FAILED
    assert run_row(engine, outcome.pipeline_run_id).sla_status == "BREACHED"
    assert "SLA of 0.0001 h BREACHED" in outcome.message
    # Once per run: the watcher saw it first, so finalize does not report it again.
    assert [lapse.pipeline_code for lapse in lapses] == ["LATE"]


def test_finalize_reports_a_lapse_nobody_saw_while_running(config, engine_db):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "LATE", sla_in_hours=0.0001)
        add_task(conn, pipeline_id, "quick")
        run_id = start_run(conn, pipeline_id)
        conn.execute(
            text(
                "UPDATE AUD_PIPELINES_RUN_LOG SET START_DATE = START_DATE - INTERVAL '1' HOUR "
                "WHERE PIPELINE_RUN_ID = :id"
            )
            if engine.dialect.name == "postgresql"
            else text(
                "UPDATE AUD_PIPELINES_RUN_LOG SET START_DATE = '2000-01-01 00:00:00.000000+00:00' "
                "WHERE PIPELINE_RUN_ID = :id"
            ),
            {"id": run_id},
        )
        task_run(
            conn,
            conn.execute(
                text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE = 'quick'")
            ).scalar_one(),
            run_id,
        )
    lapses = []

    def broken_hook(outcome):
        raise RuntimeError("cloning is down")

    outcome = finalize_pipeline(engine, config, "LATE", hooks=RunHooks(lapses.append, broken_hook))
    assert outcome.status == RunStatus.SUCCESS
    assert [lapse.pipeline_run_id for lapse in lapses] == [run_id]


def test_a_failed_warehouse_connection_test_starts_no_run(config, pipeline, monkeypatch):
    engine, _ = pipeline
    monkeypatch.setenv("ETL_CRAFT_TEST_CONNECTION_PASSWORD", "unused")
    profile = ConnectionProfile(
        section="WAREHOUSE",
        name="down",
        jdbc_url="jdbc:postgresql://127.0.0.1:1/test",
        user="etl",
        auth_mode="PASSWORD",
        schema="public",
        extra={"secret_var": "ETL_CRAFT_TEST_CONNECTION_PASSWORD"},
    )
    config = replace(config, warehouse=profile)
    with pytest.raises(ConnectionTestError, match="warehouse:"):
        run_pipeline(engine, config, "P", child=CHILD)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED", "SKIPPED"])
def test_an_alert_only_pipeline_keeps_its_alert_outcome(config, engine_db, status):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "ONLY_MAIL")
        alert_id = add_task(conn, pipeline_id, "notify", "ALERT")
        run_id = start_run(conn, pipeline_id)
        task_run(conn, alert_id, run_id, status)
    assert finalize_pipeline(engine, config, "ONLY_MAIL").status == status


@pytest.mark.parametrize("data_status", ["SUCCESS", "FAILED", "SKIPPED"])
def test_alert_failures_do_not_change_the_data_outcome(config, engine_db, data_status):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "MAIL")
        data = add_task(conn, pipeline_id, "data")
        notify = add_task(conn, pipeline_id, "notify", "ALERT", FAIL_PIPELINE_IF_FAILED="N")
        run_id = start_run(conn, pipeline_id)
        task_run(conn, data, run_id, data_status)
        notify_run = task_run(conn, notify, run_id, "IN-PROGRESS")
        transitions.finish_task_run(
            conn, notify_run, status="FAILED", error_message="relay is down"
        )
    outcome = finalize_pipeline(engine, config, "MAIL")
    assert outcome.status == data_status
    with engine.connect() as conn:
        assert runlog.fetch_task_run_status(conn, notify, run_id) == "FAILED"


@pytest.mark.parametrize("handler", ["ALERT", "SQL"])
@pytest.mark.parametrize("flag", [None, "N"])
def test_failed_task_uses_pipeline_fail_option(config, engine_db, handler, flag):
    engine = engine_db.engine
    params = {} if flag is None else {"FAIL_PIPELINE_IF_FAILED": flag}
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "OPTIONS")
        required = add_task(conn, pipeline_id, "required")
        maybe = add_task(conn, pipeline_id, "maybe", handler, **params)
        run_id = start_run(conn, pipeline_id)
        task_run(conn, required, run_id, "SUCCESS")
        task_run(conn, maybe, run_id, "FAILED")

    outcome = finalize_pipeline(engine, config, "OPTIONS")
    assert outcome.status == (RunStatus.SUCCESS if flag else RunStatus.FAILED)
    if flag is None:
        assert "maybe (FAILED) [FAIL_PIPELINE_IF_FAILED=Y]" in outcome.message
    else:
        assert "tolerated failure: maybe (FAIL_PIPELINE_IF_FAILED=N)" in outcome.message
    assert run_row(engine, run_id).status == outcome.status


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("operator_skip", [False, True])
def test_condition_skip_uses_pipeline_fail_option(config, engine_db, required, operator_skip):
    engine = engine_db.engine
    params = {"FAIL_PIPELINE_IF_NOT_RUN": "Y"} if required else {}
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "OPTIONS")
        upstream = add_task(conn, pipeline_id, "upstream")
        watched = add_task(conn, pipeline_id, "watched", **params)
        add_dependency(conn, pipeline_id, watched, upstream, "FAILURE")
        run_id = start_run(conn, pipeline_id)
        task_run(conn, upstream, run_id, "SUCCESS")
        if operator_skip:
            task_run(conn, watched, run_id, "SKIPPED")

    outcome = finalize_pipeline(engine, config, "OPTIONS")
    fail = required and not operator_skip
    assert outcome.status == (RunStatus.FAILED if fail else RunStatus.SUCCESS)
    assert ("watched (FAIL_PIPELINE_IF_NOT_RUN=Y)" in outcome.message) == fail
    with engine.connect() as conn:
        assert runlog.fetch_task_run_status(conn, watched, run_id) == "SKIPPED"
        decisions = conn.execute(
            text(
                "SELECT CONDITION_TEXT AS condition_text, CONDITION_VALUES AS condition_values "
                "FROM AUD_GATE_DECISIONS WHERE PIPELINE_RUN_ID=:run AND TASK_ID=:task"
            ),
            {"run": run_id, "task": watched},
        ).all()
    if operator_skip:
        assert decisions == []
    else:
        assert len(decisions) == 1
        assert decisions[0].condition_text == "upstream.FAILED"
        assert json.loads(decisions[0].condition_values) == {"upstream.FAILED": False}


def test_resume_preserves_an_optional_failure_without_an_attempt(config, engine_db):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "OPTIONAL")
        optional = add_task(
            conn, pipeline, "optional", BEHAVIOUR="succeed", FAIL_PIPELINE_IF_FAILED="N"
        )
        fallback = add_task(conn, pipeline, "fallback", BEHAVIOUR="succeed")
        add_dependency(conn, pipeline, fallback, optional, "FAILURE")
        run_id = start_run(conn, pipeline)
        task_run(conn, optional, run_id, "FAILED")

    outcome = run_pipeline(engine, config, "OPTIONAL", child=CHILD, clock=NO_WAIT)
    assert (outcome.pipeline_run_id, outcome.status) == (run_id, RunStatus.SUCCESS)
    assert "tolerated failure: optional (FAIL_PIPELINE_IF_FAILED=N)" in outcome.message
    assert statuses(engine, run_id)["fallback"][0] == RunStatus.SUCCESS


def test_optional_failure_still_dispatches_its_failure_branch(config, engine_db):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline_id = add_pipeline(conn, "OPTIONAL")
        optional = add_task(
            conn, pipeline_id, "optional", BEHAVIOUR="fail", FAIL_PIPELINE_IF_FAILED="N"
        )
        fallback = add_task(conn, pipeline_id, "fallback", BEHAVIOUR="succeed")
        required = add_task(conn, pipeline_id, "required", BEHAVIOUR="succeed")
        downstream = add_pipeline(conn, "DOWNSTREAM")
        add_pipeline_dependency(conn, downstream, pipeline_id)
        add_dependency(conn, pipeline_id, fallback, optional, "FAILURE")
        add_task(conn, downstream, "consume", BEHAVIOUR="succeed")
    outcome = run_pipeline(engine, config, "OPTIONAL", child=CHILD, clock=NO_WAIT)
    assert outcome.status == RunStatus.SUCCESS
    assert "tolerated failure: optional (FAIL_PIPELINE_IF_FAILED=N)" in outcome.message
    with engine.connect() as conn:
        for task, status in (
            (optional, RunStatus.FAILED),
            (fallback, RunStatus.SUCCESS),
            (required, RunStatus.SUCCESS),
        ):
            assert runlog.fetch_task_run_status(conn, task, outcome.pipeline_run_id) == status
    consumed = run_pipeline(engine, config, "DOWNSTREAM", child=CHILD, clock=NO_WAIT)
    assert consumed.status == RunStatus.SUCCESS
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT CONSUMED_PIPELINE_RUN_ID AS output FROM AUD_DEPENDENCY_CONSUMPTION "
                    "WHERE PIPELINE_RUN_ID=:run"
                ),
                {"run": consumed.pipeline_run_id},
            ).scalar_one()
            == outcome.pipeline_run_id
        )


@pytest.mark.parametrize("lost", [False, True])
def test_incomplete_optional_task_still_fails_its_run(config, engine_db, lost):
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "INCOMPLETE")
        task = add_task(conn, pipeline, "optional", FAIL_PIPELINE_IF_FAILED="N")
        run = start_run(conn, pipeline)
        if lost:
            actor = current_actor()
            summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
            attempt = transitions.queue_attempt(conn, summary, actor)
            transitions.claim_attempt(
                conn,
                attempt,
                actor,
                owner="expired",
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            transitions.lose_attempt(conn, attempt, actor, owner="expired")
    outcome = finalize_pipeline(engine, config, "INCOMPLETE")
    assert outcome.status == RunStatus.FAILED
    assert ("optional (LOST)" if lost else "optional (never started)") in outcome.message
    assert "tolerated failure" not in outcome.message


def test_cancelled_run_does_not_evaluate_a_remaining_condition(config, engine_db):
    from etl_craft.execution.run_finish import finalize
    from etl_craft.execution.run_start import load_pipeline
    from etl_craft.execution.run_types import PipelineRun, default_hooks

    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "CANCEL_TEST")
        upstream = add_task(conn, pipeline, "upstream")
        watched = add_task(conn, pipeline, "watched", FAIL_PIPELINE_IF_NOT_RUN="Y")
        add_dependency(conn, pipeline, watched, upstream, "FAILURE")
        run_id = start_run(conn, pipeline)
        task_run(conn, upstream, run_id, "SUCCESS")
        detail, graph, codes = load_pipeline(conn, pipeline, run_id=run_id)
        transitions.cancel_pipeline_run(conn, run_id)
    run = PipelineRun("CANCEL_TEST", pipeline, run_id, graph, codes, detail.sla_in_hours)
    assert finalize(engine, run, default_hooks(config, engine)).status == RunStatus.CANCELLED
    with engine.connect() as conn:
        assert runlog.fetch_task_run_status(conn, watched, run_id) is None


def test_recorded_conditions_cover_task_facts_and_operators(config, engine_db):
    from etl_craft.engine.condition_edges import derive_edges

    engine = engine_db.engine
    facts = {
        "SUCCESS": True,
        "FAILED": False,
        "SKIPPED": False,
        "FINISHED": True,
        "HAS_DATA": True,
        "STATUS": "SUCCESS",
        "ERROR_CLASS": "NONE",
        "ATTEMPTS": 1,
        "DURATION_SECONDS": 0,
        "SOURCE_ROWS": 3,
        "TARGET_ROWS": 3,
        "ROWS_WRITTEN": 3,
        "INSERTED": 3,
        "UPDATED": 0,
        "DELETED": 0,
        "REJECTED": 0,
        "DUPLICATES": 0,
    }
    yes = (
        "source.SUCCESS",
        "NOT source.FAILED",
        "NOT source.SKIPPED",
        "source.FINISHED",
        "source.HAS_DATA",
        "source.STATUS = SUCCESS",
        "source.ERROR_CLASS = NONE",
        "source.ATTEMPTS = 1",
        "source.DURATION_SECONDS = 0",
        "source.SOURCE_ROWS > 2",
        "source.TARGET_ROWS >= 3",
        "source.ROWS_WRITTEN < 4",
        "source.INSERTED <= 3",
        "source.UPDATED <> 1",
        "source.DELETED = 0",
        "source.REJECTED = 0",
        "source.DUPLICATES = 0",
    )
    no = (
        "NOT source.SUCCESS",
        "source.FAILED",
        "source.SKIPPED",
        "NOT source.FINISHED",
        "NOT source.HAS_DATA",
        "source.STATUS <> SUCCESS",
        "source.ERROR_CLASS <> NONE",
        "source.ATTEMPTS = 2",
        "source.DURATION_SECONDS = 1",
        "source.SOURCE_ROWS > 3",
        "source.TARGET_ROWS >= 4",
        "source.ROWS_WRITTEN < 3",
        "source.INSERTED <= 2",
        "source.UPDATED <> 0",
        "source.DELETED = 1",
        "source.REJECTED = 1",
        "source.DUPLICATES = 1",
    )
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "FACTS")
        source = add_task(conn, pipeline, "source")
        true_task = add_task(conn, pipeline, "true_task", BEHAVIOUR="succeed")
        false_task = add_task(conn, pipeline, "false_task")
        for task_id, rule in ((true_task, " AND ".join(yes)), (false_task, " OR ".join(no))):
            conn.execute(
                text("UPDATE CFG_TASKS SET RUN_CONDITION=:rule WHERE TASK_ID=:task"),
                {"rule": rule, "task": task_id},
            )
        derive_edges(conn, 1)
        run_id = start_run(conn, pipeline)
        source_run = transitions.find_or_create_task_run(conn, source, run_id).task_run_id
        transitions.finish_task_run(
            conn,
            source_run,
            status=RunStatus.SUCCESS,
            counts=Counts(
                source_count=3,
                target_count=3,
                insert_count=3,
                update_count=0,
                delete_count=0,
                reject_count=0,
                duplicate_count=0,
            ),
        )
        conn.execute(
            text("UPDATE AUD_TASK_RUN_LOG SET END_DATE=START_DATE WHERE TASK_RUN_ID=:id"),
            {"id": source_run},
        )

    outcome = run_pipeline(engine, config, "FACTS", child=CHILD, clock=NO_WAIT)
    assert (outcome.pipeline_run_id, outcome.status) == (run_id, RunStatus.SUCCESS)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT TASK_ID AS task_id, RESULT AS result, CONDITION_VALUES AS condition_values "
                "FROM AUD_GATE_DECISIONS WHERE PIPELINE_RUN_ID=:run AND CONDITION_TEXT IS NOT NULL"
            ),
            {"run": run_id},
        )
        rows = rows.all()
        assert {row.task_id: row.result for row in rows} == {
            true_task: "SATISFIED",
            false_task: "UNSATISFIED",
        }
        for row in rows:
            assert json.loads(row.condition_values) == {
                f"source.{fact}": value for fact, value in facts.items()
            }


def test_the_command_line(config, pipeline, capsys, monkeypatch, engine_db):
    monkeypatch.setenv("ETL_CRAFT_TOKEN", service_token(engine_db.engine))
    monkeypatch.chdir(config.config_path.parent)
    scripts = config.project_dir / "python_scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "fail.py").write_text(
        "def run(task):\n    raise RuntimeError('expected task failure')\n"
    )
    with engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_TASKS SET HANDLER='PYTHON'"))
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "SELECT TASK_ID,'SCRIPT_KIND','INGESTION' FROM CFG_TASKS"
            )
        )
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "SELECT TASK_ID,'SCRIPT_FILE','python_scripts/fail.py' FROM CFG_TASKS"
            )
        )
    assert cli_main(["deploy"]) == ExitCode.SUCCESS
    capsys.readouterr()
    assert (
        cli_main(["run", "--pipeline-code", "P", "--init-only", "--reason", "test requested run"])
        == ExitCode.SUCCESS
    )
    assert capsys.readouterr().out.endswith("IN-PROGRESS\n")
    # Real task processes execute the checked script, so every runnable task fails.
    assert (
        cli_main(["run", "--pipeline-code", "P", "--reason", "test requested run"])
        == ExitCode.FAILURE
    )
    # alert runs because extract failed; transform and after_broken never can.
    out = capsys.readouterr().out
    assert "FAILED — 3 task(s) did not succeed" in out
    assert "skipped because of the failure: transform, after_broken" in out
    assert (
        cli_main(
            [
                "run",
                "--pipeline-code",
                "P",
                "--init-only",
                "--force",
                "--reason",
                "test requested run",
            ]
        )
        == ExitCode.USAGE
    )
    with pytest.raises(SystemExit) as usage:
        cli_main(
            [
                "run",
                "--pipeline-code",
                "P",
                "--init-only",
                "--task-code",
                "extract",
                "--reason",
                "test requested run",
            ]
        )
    assert usage.value.code == ExitCode.USAGE
