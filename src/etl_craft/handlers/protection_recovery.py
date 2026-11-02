"""Evidence-based protection recovery at the process that can read the warehouse."""

from collections import defaultdict
from collections.abc import Iterable

from etl_craft.core.enums_protection import ProtectionEvidence, ProtectionKind, ProtectionStatus
from etl_craft.core.faults import fault_point
from etl_craft.core.protection import (
    MAX_PROTECTION_EVENTS,
    ProtectionEvent,
    ProtectionRecord,
    ProtectionReport,
)
from etl_craft.engine.task_store import TaskStore
from etl_craft.handlers.sql.session import Session


def records(session: Session, store: TaskStore) -> tuple[ProtectionRecord, ...]:
    """Follow every bounded page; never turn a partial history into a recovery decision."""
    result: list[ProtectionRecord] = []
    cursor = 0
    while True:
        page = store.protection_read(session.target, cursor)
        session.protection_active = page.active
        result.extend(page.records)
        if page.cursor is None:
            return tuple(result)
        cursor = page.cursor


def recover(session: Session, store: TaskStore) -> tuple[ProtectionRecord, ...]:
    """Resolve each unfinished request under the caller's existing target lock."""
    history = records(session, store)
    final = {r.request_id for r in history if r.status != ProtectionStatus.PENDING}
    pending: dict[str, list[ProtectionRecord]] = defaultdict(list)
    for record in history:
        if record.request_id not in final:
            pending[record.request_id].append(record)
    for request_id, events in pending.items():
        deletion = all(
            r.event is not None
            and r.event.kind
            in {
                ProtectionKind.HARD_DELETE,
                ProtectionKind.ERASURE,
            }
            for r in events
        )
        committed = _absent(session, events) if deletion else _stamped(session, request_id)
        evidence = (
            (ProtectionEvidence.KEYS_ABSENT if committed else ProtectionEvidence.KEYS_PRESENT)
            if deletion
            else (
                ProtectionEvidence.STAMP_PRESENT if committed else ProtectionEvidence.STAMP_ABSENT
            )
        )
        store.protection_event(
            session.target,
            ProtectionReport(
                ProtectionStatus.COMMITTED if committed else ProtectionStatus.ABANDONED,
                request_id=request_id,
                evidence=evidence,
            ),
        )
    return records(session, store) if pending else history


def _stamped(session: Session, request_id: str) -> bool:
    if "etl_protection_request_id" not in {c.lower() for c, _ in session.target_columns()}:
        return False
    return bool(
        session.run(
            f"SELECT COUNT(*) FROM {session.target} WHERE ETL_PROTECTION_REQUEST_ID=:request",
            {"request": request_id},
            step="recover protection request stamp",
        ).scalar_one()
    )


def _absent(session: Session, records: list[ProtectionRecord]) -> bool:
    if not session.target_columns():
        return True
    groups: dict[tuple[str, ...], list[ProtectionRecord]] = defaultdict(list)
    for record in records:
        assert record.event is not None
        groups[record.event.columns].append(record)
    return all(_keys_absent(session, group) for group in groups.values())


def _keys_absent(session: Session, records: list[ProtectionRecord]) -> bool:
    for start in range(0, len(records), MAX_PROTECTION_EVENTS):
        batch = records[start : start + MAX_PROTECTION_EVENTS]
        first = batch[0].event
        assert first is not None
        from etl_craft.dialects.business_rules import quote_output_key

        hashed = session.hash(
            [f"t.{quote_output_key(c, session.dialect.sqlglot_dialect)}" for c in first.columns],
            first.columns,
        )
        binds = {f"key_{i}": r.event.key_hash for i, r in enumerate(batch) if r.event}
        placeholders = ",".join(f":{name}" for name in binds)
        if session.run(
            f"SELECT COUNT(*) FROM {session.target} t WHERE {hashed} IN ({placeholders})",
            binds,
            step="recover protection deletion outcome",
        ).scalar_one():
            return False
    return True


def committed(store: TaskStore, target: str, requests: list[str]) -> None:
    """Run only after the target transaction or atomic statement has committed."""
    for request_id in requests:
        fault_point("protection.after_merge")
        store.protection_event(
            target,
            ProtectionReport(
                ProtectionStatus.COMMITTED,
                request_id=request_id,
            ),
        )
        fault_point("protection.after_committed")


def pending(
    store: TaskStore,
    target: str,
    events: Iterable[ProtectionEvent],
    requests: list[str],
    upload_id: int | None = None,
) -> str | None:
    """Durably stage all bounded hash batches before permitting a warehouse mutation."""
    from itertools import islice

    iterator = iter(events)
    request = None
    fault_point("protection.before_pending")
    while batch := tuple(islice(iterator, MAX_PROTECTION_EVENTS)):
        request = store.protection_event(
            target,
            ProtectionReport(
                ProtectionStatus.PENDING,
                batch,
                request,
                upload_id=upload_id,
            ),
        )
    if request is not None:
        requests.append(request)
        fault_point("protection.after_pending")
    return request
