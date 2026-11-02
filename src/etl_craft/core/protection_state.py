"""Canonical row-local lock and writer state, without business values."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActorKind
from etl_craft.core.errors import SqlGuardError


@dataclass(frozen=True)
class ProtectionRequest:
    """The deliberate writer and explanation for one target mutation."""

    actor: Actor
    reason: str
    request_id: str
    now: datetime

    @classmethod
    def create(cls, actor: Actor, reason: str) -> "ProtectionRequest":
        """Keep request allocation in the event service, after staging the exact hashes."""
        return cls(actor, reason, "", datetime.now(UTC))


@dataclass
class RowProtection:
    """Keep canonical per-cell locks and writers beside business values."""

    contract: list[object] | None
    cells: dict[str, dict[str, object]] = field(default_factory=dict)
    revision: int = 0

    @classmethod
    def load(cls, value: str | None, contract: list[object], target: str) -> "RowProtection":
        """Validate the stored format and admitted merge contract."""
        if value is None:
            return cls(contract)
        try:
            raw = json.loads(value)
        except (ValueError, TypeError) as error:
            raise SqlGuardError(
                f"{target}: malformed ETL_PROTECTION; expected canonical "
                "format 1; restore the target from a consistent "
                "backup"
            ) from error
        if (
            isinstance(raw, dict)
            and raw.get("format") == 1
            and raw.get("contract") is None
            and raw.get("cells") == {}
            and raw.get("revision") == 0
        ):
            return cls(contract)
        if not isinstance(raw, dict) or raw.get("format") != 1 or raw.get("contract") != contract:
            raise SqlGuardError(
                f"{target}: ETL_PROTECTION format or contract differs; "
                "expected format 1 and the admitted merge contract; "
                "restore matching keys, compare columns and business "
                "shape"
            )
        cells = raw.get("cells")
        revision = raw.get("revision")
        if not isinstance(cells, dict) or not isinstance(revision, int):
            raise SqlGuardError(
                f"{target}: malformed lock cells/revision; expected "
                "named cell states; restore the target from a consistent "
                "backup"
            )
        return cls(contract, cells, revision)

    def encoded(self) -> str:
        """Encode a stable representation for typed fingerprinting."""
        return json.dumps(
            {
                "format": 1,
                "contract": self.contract,
                "cells": self.cells,
                "revision": self.revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def changed(
        self,
        hashes: dict[str, str],
        request: ProtectionRequest,
        *,
        inserted: bool = False,
        row_lock: bool = False,
    ) -> tuple[str, ...]:
        """Update actual changed cell writers while preserving every other cell's owner."""
        actor, reason, request_id, now = (
            request.actor,
            request.reason,
            request.request_id,
            request.now.isoformat(),
        )
        changes = []
        self.revision += 1
        for column, value_hash in hashes.items():
            old = self.cells.get(column)
            if old is not None and old.get("value_hash") == value_hash:
                continue
            changes.append(column)
            self.cells[column] = {
                "value_hash": value_hash,
                "locked": bool(old and old.get("locked"))
                or (actor.kind == ActorKind.USER and not inserted),
                "writer": actor.name,
                "writer_kind": actor.kind,
                "actor": actor.name,
                "actor_kind": actor.kind,
                "happened_at": now,
                "reason": reason,
                "request_id": request_id,
                "revision": self.revision,
            }
        if actor.kind == ActorKind.USER and (inserted or row_lock):
            self.cells["*"] = {
                "value_hash": None,
                "locked": True,
                "writer": actor.name,
                "writer_kind": actor.kind,
                "actor": actor.name,
                "actor_kind": actor.kind,
                "happened_at": now,
                "reason": reason,
                "request_id": request_id,
                "revision": self.revision,
            }
        return tuple(changes)
