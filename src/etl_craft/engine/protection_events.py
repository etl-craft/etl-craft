"""One hash-only intent store for local operations and fenced agent reports."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.engine import Connection, RowMapping

from etl_craft.config import ConnectorConfig
from etl_craft.core.actor import current_actor
from etl_craft.core.enums import AttemptStatus
from etl_craft.core.enums_protection import ProtectionEvidence, ProtectionKind, ProtectionStatus
from etl_craft.core.errors import PermissionDeniedError, StaleTransitionError, UsageError
from etl_craft.core.protection import (
    MAX_PROTECTION_EVENTS,
    ProtectionEvent,
    ProtectionPage,
    ProtectionRecord,
    ProtectionReport,
    validate_cursor,
)
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id

_LIVE = frozenset({AttemptStatus.QUEUED, AttemptStatus.CLAIMED, AttemptStatus.RUNNING})
_DELETIONS = frozenset({ProtectionKind.HARD_DELETE, ProtectionKind.ERASURE})


@dataclass(frozen=True)
class Creator:
    """Retain a request's original attempt and mutation kind."""

    attempt_id: int | None
    kind: ProtectionKind
    attempt_status: str | None


def target_identity(config: ConnectorConfig, target: str) -> tuple[str, str]:
    """Share warehouse-normalized quoted audit identity and the existing lock identity."""
    from etl_craft.config.targets import active_catalog, parse_warehouse_url
    from etl_craft.dialects.business_rules import quote_output_key
    from etl_craft.dialects.warehouse import resolve
    from etl_craft.engine.repository.normalization import object_identity

    assert config.warehouse is not None
    dialect = resolve(
        parse_warehouse_url(config.warehouse.jdbc_url).dialect, config.warehouse_table_format
    )
    try:
        parts = object_identity(target, active_catalog(config), dialect.sqlglot_dialect)
    except ValueError as error:
        raise UsageError(str(error)) from None
    names = tuple(str(p) for p in parts)
    return ".".join(quote_output_key(p, dialect.sqlglot_dialect) for p in names), ".".join(names)


def _scope(target: str) -> dict[str, object]:
    return {"project_id": current_project_id(), "target": target}


def read(conn: Connection, target: str, cursor: int = 0) -> ProtectionPage:
    """Read immutable rows in bounded pages without silently dropping an event."""
    validate_cursor(cursor)
    rows = (
        conn.execute(
            statement(conn, "protection_read"),
            {**_scope(target), "cursor": cursor, "page_size": MAX_PROTECTION_EVENTS + 1},
        )
        .mappings()
        .all()
    )
    result = _records(rows[:MAX_PROTECTION_EVENTS])
    return ProtectionPage(
        result, result[-1].event_id if len(rows) > MAX_PROTECTION_EVENTS else None
    )


def fenced_read(
    conn: Connection, target: str, fencing: dict[str, object], cursor: int = 0
) -> ProtectionPage:
    """Check the live attempt/lock and pending work in one Engine DB round trip."""
    validate_cursor(cursor)
    rows = (
        conn.execute(
            statement(conn, "protection_fenced_read"),
            {**_scope(target), **fencing, "cursor": cursor, "page_size": MAX_PROTECTION_EVENTS + 1},
        )
        .mappings()
        .all()
    )
    where = f"attempt {fencing['attempt_id']}, target {target}"
    if not rows[0]["live_attempt"]:
        raise StaleTransitionError(
            f"{where}: live-attempt/token check failed; stop this writer and obtain a fresh attempt"
        )
    if not rows[0]["lock_owned"]:
        raise StaleTransitionError(
            f"{where}: target-lock check failed; acquire its live lock before reporting"
        )
    events = [row for row in rows if row["event_id"] is not None]
    result = _records(events[:MAX_PROTECTION_EVENTS])
    return ProtectionPage(
        result,
        result[-1].event_id if len(events) > MAX_PROTECTION_EVENTS else None,
        bool(rows[0]["protection_active"]),
    )


def history(
    conn: Connection, target: str, key_hash: str, request_id: str | None
) -> tuple[ProtectionRecord, ...]:
    """Return a bounded current-key history, including the caller's committing mutation."""
    rows = (
        conn.execute(
            statement(conn, "protection_history"),
            {
                **_scope(target),
                "key_hash": key_hash,
                "current_request": request_id,
            },
        )
        .mappings()
        .all()
    )
    return _records(rows)


def _records(rows: Sequence[RowMapping]) -> tuple[ProtectionRecord, ...]:
    return tuple(
        ProtectionRecord(
            r["event_id"],
            r["request_id"],
            r["attempt_id"],
            ProtectionStatus(r["status"]),
            None
            if r["key_hash"] is None
            else ProtectionEvent(
                ProtectionKind(r["kind"]),
                r["key_hash"],
                tuple(json.loads(r["column_names"])),
                tuple(json.loads(r["value_hashes"])),
            ),
            r["created_by"],
            as_utc(r["created_at"]).isoformat(),
            r["recovering_attempt_id"],
            r["recovery_actor"],
            r["upload_id"],
            r["uploader"],
        )
        for r in rows
    )


def append_fenced(
    conn: Connection, target: str, report: ProtectionReport, fencing: dict[str, object]
) -> str | None:
    """Append ordinary owned outcomes with their fence in the same atomic statement."""
    report.__post_init__()
    if report.evidence is not None:
        return None
    request = report.request_id or str(uuid4())
    events = [
        {
            "kind": e.kind,
            "key_hash": e.key_hash,
            "columns": json.dumps(e.columns),
            "hashes": json.dumps(e.value_hashes),
        }
        for e in report.events
    ]
    params = {
        **_scope(target),
        **fencing,
        "request_id": request,
        "events": json.dumps(events),
        "continuation": report.request_id is not None,
        "upload_id": report.upload_id,
        "status": report.status,
        "actor": current_actor().name,
        "now": datetime.now(UTC),
    }
    name = (
        "protection_append_pending"
        if report.status == ProtectionStatus.PENDING
        else "protection_append_final"
    )
    inserted = conn.execute(statement(conn, name), params).all()
    return request if inserted else None


def append(
    conn: Connection,
    target: str,
    report: ProtectionReport,
    attempt_id: int | None,
    hash_target: str | None = None,
) -> str:
    """Allocate intents and append one final outcome, preserving its creating attempt."""
    report.__post_init__()
    request_id = report.request_id or str(uuid4())
    scope = {**_scope(target), "request_id": request_id}
    previous = (
        conn.execute(statement(conn, "protection_request"), scope).all()
        if report.request_id is not None
        else []
    )
    if not previous and (
        report.status != ProtectionStatus.PENDING or report.request_id is not None
    ):
        raise PermissionDeniedError(
            f"attempt {attempt_id}, target {target}: request {request_id} was not created here; "
            "expected an owned PENDING request; read this target's intents before finalizing"
        )
    if previous:
        creator = previous[0]
        _ownership(
            target,
            request_id,
            Creator(creator.attempt_id, ProtectionKind(creator.kind), creator.attempt_status),
            report,
            attempt_id,
        )
        if creator.final_status is not None:
            return request_id
    if report.status == ProtectionStatus.PENDING and report.upload_id is not None:
        raise PermissionDeniedError(
            f"attempt {attempt_id}, target {target}, upload {report.upload_id}: "
            "expected this run's verified accepted upload; finish FILE_VALIDATION "
            "and use only the uploads admitted to this task"
        )
    if report.status == ProtectionStatus.PENDING:
        for event in report.events:
            _insert(conn, scope, report, event, attempt_id, None)
    else:
        first = conn.execute(statement(conn, "protection_first_pending"), _scope(target)).first()
        if first is not None and first.request_id != request_id:
            raise PermissionDeniedError(
                f"attempt {attempt_id}, target {target}: request "
                f"{first.request_id} from attempt {first.attempt_id} "
                f"is pending before {request_id}; expected intent-order "
                "finalization; recover the older request first"
            )
        if (
            report.status == ProtectionStatus.COMMITTED
            and previous[0].kind == ProtectionKind.REHASH
        ):
            from etl_craft.engine.repository.hash_versions import save_hash_version

            save_hash_version(conn, hash_target or target, 2)
        _insert(conn, scope, report, None, previous[0].attempt_id, attempt_id)
    return request_id


def _ownership(
    target: str, request_id: str, creator: Creator, report: ProtectionReport, attempt_id: int | None
) -> None:
    detail = (
        f"attempt {attempt_id}, target {target}, request "
        f"{request_id}, creating attempt {creator.attempt_id}"
    )
    if report.evidence is not None:
        _evidence(detail, creator.kind, report)
    if creator.attempt_id == attempt_id:
        return
    if report.evidence is None or report.status == ProtectionStatus.PENDING:
        raise PermissionDeniedError(
            f"{detail}: creator-only finalization check failed; expected the creating attempt; "
            "use evidence-based recovery after reconciling the creator"
        )
    if creator.attempt_id is not None and creator.attempt_status is None:
        raise PermissionDeniedError(
            f"{detail}: creating-attempt history is missing; expected terminal or reconciled "
            "LOST evidence; restore the creating attempt's audit history before recovery"
        )
    if creator.attempt_id is not None and creator.attempt_status in _LIVE:
        raise PermissionDeniedError(
            f"{detail}: creator is {creator.attempt_status}, not terminal or reconciled LOST; "
            "reconcile its expired lease before recovery, or wait for the live attempt"
        )


def _evidence(detail: str, kind: ProtectionKind, report: ProtectionReport) -> None:
    """Never accept a terminal outcome that contradicts its reported warehouse evidence."""
    deletion = kind in _DELETIONS
    committed = ProtectionEvidence.KEYS_ABSENT if deletion else ProtectionEvidence.STAMP_PRESENT
    abandoned = ProtectionEvidence.KEYS_PRESENT if deletion else ProtectionEvidence.STAMP_ABSENT
    expected = committed if report.status == ProtectionStatus.COMMITTED else abandoned
    if report.evidence != expected:
        raise PermissionDeniedError(
            f"{detail}: evidence={report.evidence}, expected {expected} for {report.status}; "
            "read the warehouse under the target lock and report its actual outcome"
        )


def _insert(
    conn: Connection,
    scope: dict[str, object],
    report: ProtectionReport,
    event: ProtectionEvent | None,
    creator: int | None,
    recovering: int | None,
) -> None:
    actor = current_actor().name
    previous = (
        conn.execute(statement(conn, "protection_request"), scope).first()
        if event is None
        else None
    )
    if event is not None:
        kind = event.kind
    else:
        assert previous is not None
        kind = previous.kind
    conn.execute(
        statement(conn, "protection_insert"),
        {
            **scope,
            "attempt_id": creator,
            "upload_id": None if previous is None else previous.upload_id,
            "kind": kind,
            "key_hash": None if event is None else event.key_hash,
            "columns": json.dumps(() if event is None else event.columns),
            "hashes": json.dumps(() if event is None else event.value_hashes),
            "status": report.status,
            "actor": actor,
            "now": datetime.now(UTC),
            "recovering_attempt": recovering if report.evidence is not None else None,
            "recovery_actor": actor if report.evidence is not None else None,
        },
    )
