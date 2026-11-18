"""Table adoption results shared by the adoption service and operation interfaces."""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.hashing import RehashResult


@dataclass(frozen=True)
class AdoptResult:
    """One adoption, done or only planned, with the statements it runs."""

    SCHEMA: ClassVar[str] = "etl-craft/adopt-target/1"
    target: str
    action: str
    adopted: bool
    dry_run: bool
    rows: int | None
    kept: str | None
    sql: tuple[str, ...]
    mapped: tuple[str, ...] = ()
    """Managed columns whose values come from the SELECT."""
    defaulted: tuple[str, ...] = ()
    """Managed columns that start with the adoption defaults."""
    rehash: RehashResult | None = None
