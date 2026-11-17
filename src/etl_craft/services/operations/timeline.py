"""A run's recorded queue, wait and execution intervals, read from the audit tables."""

from collections.abc import Iterator, Sequence
from datetime import datetime

from sqlalchemy.engine import Connection, Row

from etl_craft.core.enums import FINISHED_RUN_STATUSES, AttemptStatus, RunStatus, WaitKind
from etl_craft.core.enums_timeline import TimelineKind, WaitOutcome
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement
from etl_craft.services.operations.models import TimelineSegment

WAIT_KINDS = {
    WaitKind.DEPENDENCY: TimelineKind.GATE,
    WaitKind.EVENT: TimelineKind.EVENT,
    WaitKind.PIPELINE_RUN: TimelineKind.CHILD_RUN,
}


def run_timeline(conn: Connection, run_id: int) -> tuple[TimelineSegment, ...]:
    """Read only recorded rows: nothing is inferred from gaps or from current configuration."""
    attempts = conn.execute(statement(conn, "run_timeline_attempts"), {"run_id": run_id}).all()
    waits = conn.execute(statement(conn, "run_timeline_waits"), {"run_id": run_id}).all()
    segments = [*_attempts(attempts), *(_wait(row) for row in waits)]
    return tuple(sorted(segments, key=lambda s: (s.started_at, s.task_code or "")))


def _attempts(rows: Sequence[Row[tuple[object, ...]]]) -> Iterator[TimelineSegment]:
    for row in rows:
        status = AttemptStatus(row.status)
        started = None if row.started_at is None else as_utc(row.started_at)
        ended = None if row.ended_at is None else as_utc(row.ended_at)
        if row.queued_at is not None:
            queue_end = started or (None if status == AttemptStatus.QUEUED else ended)
            yield TimelineSegment(
                row.task_code,
                TimelineKind.QUEUE,
                as_utc(row.queued_at),
                queue_end,
                status,
                int(row.attempt_number),
            )
        if started is not None:
            yield TimelineSegment(
                row.task_code,
                TimelineKind.EXECUTION,
                started,
                ended,
                status,
                int(row.attempt_number),
            )


def _wait(row: Row[tuple[object, ...]]) -> TimelineSegment:
    kind = WAIT_KINDS[WaitKind(row.wait_kind)]
    deadline = None if row.deadline is None else as_utc(row.deadline)
    ended, outcome = _gate_end(row, deadline) if kind == TimelineKind.GATE else _task_end(row)
    if outcome is None:
        outcome = WaitOutcome.OPEN if row.next_check_at is not None else WaitOutcome.ENDED
    return TimelineSegment(
        row.task_code, kind, as_utc(row.started_at), ended, outcome, deadline=deadline
    )


def _gate_end(
    row: Row[tuple[object, ...]], deadline: datetime | None
) -> tuple[datetime | None, WaitOutcome | None]:
    """End a gate at its last recorded decision; a refusal at the deadline is a timeout."""
    if row.decided_at is None or row.next_check_at is not None:
        return None, None
    decided = as_utc(row.decided_at)
    if row.refused:
        late = deadline is not None and decided >= deadline
        return decided, WaitOutcome.TIMED_OUT if late else WaitOutcome.REFUSED
    return decided, WaitOutcome.BYPASSED if row.bypassed else WaitOutcome.SATISFIED


def _task_end(row: Row[tuple[object, ...]]) -> tuple[datetime | None, WaitOutcome | None]:
    """End event and child-run waits with their task's recorded run."""
    if row.task_status is None or RunStatus(row.task_status) not in FINISHED_RUN_STATUSES:
        return None, None
    ended = None if row.task_ended_at is None else as_utc(row.task_ended_at)
    status = RunStatus(row.task_status)
    if status == RunStatus.SUCCESS:
        return ended, WaitOutcome.SATISFIED
    return ended, WaitOutcome.TIMED_OUT if status == RunStatus.SKIPPED else WaitOutcome.REFUSED
