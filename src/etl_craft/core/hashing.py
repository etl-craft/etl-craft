"""Hash maintenance results shared by the warehouse handler and operation interfaces."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class RehashResult:
    """The checked target, row count and statement, applied or only planned."""

    SCHEMA: ClassVar[str] = "etl-craft/rehash/1"
    target: str
    rows: int
    sql: str
    dry_run: bool
