"""Durable scoped control records and the admission fence shared by every agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import BigInteger, bindparam
from sqlalchemy.engine import Connection, Row

from etl_craft.core.actor import current_actor
from etl_craft.core.enums import (
    ControlAcknowledgement,
    ControlAction,
    ControlStatus,
    EndingEvidenceKind,
    RunStatus,
)
from etl_craft.core.errors import ResourceNotFoundError, RunRefusedError
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class ControlAttempt:
    """The process identity and observed query/agent endings of an affected attempt."""

    attempt_id: int
    status: str
    host: str | None
    pid: int | None
    process_start: str | None
    process_ended_at: datetime | None
    queries_ended_at: datetime | None
    owner_id: str | None
    task_id: int
    handler: str


@dataclass(frozen=True)
class ControlView:
    """One accepted request and its actual acknowledgements, independently observable."""

    SCHEMA: ClassVar[str] = "etl-craft/control/1"
    control_id: int
    request_key: str
    pipeline_run_id: int
    pipeline_id: int
    pipeline_code: str
    task_id: int | None
    task_code: str | None
    action: ControlAction
    status: ControlStatus
    attempt_ids: tuple[int, ...]
    requested_by: str
    requested_by_kind: str
    reason: str
    requested_at: datetime
    acknowledged_at: datetime | None
    completed_at: datetime | None
    message: str
    run_status: RunStatus
    attempts: tuple[ControlAttempt, ...]
    execution_run_id: int | None = None

    run_label: str = ""
    execution_run_label: str = ""


def lock_run(conn: Connection, run_id: int) -> None:
    """Serialize admission and control changes against the exact same run row."""
    conn.execute(statement(conn, "control_lock_run"), {"run_id": run_id})


@dataclass(frozen=True)
class DispatchScope:
    """The immutable pipeline, run and task identity at a dispatch boundary."""

    pipeline_id: int
    run_id: int
    task_id: int


def dispatch_policy(
    conn: Connection, run_id: int, task_id: int | None = None
) -> tuple[Row[tuple[object, ...]], ...]:
    """Read scoped fences, pause policy and admitted event permission together."""
    return tuple(
        conn.execute(
            statement(conn, "control_blocked").bindparams(bindparam("task_id", type_=BigInteger)),
            {"run_id": run_id, "task_id": task_id},
        )
    )


def blocked(conn: Connection, run_id: int) -> dict[int | None, ControlAction]:
    """Return each scope whose latest command retains a dispatch fence."""
    return {
        row.task_id: ControlAction(row.action)
        for row in dispatch_policy(conn, run_id)
        if row.action is not None
    }


def _dispatch(
    conn: Connection, scope: DispatchScope, *, wait: bool = False, apply_pause: bool = False
) -> bool:
    """Read policy after locking, before queuing or claiming any attempt."""
    from etl_craft.engine import standing_pauses

    standing_pauses.lock(conn, scope.pipeline_id)
    lock_run(conn, scope.run_id)
    policy = dispatch_policy(conn, scope.run_id, scope.task_id)
    if apply_pause and policy[0].task_paused:
        pause = standing_pauses.at_task(
            conn, scope.pipeline_id, scope.run_id, scope.task_id, datetime.now(UTC)
        )
        if pause is not None:
            standing_pauses.apply(conn, pause, scope.run_id)
            return False
    if policy[0].draining and not policy[0].event_admitted:
        if wait:
            return False
        raise RunRefusedError(
            f"pipeline_run_id={scope.run_id}, task_id={scope.task_id}: pipeline pause is DRAIN; "
            "expected dispatch permission; resume the pipeline or replace its pause with FINISH"
        )
    fences = {row.task_id: row.action for row in policy if row.action is not None}
    action = fences.get(None) or fences.get(scope.task_id)
    if action is not None:
        raise RunRefusedError(
            f"pipeline_run_id={scope.run_id}, task_id={scope.task_id}: "
            f"dispatch is fenced by {action}; "
            "inspect the control request and recover the selected scope after it completes"
        )
    return True


def assert_dispatch(conn: Connection, run_id: int, task_id: int, *, wait: bool = False) -> bool:
    """Refuse even force/retry admissions while the pipeline drains or this scope is stopped."""
    row = conn.execute(statement(conn, "control_run_context"), {"run_id": run_id}).one()
    return _dispatch(conn, DispatchScope(row.pipeline_id, run_id, task_id), wait=wait)


def guard_task(conn: Connection, task_run_id: int) -> None:
    """Fence queuing under a bound task summary."""
    row = conn.execute(
        statement(conn, "control_task_context"), {"task_run_id": task_run_id}
    ).one_or_none()
    if row is not None:
        _dispatch(conn, DispatchScope(row.pipeline_id, row.pipeline_run_id, row.task_id))


def guard_attempt(conn: Connection, attempt_id: int, *, wait: bool = False) -> bool:
    """Apply standing outcomes or fence the queued-to-owned transition before taking a slot."""
    row = conn.execute(
        statement(conn, "control_attempt_context"), {"attempt_id": attempt_id}
    ).one_or_none()
    return row is None or _dispatch(
        conn,
        DispatchScope(row.pipeline_id, row.pipeline_run_id, row.task_id),
        wait=wait,
        apply_pause=True,
    )


def affected(conn: Connection, attempt_ids: tuple[int, ...]) -> tuple[ControlAttempt, ...]:
    """Read pinned attempts; never replace a request's attempts with a newer retry."""
    if not attempt_ids:
        return ()
    query = statement(conn, "control_attempts").bindparams(bindparam("attempt_ids", expanding=True))
    result = []
    for row in conn.execute(query, {"attempt_ids": attempt_ids}):
        values = dict(row._mapping)
        for key in ("process_ended_at", "queries_ended_at"):
            if values[key] is not None:
                values[key] = as_utc(values[key])
        result.append(ControlAttempt(**values))
    return tuple(result)


def get(conn: Connection, control_id: int) -> ControlView:
    """Read a request and its observed evidence, including after its agent disconnects."""
    row = conn.execute(statement(conn, "control_get"), {"control_id": control_id}).one_or_none()
    if row is None:
        raise ResourceNotFoundError(
            f"control_id={control_id}: no request exists; use the id returned by the control action"
        )
    values = dict(row._mapping)
    values["attempt_ids"] = tuple(json.loads(values["attempt_ids"]))
    values["attempts"] = affected(conn, values["attempt_ids"])
    for key in ("requested_at", "acknowledged_at", "completed_at"):
        if values[key] is not None:
            values[key] = as_utc(values[key])
    values["action"] = ControlAction(values["action"])
    values["status"] = ControlStatus(values["status"])
    values["run_status"] = RunStatus(values["run_status"])
    return ControlView(**values)


def observe_exit(
    conn: Connection,
    attempt_id: int,
    *,
    queries_ended: bool,
    evidence: EndingEvidenceKind = EndingEvidenceKind.VERIFIED,
    reason: str = "owning supervisor observed process exit",
    checks: tuple[str, ...] = ("process_exit",),
) -> None:
    """Record physical process exit only after the owning supervisor observed it."""
    kinds = [ControlAcknowledgement.PROCESS]
    if queries_ended:
        kinds.append(ControlAcknowledgement.QUERIES)
    for kind in kinds:
        acknowledge(
            conn,
            attempt_id,
            kind,
            evidence=EndingEvidenceKind.VERIFIED
            if kind == ControlAcknowledgement.QUERIES
            else evidence,
            reason=reason,
            checks=checks,
        )


def acknowledge(
    conn: Connection,
    attempt_id: int,
    kind: ControlAcknowledgement,
    *,
    evidence: EndingEvidenceKind = EndingEvidenceKind.VERIFIED,
    reason: str = "physical ending observed",
    checks: tuple[str, ...] = (),
) -> None:
    """Append one observation without overwriting an earlier acknowledgement."""
    conn.execute(
        statement(conn, "control_observe_exit"),
        {
            "attempt_id": attempt_id,
            "kind": kind,
            "now": datetime.now(UTC),
            "ending_evidence": evidence,
            "actor": current_actor().name,
            "reason": reason,
            "checks": json.dumps(checks),
        },
    )


def update(conn: Connection, control_id: int, status: ControlStatus, message: str) -> None:
    """Advance a request without rewriting its original actor, reason, scope or attempts."""
    from etl_craft.engine import transitions

    now = datetime.now(UTC)
    transitions.update_control(
        conn,
        {
            "control_id": control_id,
            "status": status,
            "message": message,
            "now": now,
            "completed_at": now if status == ControlStatus.COMPLETED else None,
        },
    )


def scope_attempts(
    conn: Connection, run_id: int, task_id: int | None
) -> tuple[ControlAttempt, ...]:
    """Read candidate agents before pinning the exact affected attempt identities."""
    rows = conn.execute(
        statement(conn, "control_scope_attempts"), {"run_id": run_id, "task_id": task_id}
    )
    return tuple(ControlAttempt(**dict(row._mapping)) for row in rows)


def permits_paused(conn: Connection, run_id: int) -> bool:
    """Check one-run permission without changing the definition pause."""
    return bool(
        conn.execute(statement(conn, "control_permits_paused"), {"run_id": run_id}).scalar()
    )


@dataclass(frozen=True)
class EventProbe:
    """The resource key and exact holder of one run's in-flight event check."""

    holder_id: str
    lock_key: int


def event_probes(conn: Connection, run_id: int, task_id: int | None) -> tuple[EventProbe, ...]:
    """Read run-bound holders by event resource key, never scan all resource reservations."""
    from etl_craft.engine.locks import event

    tasks = conn.execute(
        statement(conn, "control_event_tasks"), {"run_id": run_id, "task_id": task_id}
    ).scalars()
    keys = tuple(event(int(task)).key for task in tasks)
    if not keys:
        return ()
    prefix = f"action:e:{run_id:x}:" + (f"{task_id:x}:" if task_id is not None else "")
    query = statement(conn, "control_event_probes").bindparams(bindparam("keys", expanding=True))
    return tuple(
        EventProbe(row.holder_id, row.lock_key)
        for row in conn.execute(query, {"keys": keys})
        if row.holder_id.startswith(prefix)
    )
