"""Read the attempt statistics and the bounded duration cohort for one scoped run."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import ClassVar

from sqlalchemy.engine import RowMapping

from etl_craft.core.enums import RunStatus, YesNo
from etl_craft.core.time import elapsed_seconds
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.queries import statement
from etl_craft.engine.run_definitions import read
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import MetricMedian
from etl_craft.services.operations.requests import RunId
from etl_craft.services.operations.snapshots import timestamp


@dataclass(frozen=True)
class AttemptStatistics:
    """Measurements and brief failure evidence recorded for one try."""

    attempt_id: int
    attempt_number: int
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    source_count: int | None
    rows_written: int | None
    reject_count: int | None
    peak_rss_bytes: int | None
    cpu_seconds: float | None
    error_message: str | None
    failure_code: str | None
    exit_name: str | None


@dataclass(frozen=True)
class TaskStatistics:
    """Task status, final-try comparison and ordered attempt measurements."""

    task_code: str
    status: str | None
    handler: str
    error_message: str | None
    duration: MetricMedian
    attempts: tuple[AttemptStatistics, ...]


@dataclass(frozen=True)
class RunStatistics:
    """Statistics from one authorized pipeline run."""

    SCHEMA: ClassVar[str] = "etl-craft/run-statistics/1"
    tasks: tuple[TaskStatistics, ...]


def run_statistics(ctx: OperationContext, request: RunId) -> RunStatistics:
    """Batch both current and historical evidence after run authorization."""
    params = {"run_id": request.run_id, "status": RunStatus.SUCCESS}
    cohorts: dict[int, list[float]] = defaultdict(list)
    with read_snapshot(ctx.engine) as conn:
        definition, _ = read(conn, int(request.run_id))
        rows = conn.execute(statement(conn, "run_statistics"), params).mappings().all()
        for row in conn.execute(statement(conn, "run_statistics_cohort"), params).mappings():
            seconds = elapsed_seconds(timestamp(row.started_at), timestamp(row.ended_at))
            if seconds is not None:
                cohorts[row.task_id].append(seconds)
    by_task: dict[int, list[RowMapping]] = defaultdict(list)
    for row in rows:
        if row.task_id is not None:
            by_task[row.task_id].append(row)
    tasks = []
    for task in definition.rows["CFG_TASKS"]:
        task_id = int(str(task["task_id"]))
        if task["active_flag"] == YesNo.YES and task["pipeline_id"] == rows[0].pipeline_id:
            tasks.append(_task_statistics(task, by_task[task_id], cohorts[task_id]))
    return RunStatistics(tuple(sorted(tasks, key=lambda task: task.task_code)))


def _task_statistics(
    task: dict[str, object], rows: list[RowMapping], sample: list[float]
) -> TaskStatistics:
    attempts = []
    for row in rows:
        if row.attempt_id is None:
            continue
        attempt = dict(row)
        for field in ("started_at", "ended_at"):
            attempt[field] = timestamp(attempt[field])
        for field in ("pipeline_id", "task_id", "task_status", "task_error_message"):
            del attempt[field]
        attempts.append(AttemptStatistics(**attempt))
    return TaskStatistics(
        task_code=str(task["task_code"]),
        handler=str(task["handler"]),
        error_message=rows[0].task_error_message if rows else None,
        status=rows[0].task_status if rows else None,
        duration=MetricMedian(median(sample) if sample else None, len(sample)),
        attempts=tuple(attempts),
    )
