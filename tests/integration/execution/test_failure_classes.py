"""Real script attempts preserve classification and the admission policy."""

import os
import re
import subprocess
import sys
from dataclasses import replace

import pytest
from sqlalchemy import event, text

from etl_craft.core.actor import current_actor
from etl_craft.core.enums import ActionName, ApiRole, FailureClass, RetryOn, RunStatus
from etl_craft.engine.attempt_resources import AttemptResources, record_resources
from etl_craft.engine.repository.catalog import fetch_task_runs
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.execution.attempt_types import TaskRun
from etl_craft.execution.pipeline import run_pipeline
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.snapshots import success_cohort, task_run_view
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run, task_run
from integration.execution.test_pipeline import config as config


@pytest.mark.parametrize(
    "exception,policy,count,status,kind",
    [
        ("TransientError", RetryOn.TRANSIENT, 2, RunStatus.SUCCESS, FailureClass.TRANSIENT),
        ("PermanentError", RetryOn.TRANSIENT, 1, RunStatus.FAILED, FailureClass.PERMANENT),
        ("TransientError", RetryOn.NONE, 1, RunStatus.FAILED, FailureClass.TRANSIENT),
        ("PermanentError", RetryOn.ANY, 2, RunStatus.SUCCESS, FailureClass.PERMANENT),
        ("LookupError", RetryOn.TRANSIENT_AND_UNKNOWN, 2, RunStatus.SUCCESS, FailureClass.UNKNOWN),
        ("LookupError", RetryOn.TRANSIENT, 1, RunStatus.FAILED, FailureClass.UNKNOWN),
    ],
)
def test_script_failure_policy_and_historical_explanation(
    engine_db, config, exception, policy, count, status, kind
):
    project = config.project_dir
    (project / "python_scripts").mkdir(exist_ok=True)
    (project / "python_scripts" / "load.py").write_text(
        "from pathlib import Path\n"
        "from etl_craft.scripting import ScriptResult, TransientError, PermanentError\n"
        "def run():\n"
        "    flag = Path(__file__).with_suffix('.seen')\n"
        "    if not flag.exists():\n"
        "        flag.touch()\n"
        f"        raise {exception}('source unavailable')\n"
        "    return ScriptResult(row_count=1)\n"
    )
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task_id = add_task(
            conn,
            pipeline,
            "load",
            "PYTHON",
            SCRIPT_FILE="python_scripts/load.py",
            RETRIES="3",
            RETRY_DELAY_SECONDS="0",
            RETRY_ON=policy,
        )
    outcome = run_pipeline(engine, config, "P")
    assert outcome.status == status
    with engine.connect() as conn:
        attempts = conn.execute(
            text(
                "SELECT a.FAILURE_CLASS AS failure_class, a.FAILURE_SOURCE AS failure_source, "
                "a.FAILURE_CODE AS failure_code, a.RETRY_ON AS retry_on, a.RETRYABLE AS retryable "
                "FROM AUD_TASK_ATTEMPTS a JOIN AUD_TASK_RUN_LOG t ON t.TASK_RUN_ID=a.TASK_RUN_ID "
                "WHERE t.TASK_ID=:task ORDER BY a.ATTEMPT_NUMBER"
            ),
            {"task": task_id},
        ).all()
        with selected_project(1):
            history = fetch_task_runs(conn)[task_id][0]
    assert len(attempts) == count
    failed = attempts[0]
    assert failed.failure_class == kind
    assert failed.failure_source == exception
    assert failed.failure_code is None
    assert failed.retry_on == policy
    assert bool(failed.retryable) == (count > 1)
    ctx = OperationContext(
        engine, replace(config, retry_on=RetryOn.NONE), current_actor(), role=ApiRole.VIEWER
    )
    run_id = outcome.pipeline_run_id
    explanation = act(ctx, ActionName.EXPLAIN, pipeline_code="P", task_code="load", run_id=run_id)
    for attempt in explanation.task.attempts:
        if attempt.status == RunStatus.FAILED:
            first, last = attempt.first_error, attempt.last_error
            assert first is not None and last is not None
            assert first.event.error_class == exception
            assert first.event.failure_class == kind
            assert last.event.exit_code == (
                "HANDLER" if exception == "LookupError" else exception.removesuffix("Error").upper()
            )
            assert first.event.sequence == 1
            assert last.event.sequence == (2 if exception == "LookupError" else 1)
            assert first.offset is not None and last.offset is not None
            assert first.state == last.state == "LIVE"
            raw = b"".join(act(ctx, ActionName.LOGS, attempt_id=attempt.attempt_id))
            for anchor in (first, last):
                assert raw[: anchor.offset].count(b"\n") + 1 == anchor.line
                assert raw[anchor.offset :].splitlines()[0].decode() == anchor.text
        else:
            assert attempt.first_error is attempt.last_error is None
        assert attempt.peak_rss_bytes is not None and attempt.peak_rss_bytes > 0
        assert attempt.cpu_seconds is not None and attempt.cpu_seconds >= 0
        assert attempt.owner_id is not None
        record_resources(engine, attempt.attempt_id, attempt.owner_id, AttemptResources(0, 0))
    refreshed = act(ctx, ActionName.EXPLAIN, pipeline_code="P", task_code="load", run_id=run_id)
    assert refreshed.task.attempts == explanation.task.attempts
    with engine.connect() as conn:
        cohort = success_cohort(conn, task_id)
    assert cohort.run_count == int(status == RunStatus.SUCCESS)
    assert cohort.metrics["duration_seconds"].sample_size == cohort.run_count
    assert cohort.metrics["reject_count"].sample_size == 0
    assert cohort.metrics["reject_count"].median is None
    reason = explanation.task.attempts[0].retry_reason
    assert f"{kind}: {exception}" in reason
    assert f"RETRY_ON={policy}" in reason
    assert reason in history.failure_reasons[0]
    status_view = act(ctx, ActionName.STATUS, pipeline_code="P", run_id=run_id)
    assert status_view.tasks[0].explanation.task.attempts[0].retry_reason == reason


def test_selected_task_cohort_breaks_ties_and_stays_in_budget(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task_id = add_task(conn, pipeline, "load", "PYTHON")
        for value in range(21):
            run_id = start_run(conn, pipeline)
            task_run_id = task_run(conn, task_id, run_id, target_count=value)
            finish_run(conn, run_id)
        conn.execute(text("UPDATE AUD_TASK_RUN_LOG SET END_DATE = '2026-01-01 00:00:00+00:00'"))
        reads = []

        def count_read(_conn, _cursor, statement, *_args):
            reads.append(statement)

        event.listen(conn, "before_cursor_execute", count_read)
        try:
            with selected_project(1):
                view = task_run_view(conn, pipeline, task_run_id=task_run_id)
        finally:
            event.remove(conn, "before_cursor_execute", count_read)
    # Baseline: summary, attempts, applied pause, and trigger links.
    assert len(reads) <= 4 + 2
    assert view is not None and view.success_cohort is not None
    assert view.success_cohort.run_count == 20
    metric = view.success_cohort.metrics["target_count"]
    assert (metric.median, metric.sample_size) == (10.5, 20)


@pytest.mark.parametrize("failed", [False, True])
def test_supervisor_crash_after_reap_leaves_resource_evidence_absent(engine_db, config, failed):
    config.python_scripts_dir.mkdir(exist_ok=True)
    (config.python_scripts_dir / "load.py").write_text(
        "from etl_craft.scripting import PermanentError, ScriptResult\ndef run():\n"
        + (
            "    raise PermanentError('recorded before reap')\n"
            if failed
            else "    return ScriptResult(1)\n"
        )
    )
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
    program = """
import sys
from dataclasses import replace
from etl_craft.config import load_config
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.engine.connection import engine_db
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.execution.pipeline import run_pipeline
config = load_config(sys.argv[1])
config = replace(config, artifacts=replace(config.artifacts, store=None))
engine = engine_db(config)
engine.update_execution_options(reparse_required=False)
with acting_as(SYSTEM_ACTOR), selected_project(1):
    run_pipeline(engine, config, "P")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(config.config_path)],
        env=os.environ | {"ETL_CRAFT_FAULT": "supervisor.before_attempt_resources:kill"},
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 137, re.findall(rb"[\w.]+Error:", result.stderr)
    with engine_db.engine.connect() as conn:
        evidence = conn.execute(
            text(
                "SELECT ATTEMPT_ID AS attempt_id, STATUS AS status, PEAK_RSS_BYTES AS rss, "
                "CPU_SECONDS AS cpu, FIRST_ERROR_OFFSET AS anchor_offset "
                "FROM AUD_TASK_ATTEMPTS"
            )
        ).one()
    assert evidence.status == (RunStatus.FAILED if failed else RunStatus.SUCCESS)
    assert evidence.rss is evidence.cpu is evidence.anchor_offset is None
    ctx = OperationContext(engine_db.engine, config, current_actor(), role=ApiRole.VIEWER)
    attempt = act(ctx, ActionName.ATTEMPT, attempt_id=evidence.attempt_id)
    if failed:
        assert attempt.first_error is not None
        assert attempt.first_error.state == "LIVE"
        assert "recorded before reap" in attempt.first_error.text
    else:
        assert attempt.first_error is attempt.last_error is None


def test_validate_names_the_task_and_allowed_retry_policies(engine_db, config):
    from etl_craft.services.validate import validate

    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(conn, pipeline, "load", "PYTHON", RETRY_ON="sometimes")
    report = validate(engine_db.engine, config, "P")
    assert report.failed
    assert any(
        "RETRY_ON" in str(item) and "load" in str(item) and "TRANSIENT" in str(item)
        for item in report.findings
    )


@pytest.mark.parametrize("previous_policy", [None, "NONE"])
def test_admission_fills_only_an_unrecorded_queued_policy(engine_db, config, previous_policy):
    from etl_craft.engine import transitions
    from etl_craft.execution.runner import admit_attempt
    from fixtures.metadata import start_run

    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "load", "PYTHON", RETRY_ON="ANY")
        run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
        queued = transitions.queue_attempt(conn, summary, current_actor())
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET RETRY_ON=:policy WHERE ATTEMPT_ID=:id"),
            {"policy": previous_policy, "id": queued},
        )
    admitted = admit_attempt(
        engine,
        config,
        TaskRun(
            pipeline_code="P", task_code="load", task_id=task, pipeline_run_id=run, force=False
        ),
    )
    assert admitted.attempt_id == queued
    with engine.connect() as conn:
        policy = conn.execute(
            text("SELECT RETRY_ON AS retry_on FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:id"),
            {"id": queued},
        ).scalar_one()
    assert policy == ("ANY" if previous_policy is None else "NONE")


def test_retry_keeps_the_different_errors_and_the_selected_task_budget(engine_db, config):
    script = config.python_scripts_dir / "load.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "from etl_craft.scripting import PermanentError, TransientError\n"
        "def run(task):\n"
        "    flag = task.config.host_dir / 'attempt-one-seen'\n"
        "    if flag.exists():\n"
        "        raise PermanentError('second error')\n"
        "    flag.touch()\n"
        "    raise TransientError('first error')\n"
    )
    engine = engine_db.engine
    with engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(
            conn,
            pipeline,
            "load",
            "PYTHON",
            SCRIPT_FILE="python_scripts/load.py",
            RETRIES="1",
            RETRY_DELAY_SECONDS="0",
            RETRY_ON="TRANSIENT",
        )
    outcome = run_pipeline(engine, config, "P")
    assert outcome.status == RunStatus.FAILED
    read_counts = []

    def count_read(_conn, _cursor, _statement, *_args):
        read_counts.append(1)

    ctx = OperationContext(engine, config, current_actor(), role=ApiRole.VIEWER)
    with engine.connect() as conn, selected_project(1):
        selected = act(
            ctx,
            ActionName.EXPLAIN,
            pipeline_code="P",
            task_code="load",
            run_id=outcome.pipeline_run_id,
        ).task
        assert selected is not None
        task_run_view(conn, pipeline, task_run_id=selected.task_run_id)
        event.listen(conn, "before_cursor_execute", count_read)
        try:
            task_run_view(conn, pipeline, task_run_id=selected.task_run_id)
            original_count = len(read_counts)
            read_counts.clear()
            task = task_run_view(conn, pipeline, task_run_id=selected.task_run_id, ctx=ctx)
        finally:
            event.remove(conn, "before_cursor_execute", count_read)
    assert len(read_counts) == original_count <= 6
    assert task is not None
    first, second = task.attempts
    for attempt, name, detail in (
        (first, "TransientError", "first error"),
        (second, "PermanentError", "second error"),
    ):
        anchor = attempt.first_error
        assert anchor is not None and anchor == attempt.last_error
        assert anchor.event.error_class == name and anchor.event.sequence == 1
        assert anchor.text is not None and detail in anchor.text
    with engine.connect() as conn, selected_project(1):
        unresolved = task_run_view(conn, pipeline, task_run_id=selected.task_run_id)
        assert unresolved is not None
        assert [a.first_error.offset for a in unresolved.attempts] == [
            a.first_error.offset for a in task.attempts
        ]
