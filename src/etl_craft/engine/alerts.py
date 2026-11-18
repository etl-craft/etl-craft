"""Run and SLA evidence read for an alert email."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.engine import Connection

from etl_craft.core.definitions import using
from etl_craft.core.enums import SlaStatus
from etl_craft.core.environment import Environment
from etl_craft.core.errors import MetadataError
from etl_craft.core.time import as_utc
from etl_craft.engine.environment import project_environment
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import fetch_pipeline_detail, resolve_pipeline_id
from etl_craft.engine.repository.runs import (
    TaskStatus,
    fetch_latest_pipeline_run,
    fetch_task_statuses_for_run,
)
from etl_craft.engine.runlog import SlaResult, elapsed_hours


@dataclass(frozen=True)
class PipelineDigest:
    """A pipeline's latest run, and its tasks, for the status table."""

    pipeline_code: str
    status: str
    pipeline_run_id: int | None
    start_date: datetime | None
    end_date: datetime | None
    tasks: list[TaskStatus]


def latest_run_of(conn: Connection, pipeline_code: str) -> PipelineDigest:
    """Return a pipeline's latest run; an unknown code is ``UNKNOWN``, one never run ``NEVER_RUN``.

    One wrong code in ``EMAIL_PIPELINES`` shows as its own row rather than losing the report on
    every other pipeline.
    """
    with using(None):
        try:
            pipeline_id = resolve_pipeline_id(conn, pipeline_code)
        except MetadataError:
            return PipelineDigest(pipeline_code, "UNKNOWN", None, None, None, [])
        latest = fetch_latest_pipeline_run(conn, pipeline_id)
        if latest is None:
            return PipelineDigest(pipeline_code, "NEVER_RUN", None, None, None, [])
        tasks = fetch_task_statuses_for_run(conn, pipeline_id, latest.pipeline_run_id)
        return PipelineDigest(
            pipeline_code,
            latest.status,
            latest.pipeline_run_id,
            latest.start_date,
            latest.end_date,
            tasks,
        )


@dataclass(frozen=True)
class AlertState:
    """A source run's report and the requested pipeline digests."""

    statuses: tuple[TaskStatus, ...]
    sla: SlaResult | None
    digests: tuple[PipelineDigest, ...]
    project: str = ""
    environment: Environment | None = None
    run: dict[str, str | int | None] = field(default_factory=dict)


def read_alert(
    conn: Connection,
    pipeline_id: int,
    run_id: int,
    pipelines: str | None,
) -> AlertState:
    """Read the source run and the digest the alert task requests."""
    codes = []
    if pipelines:
        codes = (
            [
                str(code)
                for code in conn.execute(
                    statement(conn, "active_pipeline_codes"), {"project_id": None}
                ).scalars()
            ]
            if pipelines.strip().upper() == "ALL"
            else [code.strip() for code in pipelines.split("|") if code.strip()]
        )
    project, environment = project_environment(conn)
    recorded = conn.execute(statement(conn, "email_run_context"), {"pipeline_run_id": run_id}).one()
    start = as_utc(recorded.start_date)
    end = as_utc(recorded.end_date) if recorded.end_date else None
    sla = None
    hours = fetch_pipeline_detail(conn, pipeline_id).sla_in_hours
    if hours is not None:
        elapsed = elapsed_hours(start, end or datetime.now(UTC))
        if elapsed > hours:
            sla = SlaResult(SlaStatus.BREACHED, hours, elapsed)
    return AlertState(
        tuple(fetch_task_statuses_for_run(conn, pipeline_id, run_id)),
        sla,
        tuple(latest_run_of(conn, code) for code in codes),
        project,
        environment,
        {
            "id": run_id,
            "logical_date": str(recorded.logical_date),
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "duration": f"{((end or datetime.now(UTC)) - start).total_seconds():.2f} seconds",
            "status": recorded.status,
        },
    )
