"""Read-only projection of a recovery's task admissions."""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.enums import NOT_RETRYABLE_STATUSES, DependencyType, RunStatus
from etl_craft.core.graph import DependencyGraph, RunState, TaskRunState

_EDGE_REASON = {
    DependencyType.SUCCESS: "succeeds",
    DependencyType.FAILURE: "fails",
    DependencyType.ALWAYS: "finishes",
    DependencyType.HAS_DATA: "succeeds and writes rows",
}


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


def plan_tasks(
    graph: DependencyGraph,
    codes: dict[int, str],
    state: RunState,
    *,
    selected: int | None = None,
    downstream: bool = False,
    scope_only: int | None = None,
) -> RecoveryPreview:
    """Use the graph's own edge and threshold rules against recorded and possible outcomes."""
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
            least, most, required, reason = graph.admission_range(
                task_id, outcomes, changing, selected
            )
            if most < required:
                skip.append(PlannedTask(name, f"Its dependencies cannot be met. {reason}"))
                if status is None and selected is None:
                    outcomes[task_id] = TaskRunState(status=RunStatus.SKIPPED)
            elif least >= required and selected is None and task_id in ready:
                run.append(PlannedTask(name, "Its recorded dependencies are satisfied."))
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
    edges = graph.dependencies_of(task_id)
    conditions = [
        f"{codes[edge.depends_on_task_id]} {_EDGE_REASON[DependencyType(edge.dependency_type)]}"
        for edge in edges
        if edge.depends_on_task_id in changing
    ]
    if selected is not None:
        conditions.insert(0, f"{codes[selected]} succeeds")
    if graph.total_edge_count(task_id) > len(edges):
        conditions.append("the cross-pipeline gate admits the task")
    return "; ".join(dict.fromkeys(conditions))
