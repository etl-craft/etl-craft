"""Private register entries and safe erasure reports shared across task transports."""

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class ErasureEntry:
    """One exact register value, never a result document."""

    table: str
    column: str
    value: str = field(repr=False)
    key_hmac: str


@dataclass(frozen=True)
class ErasureSelection:
    """All direct identifier columns deleted atomically from one physical table."""

    entry: ErasureEntry
    columns: tuple[str, ...]
    parent: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class ErasedTable:
    """A table's committed deletion or preview, identified without a personal key."""

    table: str
    column: str
    key_hmac: str
    rows: int


@dataclass(frozen=True)
class Unfollowed:
    """A boundary requiring an explicit further registration or removal of the identifier."""

    table: str
    reason: str
    remedy: str = (
        "Keep the identifier out of this table, or register its table and column "
        "as a further entry."
    )


@dataclass(frozen=True)
class ErasureReport:
    """Only HMAC identities, counts and lineage boundaries leave execution."""

    SCHEMA: ClassVar[str] = "etl-craft/erasure/1"
    tables: tuple[ErasedTable, ...] = ()
    unfollowed: tuple[Unfollowed, ...] = ()
    dry_run: bool = False
