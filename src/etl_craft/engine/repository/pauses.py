"""Paused pipelines, in ``AUD_PIPELINE_PAUSES``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, bindparam
from sqlalchemy.engine import Connection

from etl_craft.core.actor import current_actor
from etl_craft.core.enums import ActiveRuns, RunStatus
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project


@dataclass(frozen=True)
class DrainedRun:
    """An admitted run waiting for a pipeline's DRAIN pause to be resumed."""

    pipeline_run_id: int
    run_label: str
    status: RunStatus


@dataclass(frozen=True)
class Pause:
    """A pipeline's open pause: when, who, and why."""

    paused_at: datetime
    paused_by: str
    reason: str
    pipeline_code: str = ""
    active_runs: ActiveRuns = ActiveRuns.DRAIN
    drained_runs: tuple[DrainedRun, ...] = ()

    def describe(self) -> str:
        """Return one line saying since when, by whom and why."""
        return (
            f"paused ({self.active_runs}) since {self.paused_at} by {self.paused_by}: {self.reason}"
        )


def fetch_open_pause(conn: Connection, pipeline_id: int) -> Pause | None:
    """Return the open pause of ``pipeline_id``, or ``None`` when it is not paused."""
    row = conn.execute(
        statement(conn, "open_pipeline_pause"), {"pipeline_id": pipeline_id}
    ).one_or_none()
    if row is None:
        return None
    with selected_project(int(row.project_id)):
        return Pause(
            paused_at=row.paused_at,
            paused_by=row.paused_by,
            reason=row.reason,
            active_runs=row.active_runs,
            drained_runs=_drained(conn, pipeline_id).get(pipeline_id, ()),
        )


def fetch_open_pauses(conn: Connection) -> dict[str, Pause]:
    """Return project-scoped pipeline pause policies and waiting runs in two reads."""
    runs = _drained(conn, None)
    return {
        row.pipeline_code: Pause(
            paused_at=row.paused_at,
            paused_by=row.paused_by,
            reason=row.reason,
            pipeline_code=row.pipeline_code,
            active_runs=row.active_runs,
            drained_runs=runs.get(row.pipeline_id, ()),
        )
        for row in conn.execute(statement(conn, "open_pipeline_pauses"))
    }


def _drained(conn: Connection, pipeline_id: int | None) -> dict[int, tuple[DrainedRun, ...]]:
    """Group exact waiting run identities without querying each paused pipeline."""
    runs: dict[int, list[DrainedRun]] = {}
    for row in conn.execute(
        statement(conn, "pipeline_pause_runs").bindparams(
            bindparam("pipeline_id", type_=BigInteger)
        ),
        {"pipeline_id": pipeline_id},
    ):
        runs.setdefault(row.pipeline_id, []).append(
            DrainedRun(row.pipeline_run_id, row.run_label, row.status)
        )
    return {pipeline: tuple(values) for pipeline, values in runs.items()}


def record_pause(
    conn: Connection,
    pipeline_id: int,
    paused_by: str,
    reason: str,
    *,
    active_runs: ActiveRuns = ActiveRuns.DRAIN,
    now: datetime | None = None,
) -> None:
    """Open a pause of ``pipeline_id``."""
    conn.execute(
        statement(conn, "insert_pipeline_pause"),
        {
            "pipeline_id": pipeline_id,
            "now": now or datetime.now(UTC),
            "active_runs": active_runs,
            "actor_kind": current_actor().kind.value,
            "paused_by": paused_by,
            "reason": reason,
        },
    )


def close_pause(
    conn: Connection,
    pipeline_id: int,
    resumed_by: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Close the open pause of ``pipeline_id``; return whether it had one."""
    result = conn.execute(
        statement(conn, "resume_pipeline_pause"),
        {
            "pipeline_id": pipeline_id,
            "now": now or datetime.now(UTC),
            "actor_kind": current_actor().kind.value,
            "resumed_by": resumed_by,
            "reason": reason,
        },
    )
    return bool(result.rowcount)


@dataclass(frozen=True)
class Resume:
    """A retained resume decision, including its choice and exact created run identities."""

    pause_id: int
    pipeline_id: int
    pipeline_code: str
    task_code: str | None
    resumed_at: datetime
    actor: str | None
    reason: str | None

    def __post_init__(self) -> None:
        """Keep resume history timestamps identical across both Engine DBs."""
        object.__setattr__(self, "resumed_at", as_utc(self.resumed_at))


def resumes(
    conn: Connection, pipeline_id: int | None = None, since: datetime | None = None
) -> tuple[Resume, ...]:
    """Read project-scoped resume history for audit and selected-pipeline explanations."""
    return tuple(
        Resume(**row._mapping)
        for row in conn.execute(
            statement(conn, "pause_resume_history").bindparams(
                bindparam("since", type_=DateTime(timezone=True)),
                bindparam("pipeline_id", type_=BigInteger),
            ),
            {"pipeline_id": pipeline_id, "since": since},
        )
    )
