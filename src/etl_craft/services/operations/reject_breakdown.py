"""Read reason counts and recorded retention information for the final attempt."""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import ActionName, ActionOutcome, AttemptStatus
from etl_craft.core.errors import HandlerError, ResourceNotFoundError, UsageError
from etl_craft.core.redaction import mask_log
from etl_craft.core.text import is_safe_object_ref, qualify
from etl_craft.dialects.warehouse.retention import reject_breakdown_statement, relation_kind
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import resolve_pipeline_id
from etl_craft.engine.repository.tasks import fetch_task_parameters, resolve_task_id
from etl_craft.engine.run_definitions import for_run
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import AttemptView
from etl_craft.services.operations.requests import TaskSelection
from etl_craft.services.operations.snapshots import task_run_view, timestamp
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect


@dataclass(frozen=True)
class RejectReason:
    """One recorded reason and its row count."""

    reason: str
    count: int


@dataclass(frozen=True)
class RejectBreakdown:
    """Retained aggregate evidence with the latest confirmed target retention date."""

    SCHEMA: ClassVar[str] = "etl-craft/reject-breakdown/1"
    recorded_count: int
    reject_table: str | None = None
    rows: tuple[RejectReason, ...] = ()
    retention_removed_at: datetime | None = None


def reject_breakdown(ctx: OperationContext, request: TaskSelection) -> RejectBreakdown:
    """Read only the final attempt and the target pinned when the run was admitted."""
    if not isinstance(request.run_id, int):
        raise UsageError("Reject breakdown requires an exact run id; open Statistics on a run")
    with read_snapshot(ctx.engine) as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        present = conn.execute(
            statement(conn, "api_run_code"), {"run_id": request.run_id}
        ).scalar_one_or_none()
        if present != request.pipeline_code:
            raise ResourceNotFoundError(
                f"run {request.run_id}: expected a run of {request.pipeline_code}; "
                "open a run of this pipeline"
            )
        with for_run(conn, request.run_id):
            task_id = resolve_task_id(conn, pipeline_id, request.task_code)
            task = task_run_view(conn, pipeline_id, pipeline_run_id=request.run_id, task_id=task_id)
            if not task or not task.attempts:
                return RejectBreakdown(0)
            attempt = task.attempts[-1]
            count = attempt.reject_count
            if not count or attempt.status in {
                AttemptStatus.QUEUED,
                AttemptStatus.CLAIMED,
                AttemptStatus.RUNNING,
            }:
                return RejectBreakdown(0)
            target = fetch_task_parameters(conn, task_id).get("TARGET_OBJECT")
    if not target:
        return RejectBreakdown(count)
    if not is_safe_object_ref(target):
        raise HandlerError(
            f"TARGET_OBJECT={target!r}: expected a safe qualified table; fix metadata"
        )
    target = qualify(target, active_catalog(ctx.config))
    if not is_safe_object_ref(target):
        raise HandlerError(
            f"Target {target!r}: expected safe identifiers; fix warehouse configuration"
        )
    table = f"{target}__rejects"
    rows = _reasons(ctx, attempt, table)
    if rows or task.end_date is None:
        return RejectBreakdown(count, table, rows)
    with read_snapshot(ctx.engine) as conn:
        removal = _retention_removal(conn, ctx, target, table, task.end_date)
    return RejectBreakdown(count, table, retention_removed_at=removal)


def _reasons(ctx: OperationContext, attempt: AttemptView, table: str) -> tuple[RejectReason, ...]:
    try:
        with open_warehouse(ctx.config) as warehouse, warehouse.connect() as conn:
            if relation_kind(warehouse_dialect(ctx.config), conn, table) is None:
                return ()
            query = reject_breakdown_statement(table)
            rows = conn.execute(
                query,
                {
                    "pipeline_id": attempt.pipeline_id,
                    "run_id": attempt.pipeline_run_id,
                    "task_run_id": attempt.task_run_id,
                },
            )
            return tuple(RejectReason(mask_log(row.reason), row._mapping["count"]) for row in rows)
    except SQLAlchemyError as error:
        raise HandlerError(
            f"{table}: could not read reject reasons ({type(error).__name__}); "
            "check warehouse access and retry the breakdown"
        ) from error


def _retention_removal(
    conn: Connection, ctx: OperationContext, target: str, table: str, ended_at: datetime
) -> datetime | None:
    return timestamp(
        conn.execute(
            statement(conn, "reject_retention_removal"),
            {
                "project_id": ctx.project_id,
                "target_name": target,
                "reject_table": table,
                "ended_at": ended_at,
                "command": ActionName.PURGE,
                "outcome": ActionOutcome.SUCCESS,
            },
        ).scalar_one_or_none()
    )
