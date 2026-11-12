"""Permission-filtered delivery facts; secret references are not part of the result."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam
from sqlalchemy.engine import Connection

from etl_craft.core.alerts import AlertStatus
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class AlertDelivery:
    """The bounded public history of one admitted event or delivery attempt."""

    delivery_id: int
    channel: str
    pipeline_code: str
    source_run_id: int
    source_run_label: str
    alert_run_id: int
    alert_run_label: str
    trigger: str
    attempt_number: int
    status: AlertStatus
    status_code: int | None
    error_class: str | None
    created_at: datetime


def history(conn: Connection, project_id: int, codes: tuple[str, ...]) -> tuple[AlertDelivery, ...]:
    """Filter by authorized pipeline codes before selecting the newest hundred records."""
    if not codes:
        return ()
    query = statement(conn, "alert_delivery_history").bindparams(
        bindparam("pipeline_codes", expanding=True)
    )
    rows = conn.execute(query, {"project_id": project_id, "pipeline_codes": codes})
    return tuple(
        AlertDelivery(
            **{
                **row._mapping,
                "status": AlertStatus(row.status),
                "created_at": as_utc(row.created_at),
            }
        )
        for row in rows
    )
