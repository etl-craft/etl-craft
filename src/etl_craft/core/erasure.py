"""Private register entries, write filters and safe erasure reports shared across transports."""

from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable


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
    old_versions: str | None = None
    """Where deleted rows stay readable (snapshots, table history), or ``None`` when nowhere."""
    bounded: bool | None = None
    """Whether those old versions expire within a known bound; ``None`` when there are none."""
    retention: str | None = None
    """The physical-retention statement shown with the result, naming the bound or its remedy."""


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


@dataclass(frozen=True)
class ErasureFilter:
    """One column of a write target and the erased keys its writer must not write."""

    column: str
    keys: tuple[str, ...] = field(repr=False)


@runtime_checkable
class HostErasure(Protocol):
    """An agent task store, whose host computes filters and deletes for the attempt's target."""

    def erasure_filters(self, target: str) -> tuple[ErasureFilter, ...]:
        """Return the erased keys this attempt's admitted target must not be written with."""
        ...

    def erase_written(self, target: str) -> ErasureReport:
        """Delete erased keys a script just wrote to its admitted target; return HMAC counts."""
        ...
