"""What a migration runs against: the project's warehouse target, and the markers it may carry.

Engine DB migrations start from the 0.9.0 baseline schema. The one marker, ``rebuild-metadata``,
asks the runner to rebuild the generated guard and history triggers around the file's
statements; a migration declares it in its header as ``-- etl-craft: rebuild-metadata``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class Target:
    """Where project metadata points: the warehouse catalog and SQL dialect."""

    catalog: str | None = None
    warehouse_dialect: str | None = None


class TargetOptions(TypedDict, total=False):
    """Keyword inputs for the migration context used by setup and migrate."""

    catalog: str | None
    warehouse_dialect: str | None


NO_TARGET = Target()
MARKERS = frozenset({"rebuild-metadata"})
"""Every marker a packaged migration header may declare."""
