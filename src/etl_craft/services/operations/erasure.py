"""Admin-controlled standing erasures, shared by the command and the browser."""

import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from etl_craft.config.project import project_config
from etl_craft.core.actor import acting_as
from etl_craft.core.erasure import ErasureEntry, ErasureReport
from etl_craft.core.errors import HandlerError, UsageError
from etl_craft.core.redaction import mask, mask_text, registering
from etl_craft.dialects.warehouse.erasure import column_identity
from etl_craft.engine.bundles import Bundle
from etl_craft.engine.queries import statement
from etl_craft.handlers.erasure import apply_entries, check_column, identity, secret
from etl_craft.handlers.resources import LocalLocker
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import NoInput, Request
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect


@dataclass(frozen=True, kw_only=True)
class EraseInput(Request):
    """The private value is never included in the action request's audit arguments."""

    table: str
    column: str
    value: str = field(repr=False, metadata={"audit": False})
    reason: str
    dry_run: bool = False
    lift: bool = False


@dataclass(frozen=True)
class ErasureList:
    """Register metadata deliberately omits SUBJECT_KEY."""

    SCHEMA: ClassVar[str] = "etl-craft/erasure-list/1"
    entries: tuple[dict[str, object], ...]


def deployment(ctx: OperationContext) -> OperationContext:
    """Use the same immutable project publication as ordinary warehouse operations."""
    with ctx.engine.connect() as conn:
        bundle_id = conn.execute(statement(conn, "bundle_latest")).scalar_one_or_none()
        bundle = Bundle.load(conn, bundle_id) if bundle_id is not None else None
    if bundle is not None:
        config = project_config(ctx.config, bundle.materialize(ctx.config) / "craft-connector.yml")
        return replace(ctx, config=config)
    return ctx


def entries(ctx: OperationContext, request: NoInput) -> ErasureList:
    """List HMACs and a fixed mask, never personal values."""
    with ctx.engine.connect() as conn:
        rows = (
            conn.execute(statement(conn, "erasure_entries"), {"all_entries": True}).mappings().all()
        )
    safe = []
    with registering(*(str(row["subject_key"]) for row in rows)):
        for row in rows:
            safe.append(
                {k: v if k == "key_hmac" else mask(v) for k, v in row.items() if k != "subject_key"}
                | {"subject_key": "[REDACTED]"}
            )
    return ErasureList(tuple(safe))


def erase(ctx: OperationContext, request: EraseInput) -> ErasureReport:
    """Register before the first deletion; retries reapply every active standing entry."""
    if not isinstance(request.value, str) or not request.value:
        raise UsageError(
            "erasure value is missing or not text; expected a nonempty identifier; supply --value"
        )
    with registering(request.value), acting_as(ctx.actor):
        return _erase(deployment(ctx), request)


def _erase(ctx: OperationContext, request: EraseInput) -> ErasureReport:
    if not request.reason.strip():
        raise UsageError("erasure reason is empty; expected a nonempty reason; supply --reason")
    if request.lift and request.dry_run:
        raise UsageError(
            "erasure lift=True,dry_run=True; expected one operation; remove --dry-run when lifting"
        )
    key = secret(ctx.config)
    table = identity(ctx.config, request.table)
    column = column_identity(request.column, warehouse_dialect(ctx.config))
    with (
        registering(key),
        open_warehouse(
            ctx.config, LocalLocker(ctx.engine, ctx.config), hide_parameters=True
        ) as warehouse,
    ):
        check_column(warehouse, ctx.config, table, column)
    assert isinstance(request.value, str)
    digest = hmac.new(
        key.encode(),
        json.dumps(
            [table, column, request.value], separators=(",", ":"), ensure_ascii=False
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    entry = ErasureEntry(table, column, request.value, digest)
    if request.dry_run:
        return apply_entries(ctx.engine, ctx.config, (entry,), dry_run=True)
    parameters = {
        "project_id": ctx.project_id,
        "table_name": table,
        "column_name": column,
        "key_hmac": digest,
        "subject_key": request.value,
        "reason": mask_text(request.reason),
        "actor": ctx.actor.name,
        "now": datetime.now(UTC),
    }
    if request.lift:
        parameters.pop("subject_key")
        with ctx.engine.begin() as conn:
            changed = conn.execute(statement(conn, "erasure_lift"), parameters).rowcount
        if changed != 1:
            raise HandlerError(
                f"{table}.{column}, entry {digest}: active entry not found or already lifted; "
                "expected one active entry; use erase --list and re-register if needed"
            )
        return ErasureReport()
    try:
        with ctx.engine.begin() as conn:
            conn.execute(statement(conn, "erasure_insert"), parameters)
    except IntegrityError:
        with ctx.engine.connect() as conn:
            active = conn.execute(
                statement(conn, "erasure_active"),
                {
                    name: parameters[name]
                    for name in ("project_id", "table_name", "column_name", "key_hmac")
                },
            ).one_or_none()
        if active is None:
            raise HandlerError(
                f"{table}.{column}, entry {digest}: registration was refused; expected a "
                "valid guarded register row; restore the Engine DB constraints and retry"
            ) from None
    except SQLAlchemyError:
        raise HandlerError(
            f"{table}.{column}, entry {digest}: register write failed; expected a writable "
            "Engine DB; restore its connection and retry erasure"
        ) from None
    return apply_entries(ctx.engine, ctx.config, (entry,))
