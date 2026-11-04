"""Declared landing contracts and the exact fan-out item allowed to replace rows."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LandingContract:
    """An admitted task owns one target with explicitly declared business types."""

    task_id: int
    target: str
    columns: tuple[tuple[str, str], ...]


current_item: ContextVar[tuple[int, str] | None] = ContextVar("landing_item", default=None)


@dataclass(frozen=True)
class LandingWrite:
    """The immutable provenance and ownership of one landing publication."""

    contract: LandingContract
    pipeline_id: int
    pipeline_run_id: int
    task_run_id: int
    item_key: str | None


GENERATED_COLUMNS = frozenset(
    {
        "pipeline_id",
        "pipeline_run_id",
        "task_run_id",
        "row_id",
        "create_date",
        "update_date",
        "landing_task_id",
        "item_key",
        "created_by",
        "updated_by",
    }
)
