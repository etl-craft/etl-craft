"""Exact row-change and upload lock intents, computed from effective staged hashes."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy.engine import RowMapping

from etl_craft.core.enums import ActorKind
from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.protection import MAX_PROTECTION_COLUMNS, ProtectionEvent
from etl_craft.core.protection_state import ProtectionRequest, RowProtection

if TYPE_CHECKING:
    from etl_craft.handlers.sql.protection import Protection


def plan(
    guard: "Protection", incoming: Sequence[RowMapping], request: ProtectionRequest
) -> tuple[list[ProtectionEvent], dict[str, dict[str, str]]]:
    """Record writes and lock-only changes together before their one target MERGE."""
    events: list[ProtectionEvent] = []
    changed = {}
    guard.unlocking.clear()
    guard.mutating_rows = sum(bool(row["mutating"]) for row in incoming)
    guard.business_changes = bool(guard.mutating_rows)
    for row in incoming:
        key = str(row["key_hash"])
        hashes = {c: str(row[f"cell_{i}"]) for i, c in enumerate(guard.business)}
        old = guard.states.get(key)
        release = (
            request.upload_id is not None
            and request.actor.kind == ActorKind.USER
            and row["upload_locked"] is False
        )
        if release:
            guard.unlocking.add(key)
        row_events = _row_events(guard, old, row, hashes, request, release)
        if row_events:
            changed[key] = hashes
            events.append(
                ProtectionEvent(
                    ProtectionKind.KEY,
                    key,
                    guard.key_columns,
                    tuple(hashes.get(c.lower()) for c in guard.key_columns),
                )
            )
            events.extend(row_events)
    return events, changed


def _row_events(
    guard: "Protection",
    old: RowProtection | None,
    row: RowMapping,
    hashes: dict[str, str],
    request: ProtectionRequest,
    release: bool,
) -> list[ProtectionEvent]:
    key = str(row["key_hash"])
    names = tuple(
        c for c, h in hashes.items() if old is None or old.cells[c].get("value_hash") != h
    )
    human = request.actor.kind == ActorKind.USER
    if human and request.upload_id is not None and not release:
        names = tuple(
            c for c in hashes if c in names or old is None or not old.cells[c].get("locked")
        )
    events = []
    if names:
        kind = ProtectionKind.LOCK if human and not release else ProtectionKind.WRITE
        events.append(ProtectionEvent(kind, key, names, tuple(hashes[c] for c in names)))
    if not names and (guard.activating or row["mutating"]):
        kind = ProtectionKind.VERSION if row["mutating"] else ProtectionKind.ENABLE
        events.append(
            ProtectionEvent(kind, key, guard.key_columns, (None,) * len(guard.key_columns))
        )
    if human and not release and (old is None or guard.row_lock):
        events.append(ProtectionEvent(ProtectionKind.LOCK, key, ("*",), (None,)))
    if release:
        events.extend(_release_events(key, hashes, old))
    return events


def _release_events(
    key: str, hashes: dict[str, str], old: RowProtection | None
) -> list[ProtectionEvent]:
    columns = (*hashes, "*")
    events = []
    for start in range(0, len(columns), MAX_PROTECTION_COLUMNS):
        names = columns[start : start + MAX_PROTECTION_COLUMNS]
        values = tuple(
            str(value)
            if (value := old.cells.get(c, {}).get("value_hash") if old else None) is not None
            else None
            for c in names
        )
        events.append(ProtectionEvent(ProtectionKind.UNLOCK, key, names, values))
    return events
