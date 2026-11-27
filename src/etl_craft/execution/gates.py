"""Cross-pipeline dependencies: waiting for the upstream, judging its last run, and trackers.

Pipeline start conditions and cross-pipeline task conditions bind names to fresh output.
An upstream's running run cannot supply facts, and only its latest finished output can bind.
A successful consumer records the outputs selected at admission, with one consumption per bound
edge and revision. Backfills are invisible as upstreams and assume delivery when they consume.

"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, TypeVar

from sqlalchemy.engine import Connection, Engine, Row

from etl_craft.core import interrupts
from etl_craft.core.conditions import (
    Condition,
    Facts,
    Reading,
    Scope,
    Truth,
    describe,
    evaluate,
    is_plain,
    parse,
)
from etl_craft.core.enums import (
    GateOutcome,
    GatePolicy,
    RunStatus,
)
from etl_craft.core.errors import ConditionError
from etl_craft.core.time import as_utc
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.queries import statement
from etl_craft.engine.repository import trackers
from etl_craft.engine.repository.dependencies import (
    PipelineDependencyEdge,
    fetch_cross_pipeline_task_edges,
    fetch_pipeline_dependency_edges,
)
from etl_craft.engine.repository.pipelines import fetch_pipeline_detail
from etl_craft.engine.run_definitions import for_run
from etl_craft.engine.runlog import fetch_task_run_facts

logger = logging.getLogger(__name__)

T = TypeVar("T")


def gates_off(dependency_id: int, *, task: bool) -> trackers.GateDecision:
    """Record a dependency bypassed unchecked because dependency gates are off."""
    return trackers.GateDecision(
        dependency_id, task, None, GateOutcome.BYPASSED, "dependency gates are off"
    )


def judged(satisfied: bool, policy: GatePolicy = GatePolicy.ENFORCE) -> GateOutcome:
    """Return a definitive check's outcome: unsatisfied dependencies are bypassed under warn."""
    if satisfied:
        return GateOutcome.SATISFIED
    return GateOutcome.BYPASSED if policy == GatePolicy.WARN else GateOutcome.UNSATISFIED


FIRST_LOOK_FRACTION = 0.70
"""The first look at a running upstream is at this fraction of its average run length."""

LOOK_FRACTION_STEP = 0.10
"""Each later look is this much more of the average run length."""

MAX_LOOKS = 30
"""How many times one check looks at running upstreams, across all its dependencies."""

WAIT_LIMIT_SECONDS = 3600.0
"""How long one check waits for running upstreams, across all its dependencies, unless
``Orchestration.Gate_wait_minutes`` says otherwise."""

MIN_LOOK_INTERVAL_SECONDS = 1.0
"""The shortest pause between two looks, for an upstream already past its expected length."""

DEFAULT_RUN_SECONDS = 300.0
"""The run length assumed for an upstream with no finished run to average."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Clock:
    """How a check sleeps and reads the time; tests replace both."""

    sleep: Callable[[float], None] = interrupts.sleep
    now: Callable[[], datetime] = _utc_now


@dataclass
class WaitBudget:
    """What is left of one check's waiting: a deadline and a number of looks."""

    deadline: datetime
    looks_left: int = MAX_LOOKS

    @classmethod
    def start(cls, clock: Clock, seconds: float = WAIT_LIMIT_SECONDS) -> WaitBudget:
        """Open a full budget from now, of ``seconds``."""
        return cls(deadline=clock.now() + timedelta(seconds=seconds))

    def exhausted(self, clock: Clock) -> bool:
        """Whether the looks or the time have run out."""
        return self.looks_left <= 0 or clock.now() >= self.deadline


def next_look_delay(
    average_seconds: float, elapsed_seconds: float, fraction: float, remaining_seconds: float
) -> float:
    """Return how long to wait before looking at a running upstream again.

    The look is due when the upstream has run ``fraction`` of its average length; never sooner
    than ``MIN_LOOK_INTERVAL_SECONDS`` from now, and never past the check's deadline.
    """
    delay = max(MIN_LOOK_INTERVAL_SECONDS, average_seconds * fraction - elapsed_seconds)
    return max(0.0, min(delay, remaining_seconds))


def fresh(
    run: trackers.FinishedRun | None,
    last_consumed: trackers.ConsumedRun | int | None,
    *,
    consume_repairs: bool = True,
) -> tuple[int | None, str]:
    """Return the upstream's latest finished run when it is fresh, or ``None`` and why not.

    A higher run id than the last consumed one is new; the same id is new only with a higher
    revision and ``consume_repairs``.
    """
    if run is None:
        return None, "has no finished run"
    if run.revision == 0:
        return (
            None,
            f"run {run.run_id} has no fresh output: SUCCESS was supplied by a standing pause",
        )
    last = (
        trackers.ConsumedRun(last_consumed, 1) if isinstance(last_consumed, int) else last_consumed
    )
    if (
        last is not None
        and run.run_id == last.run_id
        and run.revision > last.revision
        and not consume_repairs
    ):
        return None, (
            f"run {run.run_id} revision {run.revision} is newer than consumed revision "
            f"{last.revision}, but CONSUME_REPAIRS='N'; enable CONSUME_REPAIRS "
            "to accept repairs"
        )
    if last is not None and (
        run.run_id < last.run_id
        or (run.run_id == last.run_id and (not consume_repairs or run.revision <= last.revision))
    ):
        return None, f"has no run since run {last.run_id}, which was already consumed"
    return run.run_id, f"last finished run {run.run_id} ended {run.status}"


def _wait_while_running(
    fetch_latest: Callable[[], trackers.LatestRun | None],
    fetch_average: Callable[[], float | None],
    label: str,
    budget: WaitBudget,
    clock: Clock,
) -> None:
    """Wait while the upstream's latest run is ``IN-PROGRESS``, within ``budget``.

    Each look opens its own short connection, so nothing is held while sleeping.
    """
    latest = fetch_latest()
    if latest is None or latest.status != RunStatus.IN_PROGRESS:
        return
    average = fetch_average() or DEFAULT_RUN_SECONDS
    fraction = FIRST_LOOK_FRACTION
    logger.info("%s is running (run %d); waiting for it to finish", label, latest.run_id)
    while not budget.exhausted(clock):
        now = clock.now()
        start = as_utc(latest.start_date)
        delay = next_look_delay(
            average,
            (now - start).total_seconds(),
            fraction,
            (budget.deadline - now).total_seconds(),
        )
        if delay > 0:
            clock.sleep(delay)
        budget.looks_left -= 1
        fraction += LOOK_FRACTION_STEP
        latest = fetch_latest()
        if latest is None or latest.status != RunStatus.IN_PROGRESS:
            return
    logger.warning("%s is still running; stopped waiting for it", label)


@dataclass(frozen=True)
class CrossPipelineCheck:
    """What a gate bound for a task's names in other pipelines.

    ``facts`` maps each ``TASK_DEPENDENCY_ID`` to the facts of the upstream's fresh output, or
    to ``None`` when it has none, for the task's condition to read. ``consumed`` maps each bound
    dependency to that task run, for the gate to record once the task succeeds. ``definitive``
    is false when the gate did not really check (an upstream is still running), so the task
    waits. ``bypassed`` is true when ``Dependency_gates`` lets the task run whatever the names
    read.
    """

    facts: dict[int, Facts | None] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    consumed: dict[int, int] = field(default_factory=dict)
    definitive: bool = True
    bypassed: bool = False
    decisions: tuple[trackers.GateDecision, ...] = ()
    next_check_at: datetime | None = None


class TrackedGate:
    """The cross-pipeline gate for tasks, backed by ``AUD_DEPENDENCY_CONSUMPTION``."""

    def __init__(
        self,
        clock: Clock | None = None,
        policy: GatePolicy = GatePolicy.ENFORCE,
        wait_seconds: float = WAIT_LIMIT_SECONDS,
    ) -> None:
        """Wait and read the time with ``clock``, and treat what is not satisfied by ``policy``.

        A running upstream is waited for at most ``wait_seconds``.
        """
        self.clock = clock or Clock()
        self.policy = policy
        self.wait_seconds = wait_seconds

    def check(
        self,
        engine: Engine,
        task_id: int,
        *,
        budget: WaitBudget | None = None,
        waiter: Callable[..., datetime | None] | None = None,
    ) -> CrossPipelineCheck:
        """Bind each of the task's names in other pipelines to the upstream's fresh output.

        Under ``off`` nothing is bound and the task runs bypassed; under ``warn`` names are
        bound and a condition they leave unmet is bypassed by the caller.
        """
        with engine.connect() as conn:
            edges = fetch_cross_pipeline_task_edges(conn, task_id)
        if self.policy == GatePolicy.OFF:
            return CrossPipelineCheck(
                reasons=tuple(
                    f"upstream task {edge.depends_on_label} not checked" for edge in edges
                ),
                decisions=tuple(gates_off(edge.task_dependency_id, task=True) for edge in edges),
                bypassed=True,
            )
        budget = budget or WaitBudget.start(self.clock, self.wait_seconds)
        facts: dict[int, Facts | None] = {}
        reasons: list[str] = []
        consumed: dict[int, int] = {}
        decisions: list[trackers.GateDecision] = []
        for edge in edges:
            label = f"upstream task {edge.depends_on_label}"
            next_check = (waiter or _wait_while_running)(
                partial(_read, engine, trackers.fetch_latest_task_run, edge.depends_on_task_id),
                partial(
                    _read, engine, trackers.fetch_average_task_seconds, edge.depends_on_task_id
                ),
                label,
                budget,
                self.clock,
            )
            if next_check is not None:
                return CrossPipelineCheck(definitive=False, next_check_at=next_check)
            with engine.connect() as conn:
                run = trackers.fetch_latest_finished_task_run(conn, edge.depends_on_task_id)
                last = trackers.fetch_task_last_consumed(conn, edge.task_dependency_id)
                run_id, why = fresh(run, last, consume_repairs=edge.consume_repairs)
                bound = None if run_id is None else fetch_task_run_facts(conn, run_id)
            decisions.append(
                trackers.GateDecision(
                    edge.task_dependency_id,
                    True,
                    run,
                    GateOutcome.SATISFIED if run_id is not None else GateOutcome.UNSATISFIED,
                    why,
                )
            )
            facts[edge.task_dependency_id] = None if bound is None else bound.facts()
            if run_id is None:
                reasons.append(f"{label} {why}")
                continue
            logger.info("%s: bound %s", label, why)
            consumed[edge.task_dependency_id] = run_id
        return CrossPipelineCheck(
            facts,
            tuple(reasons),
            consumed,
            bypassed=self.policy == GatePolicy.WARN,
            decisions=tuple(decisions),
        )


def _read(engine: Engine, fetch: Callable[..., T], *args: object) -> T:
    with engine.connect() as conn:
        return fetch(conn, *args)


@dataclass(frozen=True)
class PipelineGateResult:
    """A pipeline's dependencies on other pipelines: the reasons any are unsatisfied."""

    reasons: tuple[str, ...] = ()
    consumed: dict[int, int] = field(default_factory=dict)
    bypassed: tuple[str, ...] = ()
    decisions: tuple[trackers.GateDecision, ...] = ()
    next_check_at: datetime | None = None

    @property
    def satisfied(self) -> bool:
        """Whether every dependency is satisfied."""
        return not self.reasons and self.next_check_at is None


def bind_pipeline(
    conn: Connection, edge: PipelineDependencyEdge, now: datetime
) -> tuple[trackers.LatestRun | trackers.FinishedRun | None, Facts | None, str]:
    """Read the bound output and its facts, or explain why the name is unknown."""
    latest = trackers.fetch_latest_pipeline_run(conn, edge.depends_on_pipeline_id)
    if latest is not None and latest.status == RunStatus.IN_PROGRESS:
        return latest, None, f"run {latest.run_id} is still running"
    run = trackers.fetch_latest_finished_pipeline_run(conn, edge.depends_on_pipeline_id, now)
    last = trackers.fetch_pipeline_last_consumed(conn, edge.pipeline_dependency_id)
    run_id, why = fresh(run, last, consume_repairs=edge.consume_repairs)
    if run_id is None:
        return run, None, why
    return run, trackers.fetch_pipeline_run_facts(conn, run_id), why


def check_pipeline_dependencies(
    engine: Engine,
    pipeline_id: int,
    clock: Clock | None = None,
    policy: GatePolicy = GatePolicy.ENFORCE,
    wait_seconds: float | WaitBudget = WAIT_LIMIT_SECONDS,
    *,
    waiter: Callable[..., datetime | None] | None = None,
    backfill: bool = False,
) -> PipelineGateResult:
    """Bind and evaluate the pipeline's start condition within the gate budget."""
    clock = clock or Clock()
    with read_snapshot(engine) as conn:
        edges = fetch_pipeline_dependency_edges(conn, pipeline_id)
        rule = fetch_pipeline_detail(conn, pipeline_id).start_condition
    if policy == GatePolicy.OFF:
        return PipelineGateResult(
            decisions=tuple(gates_off(edge.pipeline_dependency_id, task=False) for edge in edges),
            bypassed=tuple(
                f"upstream pipeline {edge.depends_on_pipeline_code} not checked" for edge in edges
            ),
        )
    if not rule or not rule.strip():
        return PipelineGateResult()
    budget = (
        wait_seconds
        if isinstance(wait_seconds, WaitBudget)
        else WaitBudget.start(clock, wait_seconds)
    )
    condition = parse(rule, Scope.PIPELINE)
    while True:
        truth, result = _evaluate_start(
            engine, edges, condition, policy, clock.now(), backfill=backfill
        )
        if truth is not None or budget.exhausted(clock) or backfill:
            return result
        next_check = _next_start_check(engine, edges, budget, clock, waiter)
        if waiter is not None:
            return PipelineGateResult(next_check_at=next_check)
        clock.sleep(max(0, (next_check - clock.now()).total_seconds()))
        budget.looks_left -= 1


def _next_start_check(
    engine: Engine,
    edges: list[PipelineDependencyEdge],
    budget: WaitBudget,
    clock: Clock,
    waiter: Callable[..., datetime | None] | None,
) -> datetime:
    now = clock.now()
    candidates = []
    for edge in edges:
        latest = partial(
            _read, engine, trackers.fetch_latest_pipeline_run, edge.depends_on_pipeline_id
        )
        average = partial(
            _read, engine, trackers.fetch_average_pipeline_seconds, edge.depends_on_pipeline_id
        )
        if waiter is not None:
            due = waiter(latest, average, edge.depends_on_pipeline_code, budget, clock)
        else:
            run = latest()
            if run is None or run.status != RunStatus.IN_PROGRESS:
                continue
            delay = next_look_delay(
                average() or DEFAULT_RUN_SECONDS,
                (now - as_utc(run.start_date)).total_seconds(),
                FIRST_LOOK_FRACTION + (MAX_LOOKS - budget.looks_left) * LOOK_FRACTION_STEP,
                (budget.deadline - now).total_seconds(),
            )
            due = now + timedelta(seconds=delay)
        if due is not None:
            candidates.append(due)
    if candidates:
        return min(candidates)
    remaining = (budget.deadline - now).total_seconds()
    interval = max(MIN_LOOK_INTERVAL_SECONDS, remaining / budget.looks_left)
    return min(budget.deadline, now + timedelta(seconds=interval))


def _evaluate_start(
    engine: Engine,
    edges: list[PipelineDependencyEdge],
    condition: Condition,
    policy: GatePolicy,
    now: datetime,
    *,
    backfill: bool,
) -> tuple[Truth, PipelineGateResult]:
    rule = condition.text
    facts: dict[tuple[str, ...], Facts | None] = {}
    decisions: list[trackers.GateDecision] = []
    consumed: dict[int, int] = {}
    reasons: list[str] = []
    with read_snapshot(engine) as conn:
        for edge in edges:
            bound: Facts | None
            if backfill:
                run, bound, why = None, Facts.delivered(), "backfill assumes delivery"
            else:
                observed, bound, why = bind_pipeline(conn, edge, now)
                run = observed if isinstance(observed, trackers.FinishedRun) else None
            facts[edge.qualified_name] = bound
            if edge.same_project:
                facts[(edge.upstream_code,)] = bound
            decisions.append(
                trackers.GateDecision(
                    edge.pipeline_dependency_id, False, run, judged(bound is not None, policy), why
                )
            )
            if run is not None and bound is not None:
                consumed[edge.pipeline_dependency_id] = run.run_id
            if bound is None:
                reasons.append(f"{edge.depends_on_pipeline_code} {why}")
    for ref in condition.refs:
        if ref.parts not in facts:
            raise ConditionError(
                f"START_CONDITION {rule!r} position {ref.position}: value {ref.name!r} "
                "has no derived edge; expected a bound definition; deploy or re-parse the pipeline"
            )
    reading = Reading()
    truth = evaluate(condition, lambda ref: facts[ref.parts], reading)
    reason = f"start condition [{rule}]: {describe(reading)}"
    if reasons:
        reason += f"; {'; '.join(reasons)}"
    if truth is not True:
        decisions = _unmet_start_edges(condition, edges, decisions, reading, policy)
        consumed = {
            edge.pipeline_dependency_id: consumed[edge.pipeline_dependency_id]
            for edge, decision in zip(edges, decisions, strict=True)
            if decision.result == GateOutcome.SATISFIED and edge.pipeline_dependency_id in consumed
        }
    outcome = judged(truth is True, policy)
    decisions.append(
        trackers.GateDecision.evaluated(
            None, rule, json.dumps(reading.values, sort_keys=True), outcome, reason
        )
    )
    return truth, PipelineGateResult(
        reasons=(reason,) if outcome == GateOutcome.UNSATISFIED else (),
        consumed=consumed,
        bypassed=(reason,) if outcome == GateOutcome.BYPASSED else (),
        decisions=tuple(decisions),
    )


def _unmet_start_edges(
    condition: Condition,
    edges: list[PipelineDependencyEdge],
    decisions: list[trackers.GateDecision],
    reading: Reading,
    policy: GatePolicy,
) -> list[trackers.GateDecision]:
    """Keep passing inputs of a plain conjunction when warn admits an unmet condition."""
    plain = is_plain(condition)
    for index, (edge, decision) in enumerate(zip(edges, decisions, strict=True)):
        names = {edge.qualified_name, tuple(edge.depends_on_pipeline_code.split("."))}
        readings = [reading.values[str(ref)] for ref in condition.refs if ref.parts in names]
        if plain and readings and all(value is True for value in readings):
            continue
        decisions[index] = replace(decision, result=judged(False, policy))
    return decisions


@dataclass(frozen=True)
class GateResult:
    """One nonblocking check: final judgement or the next persisted look."""

    state: GateOutcome
    check: CrossPipelineCheck | PipelineGateResult
    next_check_at: datetime | None = None


def check_gate(
    engine: Engine,
    pipeline_run_id: int,
    pipeline_id: int,
    *,
    task_id: int | None = None,
    clock: Clock | None = None,
    policy: GatePolicy = GatePolicy.ENFORCE,
    wait_seconds: float = WAIT_LIMIT_SECONDS,
) -> GateResult:
    """Check without sleeping or holding an agent; resume the run's durable wait budget."""
    clock = clock or Clock()
    now = clock.now()
    params = {"pipeline_run_id": pipeline_run_id, "task_id": task_id}
    with engine.connect() as conn:
        row = conn.execute(statement(conn, "gate_wait"), params).one_or_none()
    waiting = row is not None and row.next_check_at is not None
    first = as_utc(row.first_check_at) if row is not None and waiting else now
    deadline = (
        as_utc(row.wait_until)
        if row is not None and waiting
        else now + timedelta(seconds=wait_seconds)
    )
    looks = row.looks if row is not None and waiting else 0
    due = row is not None and waiting and now >= as_utc(row.next_check_at)
    if due:
        looks += 1
    budget = WaitBudget(deadline, MAX_LOOKS - looks)

    def poll(
        latest_fetch: Callable[[], trackers.LatestRun | None],
        average_fetch: Callable[[], float | None],
        label: str,
        budget: WaitBudget,
        clock: Clock,
    ) -> datetime | None:
        latest = latest_fetch()
        if latest is None or latest.status != RunStatus.IN_PROGRESS or budget.exhausted(clock):
            return None
        if row is not None and waiting and not due:
            return as_utc(row.next_check_at)
        delay = next_look_delay(
            average_fetch() or DEFAULT_RUN_SECONDS,
            (now - as_utc(latest.start_date)).total_seconds(),
            FIRST_LOOK_FRACTION + looks * LOOK_FRACTION_STEP,
            (deadline - now).total_seconds(),
        )
        logger.info("%s: next gate look in %.1fs", label, delay)
        return now + timedelta(seconds=delay)

    check: CrossPipelineCheck | PipelineGateResult
    if task_id is None:
        with for_run(engine, pipeline_run_id):
            check = check_pipeline_dependencies(
                engine, pipeline_id, clock, policy, budget, waiter=poll
            )
    else:
        check = TrackedGate(clock, policy, wait_seconds).check(
            engine, task_id, budget=budget, waiter=poll
        )
    if waiting and not due and check.next_check_at is not None:
        assert row is not None
        check = replace(check, next_check_at=as_utc(row.next_check_at))
    _persist_gate_wait(engine, params, row, first, budget, check.next_check_at)
    # A task's bound names are judged by its condition, which the caller evaluates.
    satisfied = True if isinstance(check, CrossPipelineCheck) else check.satisfied
    return GateResult(
        GateOutcome.WAIT if check.next_check_at is not None else judged(satisfied),
        check,
        check.next_check_at,
    )


def _persist_gate_wait(
    engine: Engine,
    params: dict[str, int | None],
    row: Row[Any] | None,
    first: datetime,
    budget: WaitBudget,
    next_check_at: datetime | None,
) -> None:
    deadline = budget.deadline
    looks = MAX_LOOKS - budget.looks_left
    waiting = row is not None and row.next_check_at is not None
    with engine.begin() as conn:
        if next_check_at is not None and (
            row is None
            or row.next_check_at is None
            or looks != row.looks
            or next_check_at != as_utc(row.next_check_at)
        ):
            conn.execute(
                statement(conn, "save_gate_wait"),
                {
                    **params,
                    "first_check_at": first,
                    "wait_until": deadline,
                    "looks": looks,
                    "next_check_at": next_check_at,
                },
            )
        elif waiting and next_check_at is None:
            conn.execute(
                statement(conn, "finish_gate_wait"), {**params, "looks": min(looks, MAX_LOOKS)}
            )
