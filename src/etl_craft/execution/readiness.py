"""Why a task cannot start yet: pending upstream tasks, unready reasons and backfill gates."""

from __future__ import annotations

import json
from dataclasses import replace

from sqlalchemy.engine import Engine

from etl_craft.core.conditions import Facts, Reading, describe
from etl_craft.core.enums import TERMINAL_STATUSES, GateOutcome
from etl_craft.core.graph import DependencyGraph, RunState, TaskRunState
from etl_craft.engine.repository import trackers
from etl_craft.engine.repository.dependencies import (
    fetch_cross_pipeline_task_edges,
)
from etl_craft.execution.gates import CrossPipelineCheck


def backfill_cross_check(engine: Engine, task_id: int) -> CrossPipelineCheck:
    """Bind a task's names in other pipelines for a backfill, which checks none of them.

    A backfill re-runs history as if its upstreams had delivered: each name reads as succeeded
    with data, and every other fact is not known, so a condition that needs one is not met.
    Nothing is consumed.
    """
    with engine.connect() as conn:
        edges = fetch_cross_pipeline_task_edges(conn, task_id)
    return CrossPipelineCheck({edge.task_dependency_id: Facts.delivered() for edge in edges})


def upstream_pending(graph: DependencyGraph, task_id: int, run_state: RunState) -> bool:
    """Whether a same-pipeline upstream of ``task_id`` has not finished yet."""
    return any(
        run_state.get(edge.depends_on_task_id, TaskRunState()).status not in TERMINAL_STATUSES
        for edge in graph.dependencies_of(task_id)
    )


def describe_unready(
    graph: DependencyGraph, task_id: int, pipeline_run_id: int, *, can_never: bool = False
) -> str:
    """Explain why ``task_id`` cannot start in ``pipeline_run_id``."""
    counts = f"(condition [{graph.node(task_id).rule}])"
    if can_never:
        return f"its condition can never be met under pipeline_run_id={pipeline_run_id} {counts}"
    return f"its condition is not met yet under pipeline_run_id={pipeline_run_id} {counts}"


def evaluate_condition(
    graph: DependencyGraph,
    state: RunState,
    task_id: int,
    cross: CrossPipelineCheck,
    *,
    failures_final: bool,
) -> tuple[bool | None, Reading, CrossPipelineCheck]:
    """Apply the bound facts and record whether the cross-pipeline gate was bypassed."""
    reading = Reading()
    value = graph.evaluate(
        task_id, state, cross.facts, reading=reading, failures_final=failures_final
    )
    if value is not True and cross.bypassed:
        return True, reading, cross
    if value is None and task_id in graph.unsatisfiable(state, failures_final=failures_final):
        value = False
    return value, reading, replace(cross, bypassed=False)


def condition_decision(
    task_id: int, rule: str, reading: Reading, outcome: GateOutcome
) -> trackers.GateDecision:
    """Record one deciding evaluation of a task's condition, with the values it read."""
    values = json.dumps(reading.values, sort_keys=True, default=str)
    return trackers.GateDecision.evaluated(task_id, rule, values, outcome, describe(reading))
