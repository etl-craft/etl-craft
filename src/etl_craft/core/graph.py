"""The same-pipeline task graph: validation, waves, readiness and dead ends.

The graph holds a pipeline's tasks, each with its parsed ``RUN_CONDITION``, and the edges its
condition names inside the pipeline (``CFG_TASK_DEPENDENCY``, derived by ``deploy``). Names of
tasks in other pipelines stay out of the order; the cross-pipeline gate binds them at run time
and hands their facts to the evaluation.

Given each task's state under the active run, the graph answers which tasks can start now
(``ready``) and which never-run tasks can never start (``unsatisfiable``). Conditions are
three-valued: a task starts when its condition is true, is skipped when it is false, and waits
while it is not known. A retry resumes: a task already ``SUCCESS`` or ``SKIPPED`` is never ready
again.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from etl_craft.core.conditions import Condition, Facts, Reading, Ref, Truth, evaluate
from etl_craft.core.enums import (
    NOT_RETRYABLE_STATUSES,
    SETTLED_STATUSES,
    RunStatus,
)
from etl_craft.core.errors import ExitCode, GraphError


class SelfDependencyError(GraphError):
    """A task depends on itself."""

    exit_code = ExitCode.SELF_DEPENDENCY


class CycleError(GraphError):
    """The dependency edges form a cycle, so no order can run them."""

    exit_code = ExitCode.DEPENDENCY_CYCLE

    def __init__(self, cycle: tuple[int, ...]) -> None:
        """Keep the cycle's task ids in the order they were followed."""
        self.cycle = cycle
        super().__init__(f"dependency cycle: {' -> '.join(map(str, cycle))}")


class UnknownTaskError(GraphError):
    """An edge names a task id that is not among the graph's tasks."""

    exit_code = ExitCode.UNKNOWN_TASK


Name = tuple[str, ...]


@dataclass(frozen=True)
class TaskNode:
    """A ``CFG_TASKS`` row, reduced to what the graph needs.

    ``condition`` is the parsed ``RUN_CONDITION`` (``None``: the task starts with its run).
    ``upstream`` maps each name the condition reads in this pipeline to its task id, and
    ``cross`` each name in another pipeline to its ``TASK_DEPENDENCY_ID``.
    """

    task_id: int
    task_code: str | None = None
    condition: Condition | None = None
    upstream: Mapping[Name, int] = field(default_factory=dict)
    cross: Mapping[Name, int] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """``task load_orders`` when the code is known, else ``task_id=12``."""
        return f"task {self.task_code}" if self.task_code else f"task_id={self.task_id}"

    @property
    def rule(self) -> str:
        """The condition as written, or what an empty one means."""
        return self.condition.text if self.condition else "none (starts with its run)"


@dataclass(frozen=True)
class TaskEdge:
    """A same-pipeline ``CFG_TASK_DEPENDENCY`` row: ``task_id`` waits on ``depends_on_task_id``."""

    task_id: int
    depends_on_task_id: int


@dataclass(frozen=True)
class TaskRunState:
    """One task's ``AUD_TASK_RUN_LOG`` row under the active run, as conditions read it.

    ``status`` is ``None`` while the task has no row. Counts are ``None`` where the handler did
    not report them.
    """

    status: str | None = None
    target_count: int | None = None
    rows_written: int | None = None
    source_count: int | None = None
    insert_count: int | None = None
    update_count: int | None = None
    delete_count: int | None = None
    reject_count: int | None = None
    duplicate_count: int | None = None
    attempt_count: int | None = None
    started: datetime | None = None
    ended: datetime | None = None
    error_class: str | None = None
    attempt_status: str | None = None

    def facts(self) -> Facts:
        """Return what a condition can read about this task run."""
        duration = (
            int((self.ended - self.started).total_seconds())
            if self.started is not None and self.ended is not None
            else None
        )
        return Facts(
            str(self.status),
            {
                "SOURCE_ROWS": self.source_count,
                "TARGET_ROWS": self.target_count,
                "ROWS_WRITTEN": self.rows_written,
                "INSERTED": self.insert_count,
                "UPDATED": self.update_count,
                "DELETED": self.delete_count,
                "REJECTED": self.reject_count,
                "DUPLICATES": self.duplicate_count,
            },
            self.attempt_count,
            duration,
            self.error_class,
        )


RunState = Mapping[int, TaskRunState]
"""Each task's state under the active run, by task id; a missing task has not run."""

CrossFacts = Mapping[int, Facts | None]
"""Facts the gate bound for a task's cross-pipeline names, by ``TASK_DEPENDENCY_ID``."""


class DependencyGraph:
    """A validated, immutable same-pipeline task graph; build it with ``build_graph``."""

    def __init__(self, nodes: tuple[TaskNode, ...], edges: tuple[TaskEdge, ...]) -> None:
        """Index the edges by the task that waits on them."""
        self._task_ids = tuple(node.task_id for node in nodes)
        self._nodes_by_id = {node.task_id: node for node in nodes}
        self._dependencies_of: dict[int, list[TaskEdge]] = {t: [] for t in self._task_ids}
        for edge in edges:
            self._dependencies_of[edge.task_id].append(edge)

    @property
    def task_ids(self) -> tuple[int, ...]:
        """The task ids, in the order they were supplied."""
        return self._task_ids

    def node(self, task_id: int) -> TaskNode:
        """Return the task's node."""
        return self._nodes_by_id[task_id]

    def dependencies_of(self, task_id: int) -> list[TaskEdge]:
        """Return the edges ``task_id`` waits on."""
        return list(self._dependencies_of[task_id])

    def downstream_of(self, task_id: int) -> set[int]:
        """Return every task that waits on ``task_id``, directly or through others."""
        found: set[int] = set()
        frontier = {task_id}
        while frontier:
            frontier = {
                edge.task_id
                for edges in self._dependencies_of.values()
                for edge in edges
                if edge.depends_on_task_id in frontier and edge.task_id not in found
            }
            found |= frontier
        return found

    def waves(self) -> list[list[int]]:
        """Return the tasks in static waves: each wave depends only on earlier waves.

        This is the guaranteed-safe order, not the earliest one: a task comes after every
        upstream its condition names, even when an ``OR`` could let it start sooner. ``graph``
        prints it, generated DAGs chain it, and operator repairs use its topological order.
        Task ids within a wave are sorted.
        """
        remaining = set(self._task_ids)
        resolved: set[int] = set()
        result: list[list[int]] = []
        while remaining:
            wave = sorted(
                t
                for t in remaining
                if all(e.depends_on_task_id in resolved for e in self._dependencies_of[t])
            )
            result.append(wave)
            resolved.update(wave)
            remaining.difference_update(wave)
        return result

    def evaluate(
        self,
        task_id: int,
        run_state: RunState,
        cross: CrossFacts | None = None,
        *,
        failures_final: bool = False,
        unknown: frozenset[int] = frozenset(),
        reading: Reading | None = None,
    ) -> Truth:
        """Return the task's condition under ``run_state``; ``True`` when it has none.

        A same-pipeline name is not known while its task has not finished, while a ``FAILED``
        task may still be retried (unless ``failures_final``), or when it is in ``unknown``. A
        cross-pipeline name reads ``cross``, and is not known without it.
        """
        node = self._nodes_by_id[task_id]
        if node.condition is None:
            return True

        def lookup(ref: Ref) -> Facts | None:
            upstream = node.upstream.get(ref.parts)
            if upstream is not None:
                state = run_state.get(upstream, TaskRunState())
                if upstream in unknown or not _final(state, failures_final):
                    return None
                return state.facts()
            dependency = node.cross.get(ref.parts)
            return None if dependency is None or cross is None else cross.get(dependency)

        return evaluate(node.condition, lookup, reading)

    def ready(
        self,
        run_state: RunState,
        cross: Mapping[int, CrossFacts] | None = None,
        *,
        failures_final: bool = False,
    ) -> list[int]:
        """Return the sorted ids of the tasks that can start now, or need their gate checked.

        A task whose status allows another attempt (it has not run, or it ``FAILED``) is ready
        when its condition is true. A task whose condition reads another pipeline is also
        returned, for its gate to bind those names, once every same-pipeline task it names has
        finished, unless ``cross`` already holds its gate's answer.
        """
        bound = cross or {}
        result = []
        for task_id in self._task_ids:
            if run_state.get(task_id, TaskRunState()).status in NOT_RETRYABLE_STATUSES:
                continue
            value = self.evaluate(
                task_id, run_state, bound.get(task_id), failures_final=failures_final
            )
            if value is True or (
                value is None
                and task_id not in bound
                and self._waits_only_on_gate(task_id, run_state, failures_final)
            ):
                result.append(task_id)
        return sorted(result)

    def _waits_only_on_gate(self, task_id: int, run_state: RunState, failures_final: bool) -> bool:
        node = self._nodes_by_id[task_id]
        return bool(node.cross) and all(
            _final(run_state.get(upstream, TaskRunState()), failures_final)
            for upstream in node.upstream.values()
        )

    def unsatisfiable(self, run_state: RunState, *, failures_final: bool = False) -> list[int]:
        """Return the sorted ids of the never-run tasks whose condition can never be true.

        The caller records them ``SKIPPED``. A condition is lost for good when it is false with
        every unknown name still unknown, or when it stays unknown although every same-pipeline
        task it names has settled and it names no other pipeline. A ``FAILED`` task may still
        succeed on a retry, unless ``failures_final`` says no retry will come in this run.
        Skipping a task settles it, which can doom its own dependents, so the search repeats
        until nothing changes. Names in other pipelines always count as still possible.
        """
        known = dict(run_state)
        result: set[int] = set()
        while True:
            newly = [
                task_id
                for task_id in self._task_ids
                if task_id not in result
                and known.get(task_id, TaskRunState()).status is None
                and self._never(task_id, known, failures_final)
            ]
            if not newly:
                return sorted(result)
            for task_id in newly:
                result.add(task_id)
                known[task_id] = TaskRunState(status=RunStatus.SKIPPED)

    def _never(self, task_id: int, run_state: RunState, failures_final: bool) -> bool:
        node = self._nodes_by_id[task_id]
        value = self.evaluate(task_id, run_state, failures_final=failures_final)
        if value is False:
            return True
        return (
            value is None
            and not node.cross
            and all(
                _final(run_state.get(upstream, TaskRunState()), failures_final)
                for upstream in node.upstream.values()
            )
        )

    def admission(self, task_id: int, run_state: RunState, changing: set[int]) -> Truth:
        """Decide the task's condition with the ``changing`` tasks' outcomes not known yet."""
        return self.evaluate(task_id, run_state, unknown=frozenset(changing))


def _final(state: TaskRunState, failures_final: bool) -> bool:
    """Whether a task's outcome under the run is settled for a condition to read."""
    return (
        state.status in SETTLED_STATUSES
        or state.status == RunStatus.CANCELLED
        or (failures_final and state.status == RunStatus.FAILED)
    )


def build_graph(tasks: Sequence[TaskNode], edges: Sequence[TaskEdge]) -> DependencyGraph:
    """Validate ``CFG_`` rows and build their ``DependencyGraph``.

    Raises ``UnknownTaskError`` or ``SelfDependencyError`` for a bad edge, ``GraphError`` for a
    duplicate task, and ``CycleError`` when the edges loop. ``deploy`` refuses these before they
    are stored; the graph checks them again so it is safe to use without one.
    """
    task_ids = tuple(t.task_id for t in tasks)
    task_id_set = set(task_ids)
    if len(task_id_set) != len(task_ids):
        raise GraphError("duplicate task_id in tasks list")
    for edge in edges:
        if edge.task_id not in task_id_set:
            raise UnknownTaskError(f"edge references unknown task_id={edge.task_id}")
        if edge.depends_on_task_id not in task_id_set:
            raise UnknownTaskError(
                f"edge references unknown depends_on_task_id={edge.depends_on_task_id}"
            )
        if edge.task_id == edge.depends_on_task_id:
            label = next(t.label for t in tasks if t.task_id == edge.task_id)
            raise SelfDependencyError(f"{label} depends on itself")
    graph = DependencyGraph(tuple(tasks), tuple(edges))
    _check_acyclic(graph)
    return graph


def _check_acyclic(graph: DependencyGraph) -> None:
    """Raise ``CycleError`` naming a cycle, if the graph has one.

    A depth-first search with an explicit stack, so a dependency chain deeper than Python's
    recursion limit is still checked.
    """
    white, gray, black = 0, 1, 2
    color: dict[int, int] = dict.fromkeys(graph.task_ids, white)

    def upstreams_of(task_id: int) -> Iterator[int]:
        return iter([edge.depends_on_task_id for edge in graph.dependencies_of(task_id)])

    for root in graph.task_ids:
        if color[root] != white:
            continue
        path: list[int] = [root]
        color[root] = gray
        stack: list[tuple[int, Iterator[int]]] = [(root, upstreams_of(root))]
        while stack:
            task_id, pending = stack[-1]
            descended = False
            for upstream in pending:
                if color[upstream] == gray:
                    raise CycleError((*path[path.index(upstream) :], upstream))
                if color[upstream] == white:
                    color[upstream] = gray
                    path.append(upstream)
                    # The frame keeps its iterator, so returning to it resumes the loop here.
                    stack.append((upstream, upstreams_of(upstream)))
                    descended = True
                    break
            if not descended:
                stack.pop()
                path.pop()
                color[task_id] = black


def cycles(edges: set[tuple[str, str]]) -> list[list[str]]:
    """Return each cycle in the ``(dependent, upstream)`` graph once, from its smallest code."""
    graph: dict[str, list[str]] = {}
    for dependent, upstream in sorted(edges):
        graph.setdefault(dependent, []).append(upstream)
    found: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def walk(node: str, path: list[str]) -> None:
        for upstream in graph.get(node, []):
            if upstream in path:
                cycle = path[path.index(upstream) :]
                start = cycle.index(min(cycle))
                key = tuple(cycle[start:] + cycle[:start])
                if key not in seen:
                    seen.add(key)
                    found.append(list(key))
            elif upstream > path[0]:
                walk(upstream, [*path, upstream])

    for node in sorted(graph):
        walk(node, [node])
    return found
