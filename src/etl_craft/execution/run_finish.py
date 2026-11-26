"""Finalizing a pipeline run: its outcome, SLA and unsatisfiable tasks."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.engine import Connection, Engine

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.conditions import Reading, describe
from etl_craft.core.enums import (
    TERMINAL_STATUSES,
    AttemptStatus,
    GateOutcome,
    Handler,
    InterventionAction,
    RunStatus,
    SlaStatus,
)
from etl_craft.core.graph import DependencyGraph, TaskRunState
from etl_craft.engine import controls, runlog, transitions
from etl_craft.engine.queries import statement
from etl_craft.engine.repository import trackers
from etl_craft.engine.repository.intervention_rows import fetch_interventions, fetch_task_rows
from etl_craft.engine.repository.runs import fetch_task_statuses_for_run
from etl_craft.engine.repository.tasks import fetch_admitted_parameters
from etl_craft.execution import leases
from etl_craft.execution.readiness import condition_decision
from etl_craft.execution.run_types import (
    PipelineOutcome,
    PipelineRun,
    RunHooks,
    call_hook,
)
from etl_craft.execution.sla import SlaLapse, SlaWatch
from etl_craft.handlers.parameters import pipeline_fail_options

logger = logging.getLogger(__name__)


@acting_as(SYSTEM_ACTOR)
def settle_unsatisfiable(
    engine: Engine,
    graph: DependencyGraph,
    pipeline_run_id: int,
    task_codes: dict[int, str],
    *,
    failures_final: bool = False,
) -> list[int]:
    """Record ``SKIPPED`` for every task not yet run whose dependencies can never be met.

    Returns the tasks recorded.
    """
    with engine.connect() as conn:
        run_state = runlog.fetch_run_state(conn, pipeline_run_id, list(graph.task_ids))
        fences = controls.blocked(conn, pipeline_run_id)
        cancelled = runlog.fetch_pipeline_run_status(conn, pipeline_run_id) == RunStatus.CANCELLED
    if cancelled or None in fences:
        return []
    run_state.update(
        {t: TaskRunState(status=RunStatus.IN_PROGRESS) for t in fences if t is not None}
    )
    skipped: list[int] = []
    for task_id in graph.unsatisfiable(run_state, failures_final=failures_final):
        node = graph.node(task_id)
        reading = Reading()
        graph.evaluate(task_id, run_state, failures_final=failures_final, reading=reading)
        reason = f"condition [{node.rule}] is not met: {describe(reading)}"
        decision = condition_decision(task_id, node.rule, reading, GateOutcome.UNSATISFIED)
        with engine.begin() as conn:
            controls.lock_run(conn, pipeline_run_id)
            if (
                controls.blocked(conn, pipeline_run_id) != fences
                or runlog.fetch_pipeline_run_status(conn, pipeline_run_id) == RunStatus.CANCELLED
            ):
                return skipped
            binding = transitions.find_or_create_task_run(conn, task_id, pipeline_run_id)
            if not binding.created:
                continue
            transitions.finish_task_run(
                conn, binding.task_run_id, status=RunStatus.SKIPPED, error_message=reason
            )
            trackers.record_decisions(conn, pipeline_run_id, (decision,))
        run_state[task_id] = TaskRunState(status=RunStatus.SKIPPED)
        skipped.append(task_id)
        logger.info("%s: SKIPPED — %s", task_codes[task_id], reason)
    return skipped


@dataclass(frozen=True)
class _Judgement:
    status: RunStatus
    failures: list[str]
    tolerated: list[str]


@acting_as(SYSTEM_ACTOR)
def finalize(
    engine: Engine,
    run: PipelineRun,
    hooks: RunHooks,
    never_ready: Sequence[int] = (),
    after_failure: Sequence[int] = (),
) -> PipelineOutcome:
    """End the run from its tasks' statuses, record its SLA, and consume its upstream runs.

    A run whose data tasks all ended ``SKIPPED`` ends ``SKIPPED``, which a downstream
    ``SUCCESS`` dependency does not accept.
    Every task can fail the pipeline according to its configured options.
    """
    settle_unsatisfiable(engine, run.graph, run.pipeline_run_id, run.task_codes)
    with engine.begin() as conn:
        controls.lock_run(conn, run.pipeline_run_id)
        if controls.blocked(conn, run.pipeline_run_id):
            return PipelineOutcome(
                RunStatus(runlog.fetch_pipeline_run_status(conn, run.pipeline_run_id)),
                f"pipeline_run_id={run.pipeline_run_id}: dispatch is fenced; inspect the control "
                "request and release the exact scope before finalizing",
                run.pipeline_run_id,
            )
        running = _running_elsewhere(conn, run.pipeline_code, run.pipeline_run_id)
        if running is not None:
            return running
        judgement = _judge_run(conn, run)
        status = judgement.status
        breached_before = runlog.fetch_run_sla(conn, run.pipeline_run_id).sla_status
        backfill_run = runlog.fetch_run_kind(conn, run.pipeline_run_id).backfill
        ending = transitions.finalize_pipeline_run(
            conn,
            run.pipeline_run_id,
            status,
            sla_in_hours=run.sla_hours,
            owner=leases.run_owner(run.pipeline_run_id),
            consume=not backfill_run,
        )
        current = runlog.fetch_pipeline_run_status(conn, run.pipeline_run_id)
    if not ending.ended:
        message = (
            f"{run.pipeline_code}: pipeline_run_id={run.pipeline_run_id} is {current}: "
            "it was ended "
            f"elsewhere (an operator's cancel, say) while this process was ending it {status}; "
            f"nothing more was recorded. `etl-craft history --pipeline-code "
            f"{run.pipeline_code}` shows "
            "who ended it"
        )
        logger.warning("%s", message)
        return PipelineOutcome(RunStatus(current), message, run.pipeline_run_id)
    sla = ending.sla
    outcome = _outcome(engine, run, judgement, sla, never_ready, after_failure)
    if sla is not None and sla.status == SlaStatus.BREACHED and breached_before != sla.status:
        lapse = SlaLapse(run.pipeline_code, run.pipeline_run_id, sla.sla_hours, sla.elapsed_hours)
        call_hook("on_sla_lapse", hooks.on_sla_lapse, lapse)
    call_hook("on_finalized", hooks.on_finalized, outcome)
    return outcome


def _judge_run(conn: Connection, run: PipelineRun) -> _Judgement:
    """Judge every admitted task and apply the all-skipped rule."""
    current = runlog.fetch_pipeline_run_status(conn, run.pipeline_run_id)
    if current == RunStatus.CANCELLED:
        return _Judgement(RunStatus.CANCELLED, [], [])
    run_state = runlog.fetch_run_state(conn, run.pipeline_run_id, list(run.graph.task_ids))
    data_tasks = {
        task.task_id
        for task in fetch_task_statuses_for_run(conn, run.pipeline_id, run.pipeline_run_id)
        if task.handler != Handler.ALERT
    } & set(run.graph.task_ids)
    condition_skips = set(
        conn.execute(
            statement(conn, "condition_skips"),
            {"run_id": run.pipeline_run_id, "result": GateOutcome.UNSATISFIED},
        ).scalars()
    )
    failures, tolerated = [], []
    for task_id in sorted(run.graph.task_ids, key=run.task_codes.__getitem__):
        state = run_state.get(task_id, TaskRunState())
        status = state.status
        code = run.task_codes[task_id]
        if status not in TERMINAL_STATUSES:
            failures.append(f"{code} ({status or 'never started'})")
            continue
        if status in {RunStatus.SUCCESS, RunStatus.CANCELLED}:
            continue
        if status == RunStatus.FAILED and state.attempt_status == AttemptStatus.LOST:
            failures.append(f"{code} ({AttemptStatus.LOST})")
            continue
        params = fetch_admitted_parameters(conn, task_id, run.pipeline_run_id)
        fail_failed, fail_skipped = pipeline_fail_options(params)
        if status == RunStatus.FAILED:
            if fail_failed:
                failures.append(f"{code} ({RunStatus.FAILED}) [FAIL_PIPELINE_IF_FAILED=Y]")
            else:
                tolerated.append(f"{code} (FAIL_PIPELINE_IF_FAILED=N)")
        if status == RunStatus.SKIPPED and fail_skipped and task_id in condition_skips:
            failures.append(f"{code} (FAIL_PIPELINE_IF_NOT_RUN=Y)")
    judged_tasks = data_tasks or set(run.graph.task_ids)
    if failures:
        status = RunStatus.FAILED
    elif judged_tasks and all(run_state[t].status == RunStatus.SKIPPED for t in judged_tasks):
        status = RunStatus.SKIPPED
    else:
        status = RunStatus.SUCCESS
    return _Judgement(status, failures, tolerated)


def _outcome(
    engine: Engine,
    run: PipelineRun,
    judgement: _Judgement,
    sla: runlog.SlaResult | None,
    never_ready: Sequence[int],
    after_failure: Sequence[int],
) -> PipelineOutcome:
    """Describe the committed ending, its unsuccessful tasks, bypasses and SLA."""
    status = judgement.status
    message = f"{run.pipeline_code}: pipeline_run_id={run.pipeline_run_id} {status}"
    if judgement.tolerated:
        message += f"; tolerated failure: {', '.join(judgement.tolerated)}"
    if judgement.failures:
        listed = ", ".join(judgement.failures)
        message += f" — {len(judgement.failures)} task(s) did not succeed: {listed}"
        if never_ready:
            message += (
                f"; {len(never_ready)} of them could not start because their dependencies "
                "were not met"
            )
        if after_failure:
            skipped = ", ".join(run.task_codes[t] for t in after_failure)
            message += f"; skipped because of the failure: {skipped}"
    with engine.connect() as conn:
        bypasses = [
            change
            for change in fetch_interventions(conn, {run.pipeline_run_id})
            if change.action == InterventionAction.GATE_BYPASS
        ]
    if bypasses:
        where = sorted({change.task_code or run.pipeline_code for change in bypasses})
        message += f"; dependency gates bypassed for {', '.join(where)} (see history)"
    if sla is not None and sla.status == SlaStatus.BREACHED:
        message += f"; {sla.describe()}"
    outcome = PipelineOutcome(status, message, run.pipeline_run_id, sla)
    logger.log(logging.INFO if status == RunStatus.SUCCESS else logging.ERROR, "%s", message)
    return outcome


def _running_elsewhere(
    conn: Connection, pipeline_code: str, pipeline_run_id: int
) -> PipelineOutcome | None:
    """Return the outcome that leaves the run open when a task of it is still running.

    By the time a local run is finalized, every task this process started has ended, so a task
    still ``IN-PROGRESS`` belongs to another process, or to one that died without recording an
    outcome. Either way the run must not be ended under it.
    """
    running = [
        row for row in fetch_task_rows(conn, pipeline_run_id) if row.status == RunStatus.IN_PROGRESS
    ]
    if not running:
        return None
    listed = ", ".join(f"{row.task_code} (task_run_id={row.task_run_id})" for row in running)
    first = running[0].task_code
    message = (
        f"{pipeline_code}: pipeline_run_id={pipeline_run_id} stays IN-PROGRESS: {listed} "
        f"{'is' if len(running) == 1 else 'are'} still IN-PROGRESS in another process. When it "
        f"ends, `etl-craft run --pipeline-code {pipeline_code}` finishes the run. If that process "
        f"is gone, record the task's outcome with `etl-craft mark --pipeline-code {pipeline_code} "
        f"--task-code {first} --status FAILED --stale --reason ...`"
    )
    logger.warning("%s", message)
    return PipelineOutcome(RunStatus.IN_PROGRESS, message, pipeline_run_id)


def sla_watch(
    engine: Engine, pipeline_code: str, run_id: int, hours: float | None, hooks: RunHooks
) -> SlaWatch:
    """Watch run ``run_id`` against ``hours`` of SLA, reporting a lapse to ``hooks``."""
    return SlaWatch(
        engine,
        pipeline_code,
        run_id,
        hours,
        lambda lapse: call_hook("on_sla_lapse", hooks.on_sla_lapse, lapse),
    )
