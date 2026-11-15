"""A schedule-free watcher chain, real operator recovery and competing controllers."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from sqlalchemy import text

from etl_craft.controller.restarts import COOLDOWN, Restarts
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import (
    ActionName,
    ApiRole,
    ControlAction,
    ControlStatus,
    RunStatus,
    TriggerKind,
)
from etl_craft.core.time import as_utc
from etl_craft.engine.runlog import RunSelector
from etl_craft.execution.gates import Clock
from etl_craft.execution.pipeline import run_pipeline
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.controls import ControlRequest
from fixtures.metadata import add_dependency, add_pipeline, add_task
from fixtures.races import two_at_once
from fixtures.scoped_controls import ctx as ctx


def controller(ctx):
    return replace(ctx, actor=Actor("controller", ActorKind.SERVICE), role=ApiRole.ADMIN)


def ended_at(ctx, run_id):
    with ctx.engine.connect() as conn:
        value = conn.execute(
            text("SELECT END_DATE AS ended FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:id"),
            {"id": run_id},
        ).scalar_one()
    return as_utc(value)


def next_run(ctx, previous):
    with ctx.engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS id, STATUS AS status, TRIGGER_KIND AS kind "
                "FROM AUD_PIPELINES_RUN_LOG WHERE RUN_KEY=:key"
            ),
            {"key": f"restart:{previous}"},
        ).one()


def test_schedule_free_event_watcher_continues_after_success_and_skip(ctx):
    folder = ctx.config.project_dir / "python_scripts"
    folder.mkdir()
    (folder / "consume.py").write_text(
        "from pathlib import Path\n"
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    with (task.config.project_dir / 'received').open('a') as output:\n"
        "        for name in task.event_files:\n"
        "            output.write(Path(name).read_text() + '\\n')\n"
        "    return ScriptResult(row_count=1)\n"
    )
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "WATCH")
        conn.execute(
            text(
                "UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='SUCCESS|SKIPPED' "
                "WHERE PIPELINE_ID=:id"
            ),
            {"id": pipeline},
        )
        wait = add_task(
            conn,
            pipeline,
            "wait",
            "EVENT_WAIT",
            EVENT_FILE="*.csv",
            EVENT_SETTLE_SECONDS="0",
            EVENT_POLL_SECONDS="1",
            EVENT_TIMEOUT_MINUTES="0.05",
            EVENT_ON_TIMEOUT="SKIP",
        )
        consume = add_task(
            conn, pipeline, "consume", "PYTHON", SCRIPT_FILE="python_scripts/consume.py"
        )
        add_dependency(conn, pipeline, consume, wait)
        assert (
            conn.execute(
                text("SELECT RUN_SCHEDULE AS schedule FROM CFG_PIPELINES WHERE PIPELINE_ID=:id"),
                {"id": pipeline},
            ).scalar_one()
            is None
        )
    now = datetime.now(UTC)

    def current_time():
        return now

    selector = RunSelector()
    expected = (RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.SUCCESS)
    for index, status in enumerate(expected):
        checks = 0
        deadline = monotonic() + 30
        arrived = False

        def advance(seconds, status=status, index=index, deadline=deadline):
            nonlocal now, checks, arrived
            checks += 1
            assert monotonic() < deadline, "watcher did not reach its bounded outcome"
            if status == RunStatus.SKIPPED:
                now += timedelta(seconds=max(seconds, 1))
            elif not arrived:
                with ctx.engine.connect() as conn:
                    waiting = conn.execute(
                        text("SELECT COUNT(*) AS count FROM AUD_GATE_WAITS WHERE TASK_ID=:id"),
                        {"id": wait},
                    ).scalar_one()
                if waiting:
                    (ctx.config.project_dir / f"batch-{index}.csv").write_text(f"batch-{index}")
                    now += timedelta(seconds=1)
                    arrived = True

        outcome = run_pipeline(
            ctx.engine,
            ctx.config,
            "WATCH",
            selector=selector,
            clock=Clock(now=current_time, sleep=advance),
        )
        assert outcome.status == status
        assert checks > 0
        now = ended_at(ctx, outcome.pipeline_run_id) + COOLDOWN
        Restarts().refresh(controller(ctx), now)
        following = next_run(ctx, outcome.pipeline_run_id)
        assert following.status == RunStatus.QUEUED
        assert following.kind == TriggerKind.RESTART
        selector = RunSelector(run_id=following.id)
    assert (ctx.config.project_dir / "received").read_text().splitlines() == ["batch-0", "batch-2"]


def test_recovering_the_failed_run_resumes_its_automatic_restart_chain(ctx):
    folder = ctx.config.project_dir / "python_scripts"
    folder.mkdir()
    (folder / "load.py").write_text(
        "from etl_craft.core.errors import HandlerError\n"
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    source = task.config.project_dir / 'source.csv'\n"
        "    if not source.exists():\n"
        "        raise HandlerError('RECOVER.load: source.csv absent; expected file; restore it')\n"
        "    return ScriptResult(row_count=1)\n"
    )
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "RECOVER")
        add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        conn.execute(
            text(
                "UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='SUCCESS|SKIPPED' "
                "WHERE PIPELINE_ID=:id"
            ),
            {"id": pipeline},
        )
    failed = run_pipeline(ctx.engine, ctx.config, "RECOVER")
    assert failed.status == RunStatus.FAILED
    Restarts().refresh(controller(ctx), ended_at(ctx, failed.pipeline_run_id) + COOLDOWN)
    with ctx.engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) AS count FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:id"),
                {"id": pipeline},
            ).scalar_one()
            == 1
        )
    (ctx.config.project_dir / "source.csv").write_text("repaired")
    recovered = invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="RECOVER",
            run_id=failed.pipeline_run_id,
            action=ControlAction.RECOVER,
            reason="source repaired",
            request_key="repair-source",
        ),
    )
    assert recovered.status == ControlStatus.COMPLETED
    assert recovered.execution_run_id == failed.pipeline_run_id
    outcome = run_pipeline(
        ctx.engine,
        ctx.config,
        "RECOVER",
        selector=RunSelector(run_id=failed.pipeline_run_id),
    )
    assert outcome.status == RunStatus.SUCCESS
    Restarts().refresh(controller(ctx), ended_at(ctx, outcome.pipeline_run_id) + COOLDOWN)
    assert next_run(ctx, outcome.pipeline_run_id).status == RunStatus.QUEUED


def test_two_controllers_race_to_one_restart_key_and_one_audit_record(ctx):
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "RACE")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='SUCCESS' WHERE PIPELINE_ID=:id"),
            {"id": pipeline},
        )
        add_task(conn, pipeline, "load", "PYTHON", BEHAVIOUR="succeed")
    done = run_pipeline(ctx.engine, ctx.config, "RACE", child=ctx.child)
    assert done.status == RunStatus.SUCCESS
    now = ended_at(ctx, done.pipeline_run_id) + COOLDOWN
    two_at_once(
        lambda: Restarts().refresh(controller(ctx), now),
        lambda: Restarts().refresh(controller(ctx), now),
        at="etl_craft.controller.restarts._restart",
    )
    following = next_run(ctx, done.pipeline_run_id)
    assert following.status == RunStatus.QUEUED
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) AS count FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:id"),
                {"id": pipeline},
            ).scalar_one()
            == 2
        )
        audit = conn.execute(
            text("SELECT REASON AS reason FROM AUD_RUN_INTERVENTIONS WHERE PIPELINE_RUN_ID=:id"),
            {"id": following.id},
        ).all()
        assert [row.reason for row in audit] == [
            f"restart after run {done.pipeline_run_id} ended SUCCESS"
        ]


@pytest.mark.parametrize("column", ["AUTO_RESTART_CONDITION", "ALLOWED_AUTO_RESTARTS"])
def test_invalid_restart_metadata_names_object_value_expectation_and_remedy(ctx, caplog, column):
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "BAD_RESTART")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='SUCCESS' WHERE PIPELINE_ID=:id"),
            {"id": pipeline},
        )
        add_task(conn, pipeline, "load", "PYTHON", BEHAVIOUR="succeed")
    done = run_pipeline(ctx.engine, ctx.config, "BAD_RESTART", child=ctx.child)
    assert done.status == RunStatus.SUCCESS
    with ctx.engine.begin() as conn:
        if column == "AUTO_RESTART_CONDITION":
            conn.execute(
                text("UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='FOO' WHERE PIPELINE_ID=:id"),
                {"id": pipeline},
            )
        else:
            conn.execute(text("UPDATE CFG_PROJECTS SET ALLOWED_AUTO_RESTARTS='FOO'"))
    Restarts().refresh(controller(ctx), ended_at(ctx, done.pipeline_run_id) + COOLDOWN)
    assert "pipeline BAD_RESTART" in caplog.text
    assert "'FOO'" in caplog.text
    assert "not one of NONE, SCHEDULE, SUCCESS, SKIPPED, FAILURE" in caplog.text
    assert "write NONE, or values joined with |" in caplog.text
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) AS count FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:id"),
                {"id": pipeline},
            ).scalar_one()
            == 1
        )
