"""Pipeline pause modes share the admission fence with dispatch and resume."""

import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from test_scoped_controls import wait_for

from etl_craft.core.actor import current_actor
from etl_craft.core.enums import (
    ActionName,
    AttemptStatus,
    ControlAction,
    RunStatus,
)
from etl_craft.core.errors import RunRefusedError, RunStateError, UsageError
from etl_craft.engine import runlog, standing_pauses, transitions
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.engine.runlog import RunSelector
from etl_craft.execution.pipeline import run_pipeline
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.requests import ControlRequest
from fixtures.metadata import add_dependency, add_pipeline, add_task, start_run
from fixtures.races import two_at_once
from fixtures.scoped_controls import ctx as ctx


def pause(ctx, *, mode="DRAIN", replace=False):
    return invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            action=ControlAction.PAUSE,
            reason="maintenance",
            **({"active_runs": mode} if mode == "FINISH" else {}),
            replace=replace,
        ),
    )


def resume(ctx):
    return invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            action=ControlAction.RESUME,
            reason="maintenance complete",
        ),
    )


def seed(ctx):
    with ctx.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        a = add_task(conn, p, "a", "PYTHON", BEHAVIOUR="succeed")
        b = add_task(conn, p, "b", "PYTHON", BEHAVIOUR="succeed")
        add_dependency(conn, p, b, a)
    return p, a, b


def queue(ctx, task, run):
    with ctx.engine.begin() as conn:
        summary = transitions.find_or_create_task_run(conn, task, run)
        return transitions.queue_attempt(conn, summary.task_run_id, current_actor())


@pytest.mark.chaos
@pytest.mark.parametrize("replace_pause", [False, True])
def test_drain_finishes_running_attempt_then_waits_until_resume_without_repair(
    ctx, tmp_path, replace_pause
):
    p, a, b = seed(ctx)
    ready, release = tmp_path / "ready", tmp_path / "release"
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='barrier' WHERE "
                "TASK_ID=:task AND PARAMETER_NAME='BEHAVIOUR'"
            ),
            {"task": a},
        )
        for name, path in [("READY_FILE", ready), ("RELEASE_FILE", release)]:
            conn.execute(
                text(
                    "INSERT INTO CFG_TASK_PARAMETERS "
                    "(TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) VALUES (:task,:name,:value)"
                ),
                {"task": a, "name": name, "value": str(path)},
            )
        run = start_run(conn, p)

    if replace_pause:
        pause(ctx, mode="FINISH")

    def first_finished():
        with ctx.engine.connect() as conn:
            return runlog.fetch_task_run_status(conn, a, run) == RunStatus.SUCCESS

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            contextvars.copy_context().run,
            run_pipeline,
            ctx.engine,
            ctx.config,
            "P",
            child=ctx.child,
            selector=RunSelector(run_id=run),
        )
        try:
            wait_for(ready.exists)
            pause(ctx, replace=replace_pause)
            release.touch()
            wait_for(first_finished)
            with ctx.engine.connect() as conn:
                assert runlog.fetch_pipeline_run_status(conn, run) == RunStatus.IN_PROGRESS
                assert runlog.fetch_task_run_status(conn, b, run) is None
                assert standing_pauses.drains(conn, p, run)
            assert not future.done()
        finally:
            release.touch()
            resume(ctx)
        assert future.result(timeout=30).status == RunStatus.SUCCESS
    with ctx.engine.connect() as conn:
        assert runlog.fetch_pipeline_run_status(conn, run) == RunStatus.SUCCESS
        attempts = conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_TASK_ATTEMPTS")
        ).scalar_one()
        assert attempts == 2
        assert (
            conn.execute(
                text("SELECT COUNT(*) AS count FROM AUD_RUN_INTERVENTIONS WHERE ACTION='REOPEN'")
            ).scalar_one()
            == 0
        )


def test_finish_allows_admitted_run_to_complete_and_blocks_new_runs(ctx):
    p, _, _ = seed(ctx)
    with ctx.engine.begin() as conn:
        run = start_run(conn, p)
    pause(ctx, mode="FINISH")
    assert (
        run_pipeline(
            ctx.engine, ctx.config, "P", selector=RunSelector(run_id=run), child=ctx.child
        ).status
        == RunStatus.SUCCESS
    )
    assert run_pipeline(ctx.engine, ctx.config, "P", child=ctx.child).status == RunStatus.SKIPPED
    with ctx.engine.connect() as conn:
        assert len(runlog.run_candidates(conn, p)) == 1


def test_replacement_changes_dispatch_atomically_in_both_directions(ctx):
    p, a, _ = seed(ctx)
    with ctx.engine.begin() as conn:
        run = start_run(conn, p)
    pause(ctx, mode="FINISH")
    pause(ctx, replace=True)
    with pytest.raises(RunRefusedError, match="DRAIN"):
        queue(ctx, a, run)
    pause(ctx, mode="FINISH", replace=True)
    assert queue(ctx, a, run)
    with ctx.engine.connect() as conn:
        versions = conn.execute(
            text(
                "SELECT ACTIVE_RUNS AS mode,RESUMED_AT AS resumed FROM AUD_PIPELINE_PAUSES "
                "ORDER BY PIPELINE_PAUSE_ID"
            )
        ).all()
        assert [row.mode for row in versions] == [
            "FINISH",
            "DRAIN",
            "FINISH",
        ]
        assert all(row.resumed is not None for row in versions[:-1])
        assert versions[-1].resumed is None
    resume(ctx)
    with pytest.raises(RunStateError, match="found no active pipeline pause"):
        pause(ctx, replace=True)


def test_run_paused_permission_is_not_drained(ctx):
    p, _, _ = seed(ctx)
    pause(ctx)
    permission = invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            action=ControlAction.RUN_PAUSED,
            request_key="maintenance-once",
            reason="one permitted run",
        ),
    )
    run = permission.execution_run_id
    assert (
        run_pipeline(
            ctx.engine, ctx.config, "P", selector=RunSelector(run_id=run), child=ctx.child
        ).status
        == RunStatus.SUCCESS
    )
    with ctx.engine.connect() as conn:
        assert not standing_pauses.drains(conn, p, run)


@pytest.mark.parametrize("replace_pause", [False, True])
def test_pause_or_replacement_racing_dispatch_serializes_at_the_pause_lock(ctx, replace_pause):
    p, a, _ = seed(ctx)
    with ctx.engine.begin() as conn:
        run = start_run(conn, p)
    if replace_pause:
        pause(ctx, mode="FINISH")

    def dispatch():
        try:
            return queue(ctx, a, run)
        except RunRefusedError:
            return None

    _, attempt = two_at_once(
        lambda: pause(ctx, replace=replace_pause),
        dispatch,
        at=(ctx.engine, "begin"),
    )
    with ctx.engine.connect() as conn:
        assert standing_pauses.drains(conn, p, run)
        assert conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_TASK_ATTEMPTS")
        ).scalar_one() == int(attempt is not None)
    with pytest.raises(RunRefusedError, match="DRAIN"):
        queue(ctx, a, run)


def test_pause_racing_retry_claim_keeps_unclaimed_work_queued(ctx):
    p, a, b = seed(ctx)
    with ctx.engine.begin() as conn:
        conn.execute(text("DELETE FROM CFG_TASK_DEPENDENCY WHERE PIPELINE_ID=:p"), {"p": p})
        run = start_run(conn, p)
        summary = transitions.find_or_create_task_run(conn, a, run)
        failed = transitions.queue_attempt(conn, summary.task_run_id, current_actor())
        transitions.claim_attempt(
            conn,
            failed,
            current_actor(),
            owner="first",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        transitions.finish_attempt(
            conn, failed, AttemptStatus.FAILED, current_actor(), owner="first"
        )
        attempt = transitions.queue_attempt(
            conn,
            summary.task_run_id,
            current_actor(),
            previous_attempt_id=failed,
            not_before=datetime.now(UTC) - timedelta(seconds=1),
        )

    pending = queue(ctx, b, run)

    def claim():
        try:
            with ctx.engine.begin() as conn:
                transitions.claim_attempt(
                    conn,
                    attempt,
                    current_actor(),
                    owner="agent",
                    lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
                )
            return True
        except RunRefusedError:
            return False

    _, claimed = two_at_once(lambda: pause(ctx), claim, at=(ctx.engine, "begin"))
    with ctx.engine.connect() as conn:
        row = conn.execute(
            text("SELECT STATUS AS status FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:id"),
            {"id": attempt},
        ).one()
        assert row.status == (AttemptStatus.CLAIMED if claimed else AttemptStatus.QUEUED)

    with pytest.raises(RunRefusedError, match="DRAIN"), ctx.engine.begin() as conn:
        transitions.claim_attempt(
            conn,
            pending,
            current_actor(),
            owner="later-agent",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )


@pytest.mark.parametrize("field", ["missing-outcome", "active-runs-task"])
def test_task_pause_request_refuses_missing_outcome_and_pipeline_mode_before_writes(ctx, field):
    seed(ctx)
    args = {
        "pipeline_code": "P",
        "task_code": "a",
        "action": ControlAction.PAUSE,
        "reason": "maintenance",
    }
    if field == "active-runs-task":
        args.update(active_runs="DRAIN", outcome=RunStatus.SKIPPED)
    with pytest.raises(UsageError) as refused:
        ControlRequest(**args)
    assert "pipeline P task a" in str(refused.value)
    assert (
        "a task pause needs --outcome SUCCESS, SKIPPED or FAILED"
        if field == "missing-outcome"
        else "task pauses take an outcome, not --active-runs"
    ) in str(refused.value)
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_PIPELINE_PAUSES")).scalar_one()
            == 0
        )


def test_resume_racing_second_controller_keeps_one_next_attempt(ctx):
    from etl_craft.core.errors import StaleTransitionError

    p, a, _ = seed(ctx)
    with ctx.engine.begin() as conn:
        run = start_run(conn, p)
    pause(ctx)
    with pytest.raises(RunRefusedError, match="DRAIN"):
        queue(ctx, a, run)

    def controller():
        with suppress(RunStateError):
            resume(ctx)
        try:
            return queue(ctx, a, run)
        except StaleTransitionError:
            return None

    results = two_at_once(controller, controller, at=(ctx.engine, "begin"))
    assert sum(result is not None for result in results) == 1
    with ctx.engine.connect() as conn:
        assert not standing_pauses.drains(conn, p, run)
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_TASK_ATTEMPTS")).scalar_one() == 1
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) AS count FROM AUD_PIPELINE_PAUSES WHERE RESUMED_AT IS NOT NULL"
                )
            ).scalar_one()
            == 1
        )


def test_event_wait_finishes_during_drain_but_its_downstream_waits_for_resume(ctx, tmp_path):
    from etl_craft.engine.repository.events import run_event_files
    from etl_craft.execution.events import check_event

    path = tmp_path / "incoming.csv"
    scripts = ctx.config.project_dir / "python_scripts"
    scripts.mkdir()
    (scripts / "load.py").write_text(
        "from pathlib import Path\n"
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    output = task.config.project_dir / 'loaded.csv'\n"
        "    with output.open('a') as target:\n"
        "        for file in task.event_files:\n"
        "            target.write(Path(file).read_text())\n"
        "    return ScriptResult(row_count=1)\n"
    )
    with ctx.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        event = add_task(
            conn,
            p,
            "wait",
            "EVENT_WAIT",
            EVENT_FILE=str(path),
            EVENT_SETTLE_SECONDS="0",
            EVENT_POLL_SECONDS="1",
        )
        load = add_task(conn, p, "load", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        add_dependency(conn, p, load, event)
        run = start_run(conn, p)
    now = datetime.now(UTC)
    assert check_event(ctx.engine, ctx.config, run, event, now).next_check_at is not None
    pause(ctx)
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='PYTHON' WHERE TASK_ID=:task"), {"task": event}
        )
    path.write_text("id\n1\n")
    assert (
        check_event(ctx.engine, ctx.config, run, event, now + timedelta(seconds=1)).status
        == RunStatus.SUCCESS
    )
    assert (
        check_event(ctx.engine, ctx.config, run, event, now + timedelta(seconds=2)).status
        == RunStatus.SUCCESS
    )
    with pytest.raises(RunRefusedError, match="DRAIN"):
        queue(ctx, load, run)
    with ctx.engine.connect() as conn:
        assert run_event_files(conn, run) == (str(path.resolve()),)
        assert runlog.fetch_task_run_status(conn, load, run) is None
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_TASK_ATTEMPTS")).scalar_one() == 1
        )
    assert not (ctx.config.project_dir / "loaded.csv").exists()
    resume(ctx)
    assert (
        run_pipeline(ctx.engine, ctx.config, "P", selector=RunSelector(run_id=run)).status
        == RunStatus.SUCCESS
    )
    with ctx.engine.connect() as conn:
        assert run_event_files(conn, run) == (str(path.resolve()),)
        assert (
            conn.execute(
                text(
                    "SELECT count(*) AS count FROM AUD_TASK_ATTEMPTS a JOIN "
                    "AUD_TASK_RUN_LOG t ON t.TASK_RUN_ID=a.TASK_RUN_ID WHERE t.TASK_ID=:task"
                ),
                {"task": load},
            ).scalar_one()
            == 1
        )

    assert (ctx.config.project_dir / "loaded.csv").read_text() == "id\n1\n"


def test_task_pause_skips_an_admitted_unstarted_task_and_records_its_version(ctx):
    from etl_craft.core.enums import InterventionAction

    p, a, b = seed(ctx)
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASKS SET RUN_CONDITION="
                "REPLACE(RUN_CONDITION, '.SUCCESS', '.FINISHED') WHERE TASK_ID=:task"
            ),
            {"task": b},
        )
        run = start_run(conn, p)
    invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            task_code="a",
            action=ControlAction.PAUSE,
            outcome=RunStatus.SKIPPED,
            reason="source intentionally omitted",
        ),
    )
    pause(ctx)

    def applied():
        with ctx.engine.connect() as conn:
            return runlog.fetch_task_run_status(conn, a, run) == RunStatus.SKIPPED

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            contextvars.copy_context().run,
            run_pipeline,
            ctx.engine,
            ctx.config,
            "P",
            selector=RunSelector(run_id=run),
            child=ctx.child,
        )
        try:
            wait_for(applied)
            with ctx.engine.connect() as conn:
                assert runlog.fetch_pipeline_run_status(conn, run) == RunStatus.IN_PROGRESS
                assert runlog.fetch_task_run_status(conn, b, run) is None
        finally:
            resume(ctx)
        assert future.result(timeout=30).status == RunStatus.SUCCESS
    with ctx.engine.connect() as conn:
        assert runlog.fetch_task_run_status(conn, a, run) == RunStatus.SKIPPED
        assert runlog.fetch_task_run_status(conn, b, run) == RunStatus.SUCCESS
        intervention = conn.execute(
            text(
                "SELECT ACTION AS action,TO_STATUS AS outcome,ITEM_KEY AS version FROM "
                "AUD_RUN_INTERVENTIONS WHERE TASK_ID=:task"
            ),
            {"task": a},
        ).one()
        assert intervention.action == InterventionAction.PAUSE_APPLIED
        assert intervention.outcome == RunStatus.SKIPPED
        assert intervention.version == str(
            conn.execute(
                text(
                    "SELECT PIPELINE_PAUSE_ID AS id FROM AUD_PIPELINE_PAUSES "
                    "WHERE TASK_ID IS NOT NULL"
                )
            ).scalar_one()
        )


def test_task_pause_skips_unstarted_tasks_but_leaves_running_attempts_to_finish_normally(ctx):
    p, a, b = seed(ctx)
    with ctx.engine.begin() as conn:
        run = start_run(conn, p)
        task_run = transitions.find_or_create_task_run(conn, a, run)
        attempt = transitions.queue_attempt(conn, task_run.task_run_id, current_actor())
        transitions.claim_attempt(
            conn,
            attempt,
            current_actor(),
            owner="worker",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        transitions.start_attempt(conn, attempt, current_actor(), owner="worker")
    invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            task_code="a",
            action=ControlAction.PAUSE,
            outcome=RunStatus.SKIPPED,
            reason="next admissions only",
        ),
    )
    invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P",
            task_code="b",
            action=ControlAction.PAUSE,
            outcome=RunStatus.SKIPPED,
            reason="omit downstream",
        ),
    )
    with ctx.engine.begin() as conn:
        transitions.finish_attempt(
            conn, attempt, AttemptStatus.SUCCESS, current_actor(), owner="worker"
        )
        assert runlog.fetch_task_run_status(conn, a, run) == RunStatus.SUCCESS
    result = run_pipeline(
        ctx.engine, ctx.config, "P", selector=RunSelector(run_id=run), child=ctx.child
    )
    assert result.status == RunStatus.SUCCESS
    with ctx.engine.connect() as conn:
        assert runlog.fetch_task_run_status(conn, a, run) == RunStatus.SUCCESS
        assert runlog.fetch_task_run_status(conn, b, run) == RunStatus.SKIPPED
        applied = (
            conn.execute(
                text(
                    "SELECT TASK_ID AS task FROM AUD_RUN_INTERVENTIONS WHERE ACTION='PAUSE_APPLIED'"
                )
            )
            .scalars()
            .all()
        )
        assert applied == [b]


def test_drain_blocks_a_due_retry_and_resume_finishes_the_original_run(ctx):
    from etl_craft.execution.retries import refresh_retries

    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(
            conn, pipeline, "a", "PYTHON", BEHAVIOUR="succeed", RETRIES="1", RETRY_DELAY_SECONDS="0"
        )
        run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, task, run)
        attempt = transitions.queue_attempt(conn, summary.task_run_id, current_actor())
        transitions.claim_attempt(
            conn,
            attempt,
            current_actor(),
            owner="first",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        from test_retries import transient_failure

        transient_failure(conn, attempt)
        transitions.finish_attempt(
            conn, attempt, AttemptStatus.FAILED, current_actor(), owner="first"
        )
    pause(ctx)
    waiting, exhausted = refresh_retries(ctx.engine, ctx.config, run, {task})
    assert task in waiting and task not in exhausted
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_TASK_ATTEMPTS")).scalar_one() == 1
        )
        assert runlog.fetch_pipeline_run_status(conn, run) == RunStatus.IN_PROGRESS
    resume(ctx)
    result = run_pipeline(
        ctx.engine, ctx.config, "P", selector=RunSelector(run_id=run), child=ctx.child
    )
    assert result.status == RunStatus.SUCCESS and result.pipeline_run_id == run
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT STATUS AS status,TASK_RUN_ID AS task_run_id,ATTEMPT_NUMBER AS number "
                "FROM AUD_TASK_ATTEMPTS ORDER BY ATTEMPT_NUMBER"
            )
        ).all()
        assert [row.status for row in rows] == [AttemptStatus.FAILED, AttemptStatus.SUCCESS]
        assert {row.task_run_id for row in rows} == {summary.task_run_id}
        assert [row.number for row in rows] == [1, 2]
        assert (
            conn.execute(
                text("SELECT count(*) AS count FROM AUD_RUN_INTERVENTIONS WHERE ACTION='REOPEN'")
            ).scalar_one()
            == 0
        )


def test_an_admitted_dependency_wait_finishes_during_drain_without_dispatching(ctx):
    from etl_craft.execution.gates import Clock, check_gate
    from fixtures.metadata import finish_run

    with ctx.engine.begin() as conn:
        upstream = add_pipeline(conn, "UP")
        source = add_task(conn, upstream, "source", "PYTHON", BEHAVIOUR="succeed")
        up_run = start_run(conn, upstream)
        up_task = transitions.find_or_create_task_run(conn, source, up_run)
        pipeline = add_pipeline(conn, "P")
        target = add_task(conn, pipeline, "target", "PYTHON", BEHAVIOUR="succeed")
        add_dependency(conn, pipeline, target, source, upstream_pipeline=upstream)
        run = start_run(conn, pipeline)
    now = datetime.now(UTC)
    with selected_project(1):
        first = check_gate(ctx.engine, run, pipeline, task_id=target, clock=Clock(now=lambda: now))
    assert first.next_check_at is not None
    pause(ctx)
    with ctx.engine.begin() as conn:
        transitions.mark_task_run(
            conn,
            up_task.task_run_id,
            status=RunStatus.SUCCESS,
            error_message="source completed",
            target_count=1,
        )
        finish_run(conn, up_run)

    def finished_wait():
        with ctx.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT NEXT_CHECK_AT AS next_check FROM AUD_GATE_WAITS "
                    "WHERE PIPELINE_RUN_ID=:run AND TASK_ID=:task"
                ),
                {"run": run, "task": target},
            ).one()
            return row.next_check is None

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            contextvars.copy_context().run,
            run_pipeline,
            ctx.engine,
            ctx.config,
            "P",
            selector=RunSelector(run_id=run),
            child=ctx.child,
            clock=Clock(now=lambda: now + timedelta(minutes=5)),
        )
        try:
            wait_for(finished_wait)
            with ctx.engine.connect() as conn:
                assert runlog.fetch_pipeline_run_status(conn, run) == RunStatus.IN_PROGRESS
                assert (
                    conn.execute(
                        text("SELECT count(*) AS count FROM AUD_TASK_ATTEMPTS")
                    ).scalar_one()
                    == 0
                )
        finally:
            resume(ctx)
        assert future.result(timeout=30).status == RunStatus.SUCCESS
    with ctx.engine.connect() as conn:
        consumed = conn.execute(
            text(
                "SELECT CONSUMED_PIPELINE_RUN_ID AS run "
                "FROM AUD_DEPENDENCY_CONSUMPTION WHERE TASK_ID=:task"
            ),
            {"task": target},
        ).one()
        assert consumed.run == up_run
