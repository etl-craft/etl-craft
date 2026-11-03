"""Authenticated SCD edits, integrations, provenance and explicit human unlocks."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import ClassVar

from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import ActionName, ActorKind, Handler
from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.errors import PermissionDeniedError, SqlGuardError, UsageError
from etl_craft.core.governance import check_reason
from etl_craft.core.redaction import mask_text, registering
from etl_craft.core.time import as_utc
from etl_craft.engine import locks
from etl_craft.engine.repository.pipelines import resolve_pipeline_id
from etl_craft.engine.repository.tasks import (
    conflicting_merge_action,
    fetch_task_execution_detail,
    fetch_task_parameters,
    resolve_task_id,
)
from etl_craft.engine.task_store import LocalTaskStore
from etl_craft.handlers.protection_recovery import committed, recover
from etl_craft.handlers.registry import TaskContext, task_store
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.actions import ACTIONS
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.protection import (
    MERGES,
    Protection,
    ProtectionRequest,
    exists,
    refuse_legacy,
)
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.spec import read_sql_task
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.recording import recorded
from etl_craft.services.operations.requests import Request
from etl_craft.warehouse.connection import open_warehouse, task_warehouse_dialect


@dataclass(frozen=True, kw_only=True)
class ValueKey(Request):
    """One exact business key of a SQL task's target, cast by the warehouse's declared types."""

    pipeline_code: str
    task_code: str
    key: dict[str, object] = field(repr=False, metadata={"audit": False})


@dataclass(frozen=True, kw_only=True)
class ValueEdit(ValueKey):
    """Explicit values for one key; omitted existing values are retained."""

    values: dict[str, object] = field(repr=False, metadata={"audit": False})
    reason: str = field(default="", repr=False, metadata={"audit": False})
    row_lock: bool = False


@dataclass(frozen=True, kw_only=True)
class ValueUnlock(ValueKey):
    """An explicit release; no columns means all active locks on the selected key."""

    reason: str = field(default="", repr=False, metadata={"audit": False})
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueResult:
    """Latest value attribution and locks, with bounded immutable operation evidence."""

    SCHEMA: ClassVar[str] = "etl-craft/scd-values/1"
    target: str
    enabled: bool
    request_id: str | None
    records: tuple[dict[str, object], ...]
    history: tuple[dict[str, object], ...]


def _task_context(ctx: OperationContext, pipeline: str, task: str) -> TaskContext:
    """Resolve a definition without creating or selecting an execution run."""
    with ctx.engine.connect() as conn:
        pipeline_id = resolve_pipeline_id(conn, pipeline)
        task_id = resolve_task_id(conn, pipeline_id, task)
        detail = fetch_task_execution_detail(conn, task_id)
        params = fetch_task_parameters(conn, task_id)
    if detail.handler != Handler.SQL:
        raise UsageError(
            f"{pipeline}/{task}: HANDLER={detail.handler}; expected SQL SCD1/SCD2; "
            "select a merge task"
        )
    return TaskContext(
        ctx.config,
        pipeline_id,
        pipeline,
        task_id,
        task,
        0,
        0,
        0,
        detail.handler,
        detail.refresh_type,
        params,
    )


@contextmanager
def _selected(
    ctx: OperationContext, pipeline: str, task: str
) -> Iterator[tuple[Protection, TaskContext]]:
    """Share engine ownership, single-writer access and atomic warehouse transactions with ETL."""
    context = _task_context(ctx, pipeline, task)
    spec = read_sql_task(context)
    if spec.action not in MERGES:
        raise UsageError(
            f"{pipeline}/{task}: SQL_ACTION={spec.action}; expected SCD1_MERGE or SCD2_MERGE; "
            "select a merge task"
        )
    with ctx.engine.connect() as conn:
        other = conflicting_merge_action(conn, context.task_id, spec.action)
    if other is not None:
        raise SqlGuardError(
            f"{spec.target_object}: {spec.action} conflicts with an active {other} writer; "
            "give the target one merge action before editing"
        )
    catalog = active_catalog(ctx.config)
    locker = LocalLocker(ctx.engine, ctx.config)
    store = LocalTaskStore.standalone(ctx.engine, ctx.config, locker)
    with (
        locks.target(spec.target_object, catalog).hold(locker),
        open_warehouse(ctx.config, locker) as warehouse,
    ):
        with warehouse.begin() as conn:
            session = Session(
                conn,
                task_warehouse_dialect(ctx.config, context.task_params),
                catalog=catalog,
                action=spec.action,
                target_object=spec.target_object,
                task_run_id=0,
                params=context.task_params,
            )
            session.protection_store = store
            refuse_legacy(session)
            recover(session, store)
            guard = Protection(session, spec)
            guard.acquire()
            try:
                yield guard, context
            finally:
                session.sweep()
        committed(store, session.target, session.protection_requests)


def _validate_input(guard: Protection, key: Mapping[str, object]) -> None:
    """Require the exact stable business key and bound scalar values."""
    if set(key) != set(guard.task.merge_key) or any(value is None for value in key.values()):
        raise UsageError(
            f"{guard.session.target}: key columns={tuple(key)}; expected non-NULL values for "
            f"{guard.task.merge_key}; supply exactly those business-key columns"
        )
    _validate_scalars(key)


def _validate_scalars(values: Mapping[str, object]) -> None:
    """Refuse structured and non-finite values before they reach a driver."""
    for column, value in values.items():
        if (value is not None and not isinstance(value, (str, int, float, bool))) or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            raise UsageError(
                f"column {column!r}: value type={type(value).__name__}; expected a finite scalar "
                "or NULL; encode dates/times as ISO strings and supply individual column values"
            )


def _key_row(guard: Protection, key: Mapping[str, object]) -> dict[str, object] | None:
    """Read one latest business-key version, including a deleted row awaiting revival."""
    _validate_input(guard, key)
    params = {f"key_{i}": value for i, value in enumerate(key.values())}
    types = guard.session.column_types(guard.session.target)
    predicate = " AND ".join(
        f"t.{column} = CAST(:key_{i} AS {types[column.lower()]})" for i, column in enumerate(key)
    )
    rows = (
        guard.session.run(
            f"SELECT t.* FROM ({guard.sql.current()}) t WHERE {predicate}",
            params,
            step="select the business key",
        )
        .mappings()
        .all()
    )
    return None if not rows else {k.lower(): v for k, v in rows[0].items()}


def _edit_stage(guard: Protection, edit: ValueEdit) -> tuple[str, str]:
    """Stage an exact row using declared warehouse types and bound input values."""
    s = guard.session
    previous = _key_row(guard, edit.key)
    unknown = set(edit.values) - set(guard.business)
    if unknown or set(edit.values) & set(guard.task.merge_key):
        raise UsageError(
            f"{s.target}: edit columns={tuple(edit.values)}; expected business columns other "
            f"than {guard.task.merge_key}; remove unknown, managed and key columns"
        )
    _validate_scalars(edit.values)
    values = {**(previous or {}), **edit.key, **edit.values}
    missing = set(guard.business) - set(values)
    if missing or not edit.values:
        raise UsageError(
            f"{s.target}: missing insert columns={sorted(missing)}, "
            f"edit columns={tuple(edit.values)}; "
            "supply at least one value and every business column for a new key"
        )
    types = s.column_types(s.target)
    columns = (*guard.business, *(("upload_id",) if "upload_id" in types else ()))
    values.setdefault("upload_id", None)
    stage = s.scratch("edit")
    names = ", ".join(columns)
    s.create_scratch(stage, f"SELECT {names} FROM {s.target} WHERE 1 = 0", step="stage an edit")
    expressions = ", ".join(
        f"CAST(:value_{i} AS {types[c.lower()]})" for i, c in enumerate(columns)
    )
    s.run(
        f"INSERT INTO {stage} ({names}) SELECT {expressions}",
        {f"value_{i}": values[c] for i, c in enumerate(columns)},
        step="bind edited values",
    )
    key_hash = str(
        s.run(
            f"SELECT {guard.sql.key_hash} AS key_hash FROM {stage} t", step="identify edited key"
        ).scalar_one()
    )
    return stage, key_hash


def _result(
    ctx: OperationContext, guard: Protection, key_hash: str, request_id: str | None
) -> ValueResult:
    """Return current attribution and the last hundred events for exactly this key."""
    from etl_craft.core.privacy import PrivacyDomain, fingerprint
    from etl_craft.engine.privacy import check

    with ctx.engine.connect() as conn:
        privacy_key = check(conn, ctx.config)
    assert privacy_key is not None
    from etl_craft.engine.protection_events import target_identity

    private_target = target_identity(ctx.config, guard.session.target)[0]
    private_key = fingerprint(privacy_key, PrivacyDomain.KEY, private_target, key_hash)
    guard.refresh(key_hash)
    state = guard.states.get(key_hash)
    current = (
        ()
        if state is None
        else tuple(
            {
                **cell,
                "key_hash": private_key,
                "value_hash": None
                if cell.get("value_hash") is None
                else fingerprint(
                    privacy_key, PrivacyDomain.VALUE, private_target, str(cell["value_hash"]), name
                ),
                "column_name": name,
                "happened_at": as_utc(cell["happened_at"]) if cell.get("happened_at") else None,
            }
            for name, cell in sorted(state.cells.items())
        )
    )
    return ValueResult(
        guard.session.target,
        True,
        request_id,
        current,
        _history(ctx, guard, private_target, private_key),
    )


def _history(
    ctx: OperationContext, guard: Protection, private_target: str, private_key: str
) -> tuple[dict[str, object], ...]:
    """Keep physical-row maintenance events out of business-key attribution."""
    store = guard.session.protection_store
    assert store is not None
    history: list[dict[str, object]] = []
    from etl_craft.engine.protection_events import history as event_history

    with ctx.engine.connect() as conn:
        recent = event_history(
            conn,
            private_target,
            private_key,
            guard.request_id,
        )
    for record in recent:
        event = record.event
        if (
            event is None
            or event.key_hash != private_key
            or event.kind == ProtectionKind.REHASH
            or (
                event.kind
                in {ProtectionKind.KEY, ProtectionKind.ERASURE, ProtectionKind.HARD_DELETE}
                and event.columns != guard.key_columns
            )
        ):
            continue
        for column, hashed in zip(event.columns, event.value_hashes, strict=True):
            history.append(
                {
                    "key_hash": private_key,
                    "column_name": column,
                    "value_hash": hashed,
                    "event_kind": event.kind,
                    "actor": record.uploader or record.created_by,
                    "upload_id": record.upload_id,
                    "reason": (
                        f"upload {record.upload_id}: LOCKED=false"
                        if record.upload_id is not None and event.kind == ProtectionKind.UNLOCK
                        else f"upload {record.upload_id}"
                        if record.upload_id is not None
                        else None
                    ),
                    "happened_at": as_utc(record.created_at),
                    "request_id": record.request_id,
                    "revision": record.event_id,
                }
            )
    return tuple(history[:100])


def write_values(ctx: OperationContext, edit: ValueEdit) -> ValueResult:
    """Apply an admin's edit or authenticated integration write with accurate attribution.

    The command audit names columns, never values; the intent log owns its request id.
    """
    pipeline, task = edit.pipeline_code, edit.task_code
    request = ProtectionRequest.create(ctx.actor, edit.reason)
    private = tuple(v for v in (*edit.key.values(), *edit.values.values()) if isinstance(v, str))
    with registering(*private):
        reason = mask_text(edit.reason or "")
    arguments = {
        "pipeline_code": pipeline,
        "task_code": task,
        "columns": tuple(edit.values),
        "reason": reason,
    }
    with recorded(ctx, ActionName.DATA_EDIT, arguments), registering(*private):
        _check_reason(edit.reason)
        if ctx.actor.kind not in {ActorKind.USER, ActorKind.SERVICE}:
            raise PermissionDeniedError(
                f"actor={ctx.actor.name!r}, kind={ctx.actor.kind}; expected a registered USER "
                "or SERVICE admin; sign in with an account credential"
            )
        if edit.row_lock and ctx.actor.kind != ActorKind.USER:
            raise PermissionDeniedError("row_lock=True requires a human admin; omit row_lock")
        with _selected(ctx, pipeline, task) as (guard, context):
            if exists(guard.session):
                guard.check()
            else:
                guard.enable(request)
            stage, key_hash = _edit_stage(guard, edit)
            spec = replace(guard.task, preserve_target=False, watermark=None)
            guard.session.protection = guard
            guard.request = request
            guard.row_lock = edit.row_lock
            ACTIONS[spec.action](
                guard.session,
                ActionContext(
                    spec,
                    context,
                    task_store(context, ctx.engine),
                    ctx.actor.name,
                    request.now,
                    stage,
                    respect_protection=ctx.actor.kind != ActorKind.USER,
                ),
            )
            return _result(ctx, guard, key_hash, guard.request_id)


def _check_reason(reason: str) -> None:
    """Keep every successful edit/unlock explainable without accepting unbounded evidence."""
    check_reason(reason)


def _selected_key(guard: Protection, key: Mapping[str, object]) -> str:
    """Resolve a typed key even after deletion, so its evidence remains inspectable."""
    _validate_input(guard, key)
    types = guard.session.column_types(guard.session.target)
    expression = ", ".join(
        f"CAST(:key_{i} AS {types[c.lower()]}) AS {c}" for i, c in enumerate(key)
    )
    return str(
        guard.session.run(
            f"SELECT {guard.sql.key_hash} AS key_hash FROM (SELECT {expression}) t",
            {f"key_{i}": v for i, v in enumerate(key.values())},
            step="identify selected key",
        ).scalar_one()
    )


def unlock_values(ctx: OperationContext, edit: ValueUnlock) -> ValueResult:
    """Release protection explicitly; integrations cannot unlock a person's values."""
    pipeline, task = edit.pipeline_code, edit.task_code
    request = ProtectionRequest.create(ctx.actor, edit.reason)
    private = tuple(v for v in edit.key.values() if isinstance(v, str))
    with registering(*private):
        reason = mask_text(edit.reason or "")
    with (
        recorded(
            ctx,
            ActionName.DATA_UNLOCK,
            {
                "pipeline_code": pipeline,
                "task_code": task,
                "reason": reason,
            },
        ),
        registering(*private),
    ):
        _check_reason(edit.reason)
        if ctx.actor.kind != ActorKind.USER:
            raise PermissionDeniedError(
                f"actor={ctx.actor.name!r}, kind={ctx.actor.kind}; expected a human admin; "
                "sign in as a USER admin to release protection"
            )
        with _selected(ctx, pipeline, task) as (guard, _context):
            if not exists(guard.session):
                raise UsageError(
                    f"{guard.session.target}: protection is not enabled; nothing to unlock"
                )
            guard.check()
            unknown = set(edit.columns) - {*guard.business, "*"}
            if unknown:
                raise UsageError(
                    f"{guard.session.target}: unlock columns={sorted(unknown)}; expected business "
                    "columns or '*' for the row lock; correct the column names"
                )
            key_hash = _selected_key(guard, edit.key)
            guard.unlock(key_hash, edit.columns, request)
            return _result(ctx, guard, key_hash, guard.request_id)


def provenance(ctx: OperationContext, request: ValueKey) -> ValueResult:
    """Read known writers and lock evidence; never infer identity from actor-column strings."""
    key = request.key
    with (
        registering(*(v for v in key.values() if isinstance(v, str))),
        _selected(ctx, request.pipeline_code, request.task_code) as (guard, _context),
    ):
        if not exists(guard.session) and not guard.session.protection_active:
            return ValueResult(guard.session.target, False, None, (), ())
        guard.check()
        return _result(ctx, guard, _selected_key(guard, key), None)
