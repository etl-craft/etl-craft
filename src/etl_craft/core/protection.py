"""Bounded hash-only protection messages shared by local and remote task stores."""

import re
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from etl_craft.core.enums_protection import ProtectionEvidence, ProtectionKind, ProtectionStatus
from etl_craft.core.errors import UsageError

MAX_PROTECTION_EVENTS = 256
MAX_PROTECTION_COLUMNS = 128
PROTECTION_COLUMNS = ("ETL_PROTECTION", "ETL_ROW_FINGERPRINT", "ETL_PROTECTION_REQUEST_ID")
_HASH = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class ProtectionEvent:
    """One key's named value fingerprints, with no field for business values or actors."""

    __pydantic_config__: ClassVar[dict[str, str]] = {"extra": "forbid"}

    kind: ProtectionKind
    key_hash: str
    columns: tuple[str, ...]
    value_hashes: tuple[str | None, ...]

    def __post_init__(self) -> None:
        """Reject values and unbounded or ambiguous column lists."""
        if not isinstance(self.key_hash, str) or not _HASH.fullmatch(self.key_hash):
            raise UsageError(
                "protection key_hash: found non-hash text; expected "
                "32 hex digits; send only a typed key hash"
            )
        if not 1 <= len(self.columns) <= MAX_PROTECTION_COLUMNS:
            raise UsageError(
                f"protection columns: found {len(self.columns)}; "
                f"expected 1-{MAX_PROTECTION_COLUMNS}; split the "
                "event"
            )
        if len(self.columns) != len(self.value_hashes):
            raise UsageError(
                "protection value_hashes: length differs from columns; "
                "expected one hash per column; correct the event"
            )
        if len(set(self.columns)) != len(self.columns):
            raise UsageError(
                "protection columns: found duplicates; expected "
                "unique column names; correct the event"
            )
        if any(len(c) > 128 for c in self.columns):
            raise UsageError(
                "protection columns: found a name longer than 128; "
                "expected at most 128 characters; use the admitted "
                "column names"
            )
        if any(c == "*" for c in self.columns) and self.kind not in {
            ProtectionKind.LOCK,
            ProtectionKind.UNLOCK,
            ProtectionKind.ERASURE,
        }:
            raise UsageError(
                "protection columns: found row scope on a value "
                "event; expected named columns; use LOCK or UNLOCK "
                "for row scope"
            )
        if any(not c.isprintable() for c in self.columns):
            raise UsageError(
                "protection columns: found an empty or non-printable name; "
                "expected physical column names without control characters; correct the event"
            )
        if any(
            h is not None and (not isinstance(h, str) or not _HASH.fullmatch(h))
            for h in self.value_hashes
        ):
            raise UsageError(
                "protection value_hashes: found non-hash text; "
                "expected 32 hex digits or NULL; send only fingerprints"
            )


@dataclass(frozen=True)
class ProtectionReport:
    """Append a bounded intent batch or finalize one server-allocated request."""

    __pydantic_config__: ClassVar[dict[str, str]] = {"extra": "forbid"}

    status: ProtectionStatus
    events: tuple[ProtectionEvent, ...] = ()
    request_id: str | None = None
    evidence: ProtectionEvidence | None = None
    upload_id: int | None = None

    def __post_init__(self) -> None:
        """Require bounded intents or one existing request's final status."""
        if self.upload_id is not None and (
            not isinstance(self.upload_id, int)
            or isinstance(self.upload_id, bool)
            or not 0 < self.upload_id < 2**63
        ):
            raise UsageError(
                "protection upload_id: expected a positive accepted upload identity; "
                "use only an upload admitted to this attempt's run"
            )
        if self.upload_id is not None and any(
            event.kind
            not in {
                ProtectionKind.ENABLE,
                ProtectionKind.KEY,
                ProtectionKind.VERSION,
                ProtectionKind.WRITE,
                ProtectionKind.LOCK,
                ProtectionKind.UNLOCK,
            }
            for event in self.events
        ):
            raise UsageError(
                "protection upload_id: found a non-upload event kind; expected upload "
                "writes or unlocks only; omit upload_id for engine and operator work"
            )
        if self.request_id is not None:
            try:
                UUID(self.request_id)
            except ValueError as error:
                raise UsageError(
                    "protection request_id: found an invalid id; expected "
                    "a server-issued UUID; use the PENDING response"
                ) from error
        if len(self.events) > MAX_PROTECTION_EVENTS:
            raise UsageError(
                f"protection batch: found {len(self.events)}; expected "
                f"at most {MAX_PROTECTION_EVENTS}; split the batch"
            )
        if self.status == ProtectionStatus.PENDING and (
            not self.events or self.evidence is not None
        ):
            raise UsageError(
                "protection PENDING: found empty events or recovery "
                "evidence; expected a nonempty hash-only batch; "
                "correct the report"
            )
        if self.status != ProtectionStatus.PENDING and (
            not self.request_id or self.events or self.upload_id is not None
        ):
            raise UsageError(
                "protection final status: found missing request "
                "id or new events; expected an existing request "
                "with no new events; correct the report"
            )


@dataclass(frozen=True)
class ProtectionRecord:
    """One immutable status row, retaining the creator during recovery."""

    event_id: int
    request_id: str
    attempt_id: int | None
    status: ProtectionStatus
    event: ProtectionEvent | None
    created_by: str
    created_at: str
    recovering_attempt_id: int | None = None
    recovery_actor: str | None = None
    upload_id: int | None = None
    uploader: str | None = None


@dataclass(frozen=True)
class ProtectionPage:
    """A bounded page; its cursor is the last included immutable event identity."""

    records: tuple[ProtectionRecord, ...]
    cursor: int | None
    active: bool | None = None

    def __post_init__(self) -> None:
        """Reject oversized pages before their contents reach a caller."""
        if len(self.records) > MAX_PROTECTION_EVENTS:
            raise UsageError(
                f"protection page: found {len(self.records)}; expected at most "
                f"{MAX_PROTECTION_EVENTS}; upgrade agent and server together"
            )
        if self.cursor is not None:
            validate_cursor(self.cursor)


def validate_cursor(cursor: int) -> None:
    """Reject cursors that cannot name an Engine DB event identity."""
    if not 0 <= cursor <= 2**63 - 1:
        raise UsageError(
            f"protection cursor={cursor}; expected an event id from 0 to 9223372036854775807; "
            "restart the read"
        )
