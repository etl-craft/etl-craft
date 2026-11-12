"""Safe append-only facts for event-bound alert runs."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.engine import Connection

from etl_craft.core.actor import current_actor
from etl_craft.core.alerts import AlertStatus
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class AlertEvent:
    """The source event never changes when an alert run is retried."""

    source_run_id: int
    channel_id: int
    event_id: str
    trigger: str
    source_task_id: int | None = None
    source_attempt_id: int | None = None


def event(conn: Connection, run_id: int) -> AlertEvent | None:
    """Recognize only a recorded admission, never an operator-supplied run-key prefix."""
    row = conn.execute(statement(conn, "alert_run"), {"run_id": run_id}).one_or_none()
    return None if row is None else AlertEvent(**row._mapping)


@dataclass(frozen=True)
class DeliveryAttempt:
    """One bounded send's non-secret observations."""

    number: int = 1
    task_run_id: int | None = None
    status_code: int | None = None
    error_class: str | None = None


DEFAULT_ATTEMPT = DeliveryAttempt()


def append(
    conn: Connection,
    run_id: int,
    source: AlertEvent,
    status: AlertStatus,
    attempt: DeliveryAttempt = DEFAULT_ATTEMPT,
) -> None:
    """Store only controlled status/error classes; callers never supply network text."""
    actor = current_actor()
    conn.execute(
        statement(conn, "alert_delivery_insert"),
        {
            **source.__dict__,
            "run_id": run_id,
            "task_run_id": attempt.task_run_id,
            "status": status,
            "attempt_number": attempt.number,
            "status_code": attempt.status_code,
            "error_class": attempt.error_class,
            "actor": actor.name,
            "actor_kind": actor.kind,
            "now": datetime.now(UTC),
        },
    )
