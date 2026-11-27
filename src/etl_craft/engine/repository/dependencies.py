"""Dependencies: a pipeline's graph, and the edges the cross-pipeline gates check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Boolean
from sqlalchemy.engine import Connection, Row

from etl_craft.core.conditions import Scope, parse
from etl_craft.core.enums import Handler, YesNo
from etl_craft.core.errors import ConditionError, MetadataError
from etl_craft.core.graph import TaskEdge, TaskNode
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class PipelineGraphData:
    """A pipeline's active tasks and same-pipeline edges, as ``build_graph`` takes them.

    Edges on tasks in other pipelines are not part of the order; each task maps its names in
    other pipelines to their edges, and ``cross_pipeline_task_ids`` names the tasks that have any.
    """

    tasks: list[TaskNode]
    same_pipeline_edges: list[TaskEdge]
    cross_pipeline_task_ids: frozenset[int]
    event_alerts: frozenset[int] = frozenset()


def fetch_pipeline_graph(conn: Connection, pipeline_id: int) -> PipelineGraphData:
    """Return the tasks, their parsed conditions and the edges of ``pipeline_id``.

    The edges of an inactive task are left out: it does not run. An active task that names an
    inactive one in the same pipeline could never run, so it is a ``MetadataError``; so is a
    condition whose names have no derived edge, which ``deploy`` or re-parse writes.
    """
    edges = conn.execute(
        statement(conn, "pipeline_task_dependencies"), {"pipeline_id": pipeline_id}
    ).all()
    on_inactive = [
        f"{row.task_code} depends on {row.depends_on_task_code}"
        for row in edges
        if row.depends_on_pipeline_id == pipeline_id and row.depends_on_active_flag != YesNo.YES
    ]
    if on_inactive:
        raise MetadataError(
            f"active tasks depend on inactive ones ({'; '.join(on_inactive)}); remove them from "
            "the RUN_CONDITION, or reactivate the task"
        )
    rows = tuple(
        conn.execute(statement(conn, "pipeline_graph_tasks"), {"pipeline_id": pipeline_id})
    )
    by_task: dict[int, list[Row[Any]]] = {}
    for row in edges:
        by_task.setdefault(row.task_id, []).append(row)
    tasks = [_node(row, by_task.get(row.task_id, []), pipeline_id) for row in rows]
    same = [
        TaskEdge(row.task_id, row.depends_on_task_id)
        for row in edges
        if row.depends_on_pipeline_id == pipeline_id
    ]
    cross = frozenset(task.task_id for task in tasks if task.cross)
    dependent = {edge.task_id for edge in same} | cross
    alerts = frozenset(
        row.task_id for row in rows if row.handler == Handler.ALERT and row.task_id not in dependent
    )
    return PipelineGraphData(tasks, same, cross, alerts)


def _node(row: Row[Any], edges: list[Row[Any]], pipeline_id: int) -> TaskNode:
    """Parse a task's condition and map each name it reads to its edge."""
    label = f"{row.pipeline_code}.{row.task_code}"
    text = (row.run_condition or "").strip()
    try:
        condition = parse(text, Scope.TASK) if text else None
    except ConditionError as error:
        raise ConditionError(f"{label} RUN_CONDITION {error}") from error
    names: dict[tuple[str, ...], tuple[bool, int]] = {}
    for edge in edges:
        same = edge.depends_on_pipeline_id == pipeline_id
        full = (
            edge.depends_on_project_code,
            edge.depends_on_pipeline_code,
            edge.depends_on_task_code,
        )
        keys: list[tuple[str, ...]] = [full]
        if edge.depends_on_project_code == row.project_code:
            keys.append(full[1:])
        if same:
            keys.append(full[2:])
        target = edge.depends_on_task_id if same else edge.task_dependency_id
        for key in keys:
            names[key] = (same, int(target))
    upstream: dict[tuple[str, ...], int] = {}
    cross: dict[tuple[str, ...], int] = {}
    for name in condition.names() if condition else ():
        if name not in names:
            raise MetadataError(
                f"{label} RUN_CONDITION names {'.'.join(name)}, which has no derived edge; "
                "run `etl-craft deploy` or `etl-craft pipelines re-parse` to derive it"
            )
        same, target = names[name]
        (upstream if same else cross)[name] = target
    return TaskNode(int(row.task_id), row.task_code, condition, upstream, cross)


@dataclass(frozen=True)
class PipelineDependencyEdge:
    """One active dependency of a pipeline on another pipeline."""

    pipeline_dependency_id: int
    depends_on_pipeline_id: int
    upstream_code: str
    upstream_project: str
    same_project: bool
    consume_repairs: bool = True

    @property
    def depends_on_pipeline_code(self) -> str:
        """Display the upstream relative to the consumer's project."""
        return self.upstream_code if self.same_project else ".".join(self.qualified_name)

    @property
    def qualified_name(self) -> tuple[str, str]:
        """The two-part condition name, including the project."""
        return self.upstream_project, self.upstream_code


def fetch_pipeline_dependency_edges(
    conn: Connection, pipeline_id: int
) -> list[PipelineDependencyEdge]:
    """Return the active dependencies of ``pipeline_id`` on other pipelines."""
    rows = conn.execute(
        statement(conn, "pipeline_gate_edges").columns(
            consume_repairs=Boolean, same_project=Boolean
        ),
        {"pipeline_id": pipeline_id},
    )
    return [PipelineDependencyEdge(**row._mapping) for row in rows]


@dataclass(frozen=True)
class CrossPipelineTaskEdge:
    """One active dependency of a task on a task in another pipeline.

    ``depends_on_label`` names the upstream as ``PIPELINE_CODE.TASK_CODE``.
    """

    task_dependency_id: int
    pipeline_id: int
    depends_on_pipeline_id: int
    depends_on_task_id: int
    depends_on_label: str
    depends_on_project_code: str
    depends_on_pipeline_code: str
    depends_on_task_code: str
    same_project: bool
    consume_repairs: bool = True


def fetch_cross_pipeline_task_edges(conn: Connection, task_id: int) -> list[CrossPipelineTaskEdge]:
    """Return the active dependencies of ``task_id`` on tasks in other pipelines."""
    rows = conn.execute(
        statement(conn, "task_gate_edges").columns(consume_repairs=Boolean, same_project=Boolean),
        {"task_id": task_id},
    )
    return [CrossPipelineTaskEdge(**row._mapping) for row in rows]
