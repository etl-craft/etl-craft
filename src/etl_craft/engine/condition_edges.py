"""Derive ``CFG_TASK_DEPENDENCY`` from each task's ``RUN_CONDITION``.

A task's condition names the tasks it waits on; ``deploy`` and re-parse write those names as
edges, which the scheduler, gates, graphs and catalog read. A team never writes an edge. An edge
keeps its id while a condition names it, so the consumption it records continues across
deploys; an edge no condition names any more is deactivated, never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from itertools import pairwise

from sqlalchemy.engine import Connection

from etl_craft.core.conditions import Condition, Ref, Scope, parse
from etl_craft.core.errors import ConditionError
from etl_craft.core.text import suggest
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class ConditionTask:
    """A task of the project being derived, with its parsed condition."""

    task_id: int
    pipeline_id: int
    project_code: str
    pipeline_code: str
    task_code: str
    condition: Condition | None

    @property
    def label(self) -> str:
        """``PIPELINE.task``, as files and messages name a task."""
        return f"{self.pipeline_code}.{self.task_code}"


def project_tasks(conn: Connection, project_id: int) -> list[ConditionTask]:
    """Read the project's active tasks and parse each condition, naming the task on failure."""
    tasks = []
    for row in conn.execute(statement(conn, "condition_tasks"), {"project_id": project_id}):
        if not row.active:
            continue
        text = (row.run_condition or "").strip()
        label = f"{row.pipeline_code}.{row.task_code}"
        try:
            condition = parse(text, Scope.TASK) if text else None
        except ConditionError as error:
            raise ConditionError(
                f"{label} RUN_CONDITION {error}; correct the condition and deploy"
            ) from error
        tasks.append(
            ConditionTask(
                int(row.task_id),
                int(row.pipeline_id),
                row.project_code,
                row.pipeline_code,
                row.task_code,
                condition,
            )
        )
    return tasks


def resolve(
    conn: Connection, task: ConditionTask, ref: Ref, by_code: dict[tuple[str, str], ConditionTask]
) -> tuple[int, int]:
    """Return ``(pipeline_id, task_id)`` for one name; ``ConditionError`` names what is missing."""
    parts = ref.parts
    where = f"{task.label} RUN_CONDITION position {ref.position}"
    if len(parts) == 3:
        found = conn.execute(
            statement(conn, "config_dependency_target"),
            {"project_code": parts[0], "pipeline_code": parts[1], "task_code": parts[2]},
        ).one_or_none()
        if found is None or found.task_id is None:
            raise ConditionError(
                f"{where}: value {ref.name!r}; expected an active task of an active pipeline and "
                "project; apply that project's definitions first or correct the name"
            )
        _refuse_self(task, ref, int(found.task_id))
        return int(found.pipeline_id), int(found.task_id)
    key = (task.pipeline_code, parts[0]) if len(parts) == 1 else (parts[0], parts[1])
    upstream = by_code.get(key)
    if upstream is None:
        known = [code for pipeline, code in by_code if pipeline == key[0]]
        hint = suggest(key[1], known)
        did = f"; did you mean {hint[0]}?" if hint else ""
        raise ConditionError(
            f"{where}: value {ref.name!r}; expected an active task of pipeline {key[0]}{did}; "
            "correct the task or pipeline name and deploy"
        )
    _refuse_self(task, ref, upstream.task_id)
    return upstream.pipeline_id, upstream.task_id


def _refuse_self(task: ConditionTask, ref: Ref, upstream_id: int) -> None:
    if upstream_id == task.task_id:
        raise ConditionError(
            f"{task.label} RUN_CONDITION position {ref.position}: value {ref.name!r} names "
            "this task; expected another task; remove the self-reference and deploy"
        )


def _wanted(conn: Connection, project_id: int) -> dict[tuple[int, int], tuple[int, int]]:
    """Map ``(task, upstream)`` to ``(pipeline, upstream pipeline)`` for every named task."""
    tasks = project_tasks(conn, project_id)
    by_code = {(t.pipeline_code, t.task_code): t for t in tasks}
    wanted: dict[tuple[int, int], tuple[int, int]] = {}
    for task in tasks:
        if task.condition is None:
            continue
        for ref in task.condition.refs:
            pipeline_id, upstream = resolve(conn, task, ref, by_code)
            wanted[(task.task_id, upstream)] = (task.pipeline_id, pipeline_id)
    _refuse_cycles(conn, project_id, tasks, wanted)
    return wanted


def _refuse_cycles(
    conn: Connection,
    project_id: int,
    tasks: list[ConditionTask],
    wanted: dict[tuple[int, int], tuple[int, int]],
) -> None:
    """Refuse names that close a loop, within a pipeline or through other pipelines and projects.

    Every task on a loop waits on the next, so none of them could ever start; a loop through
    other pipelines would only ever read each other's previous output.
    """
    labels = {t.task_id: f"{t.project_code}.{t.pipeline_code}.{t.task_code}" for t in tasks}
    edges = {
        (labels[task], labels.get(upstream) or _label(conn, upstream)) for task, upstream in wanted
    }
    edges |= {
        (row.task_label, row.upstream_label)
        for row in conn.execute(
            statement(conn, "condition_edges_elsewhere"), {"project_id": project_id}
        )
    }
    graph: dict[str, set[str]] = {}
    for task, upstream in edges:
        graph.setdefault(task, set()).add(upstream)
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as error:
        cycle = tuple(reversed(error.args[1][:-1]))
        start = min(range(len(cycle)), key=cycle.__getitem__)
        loop = (*cycle[start:], *cycle[:start], cycle[start])
        local = {labels[task.task_id]: task for task in tasks}
        pair = next(((a, b) for a, b in pairwise(loop) if a in local), None)
        where = "RUN_CONDITION"
        if pair is not None:
            source = local[pair[0]]
            assert source.condition is not None
            target = tuple(pair[1].split("."))
            ref = next(
                ref for ref in source.condition.refs if target[-len(ref.parts) :] == ref.parts
            )
            where = f"{source.label} RUN_CONDITION position {ref.position}"
        raise ConditionError(
            f"{where}: names form a cycle: "
            f"value {' -> '.join(loop)}; expected each task to wait "
            "only on tasks that do not wait on it; remove one of these names"
        ) from error


def _label(conn: Connection, task_id: int) -> str:
    row = conn.execute(statement(conn, "condition_task_label"), {"task_id": task_id}).one()
    return str(row.label)


def problem(conn: Connection, project_id: int) -> str | None:
    """Return the first condition that does not parse or names an unknown task, without writing."""
    try:
        _wanted(conn, project_id)
    except ConditionError as error:
        return str(error)
    return None


def derive_edges(conn: Connection, project_id: int) -> int:
    """Write the edges every active task's condition names; return how many changed."""
    wanted = _wanted(conn, project_id)
    changed = 0
    existing = {
        (int(row.task_id), int(row.depends_on_task_id)): row
        for row in conn.execute(statement(conn, "condition_edges"), {"project_id": project_id})
    }
    for key, row in existing.items():
        flag = "Y" if key in wanted else "N"
        if row.active_flag != flag:
            conn.execute(
                statement(conn, "condition_edge_activate"),
                {"task_dependency_id": int(row.task_dependency_id), "active_flag": flag},
            )
            changed += 1
    for (task_id, upstream), (pipeline_id, upstream_pipeline) in wanted.items():
        if (task_id, upstream) not in existing:
            conn.execute(
                statement(conn, "condition_edge_insert"),
                {
                    "pipeline_id": pipeline_id,
                    "task_id": task_id,
                    "depends_on_pipeline_id": upstream_pipeline,
                    "depends_on_task_id": upstream,
                },
            )
            changed += 1
    return changed
