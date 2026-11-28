"""Attempt identity reads and failure evidence written with lifecycle transitions."""

from dataclasses import asdict, dataclass

from sqlalchemy.engine import Connection

from etl_craft.core.enums import AttemptStatus, FailureClass, RetryOn
from etl_craft.core.error_anchors import ErrorAnchors
from etl_craft.core.errors import StaleTransitionError
from etl_craft.core.failures import Failure
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class ActiveAttempt:
    """Identity and owner of a nonterminal attempt."""

    attempt_id: int
    attempt_number: int
    owner: str | None
    status: str


def active_attempt(conn: Connection, task_run_id: int) -> ActiveAttempt | None:
    """Return the task's nonterminal attempt, if one exists."""
    row = conn.execute(
        statement(conn, "active_attempt"), {"task_run_id": task_run_id}
    ).one_or_none()
    return (
        None
        if row is None
        else ActiveAttempt(int(row.attempt_id), int(row.attempt_number), row.owner_id, row.status)
    )


def record_attempt_failure(
    conn: Connection,
    attempt_id: int,
    failure: Failure,
    *,
    overwrite: bool = True,
    anchors: ErrorAnchors | None = None,
) -> None:
    """Store classification with the ending, using the policy captured at admission."""
    row = conn.execute(
        statement(conn, "attempt_retry_policy"), {"attempt_id": attempt_id}
    ).one_or_none()
    if row is None:
        if not overwrite:
            return
        raise StaleTransitionError(
            f"attempt_id={attempt_id}: missing attempt; expected a live attempt; "
            "refresh the attempt before recording its failure"
        )
    policy = row.retry_on
    result = conn.execute(
        statement(conn, "transition_attempt_failure"),
        {
            **_anchor_values(anchors),
            "attempt_id": attempt_id,
            "overwrite": overwrite,
            "failure_class": failure.kind,
            "failure_source": failure.source,
            "failure_code": failure.code,
            "retryable": policy is not None and RetryOn(policy).permits(failure.kind),
        },
    )

    if overwrite and result.rowcount != 1:
        raise StaleTransitionError(
            f"attempt_id={attempt_id}: failure evidence found no live attempt; "
            "expected QUEUED, CLAIMED or RUNNING; refresh the attempt before recording its outcome"
        )


def _anchor_values(anchors: ErrorAnchors | None) -> dict[str, object]:
    keys = ("sequence", "step", "error_class", "exit_code", "failure_class", "offset", "line")
    values: dict[str, object] = {}
    for prefix in ("first", "last"):
        fields: dict[str, object] = dict.fromkeys(keys)
        if anchors is not None:
            event = anchors.first if prefix == "first" else anchors.last
            position = anchors.first_position if prefix == "first" else anchors.last_position
            fields.update(asdict(event))
            if position is not None and position.sequence == event.sequence:
                fields.update(offset=position.offset, line=position.line)
        values.update({f"{prefix}_{key}": value for key, value in fields.items()})
    return values


def record_attempt_ending(conn: Connection, attempt_id: int, status: str, retryable: bool) -> None:
    """Record failures whose process could not report a more specific exception."""
    if status not in {AttemptStatus.FAILED, AttemptStatus.TIMED_OUT, AttemptStatus.LOST}:
        return
    kind = FailureClass.UNKNOWN if retryable else FailureClass.PERMANENT
    source = "TaskProcess"
    if status == AttemptStatus.TIMED_OUT:
        kind, source = FailureClass.TRANSIENT, "TimeoutError"
    if status == AttemptStatus.LOST:
        kind, source = FailureClass.TRANSIENT, "OwnershipLease"
    record_attempt_failure(conn, attempt_id, Failure(kind, source), overwrite=False)


def set_attempt_retry_policy(
    conn: Connection, attempt_id: int, policy: RetryOn, *, overwrite: bool = True
) -> None:
    """Capture the effective policy before the newly queued attempt can be claimed."""
    result = conn.execute(
        statement(conn, "transition_attempt_retry_policy"),
        {"attempt_id": attempt_id, "retry_on": policy, "overwrite": overwrite},
    )
    if overwrite and result.rowcount != 1:
        raise StaleTransitionError(
            f"attempt_id={attempt_id}: retry policy found no queued attempt; "
            "expected QUEUED; refresh the attempt before admitting execution"
        )
