"""Read-only projection of a recovery's task admissions."""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.enums import NOT_RETRYABLE_STATUSES, RunStatus
from etl_craft.core.graph import DependencyGraph, RunState, TaskRunState


@dataclass(frozen=True)
class PlannedTask:
    """One task and the reason for its projected admission."""

    task_code: str
    reason: str


@dataclass(frozen=True)
class RecoveryPreview:
    """Tasks the engine can admit, retain, or decide later."""

    SCHEMA: ClassVar[str] = "etl-craft/recovery-preview/1"

    will_run: tuple[PlannedTask, ...]
    will_skip: tuple[PlannedTask, ...]
    depends_on_upstream: tuple[PlannedTask, ...]
    start_condition: str | None = None


def plan_tasks(
    graph: DependencyGraph,
    codes: dict[int, str],
    state: RunState,
    *,
    selected: int | None = None,
    downstream: bool = False,
    scope_only: int | None = None,
) -> RecoveryPreview:
    """Use the graph's run conditions against recorded and possible outcomes."""
    scope = set(graph.task_ids) if selected is None else {selected}
    if selected is not None and downstream:
        scope |= graph.downstream_of(selected)
    if scope_only is not None:
        scope = {scope_only}
    ready = set(graph.ready(state))
    outcomes = dict(state)
    changing: set[int] = set()
    run: list[PlannedTask] = []
    skip: list[PlannedTask] = []
    conditional: list[PlannedTask] = []
    for task_id in (item for wave in graph.waves() for item in wave):
        name = codes[task_id]
        status = state.get(task_id, TaskRunState()).status
        if task_id not in scope:
            skip.append(PlannedTask(name, "Outside the selected task scope."))
        elif task_id == selected:
            run.append(PlannedTask(name, "The selected task runs again under its recorded run."))
            changing.add(task_id)
        elif selected is None and status in NOT_RETRYABLE_STATUSES:
            skip.append(PlannedTask(name, f"Retains its recorded {status} state."))
        else:
            value = graph.admission(task_id, outcomes, changing)
            reason = f"Condition: {graph.node(task_id).rule}."
            if value is False:
                skip.append(PlannedTask(name, f"Its condition cannot be met. {reason}"))
                if status is None and selected is None:
                    outcomes[task_id] = TaskRunState(status=RunStatus.SKIPPED)
            elif value is True and selected is None and task_id in ready:
                run.append(PlannedTask(name, "Its recorded condition is met."))
                changing.add(task_id)
            else:
                detail = _conditions(graph, codes, task_id, changing, selected)
                conditional.append(PlannedTask(name, f"{reason} {detail}".strip()))
                changing.add(task_id)
    return RecoveryPreview(tuple(run), tuple(skip), tuple(conditional))


def _conditions(
    graph: DependencyGraph,
    codes: dict[int, str],
    task_id: int,
    changing: set[int],
    selected: int | None,
) -> str:
    conditions = [
        f"it depends on how {codes[edge.depends_on_task_id]} ends"
        for edge in graph.dependencies_of(task_id)
        if edge.depends_on_task_id in changing
    ]
    if selected is not None:
        conditions.insert(0, f"{codes[selected]} runs again first")
    if graph.node(task_id).cross:
        conditions.append("its condition reads fresh output from other pipelines")
    return "; ".join(dict.fromkeys(conditions))
