"""Provisional partition evidence, retained within one task run until attempt success."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from etl_craft.core.enums import ScriptKind
from etl_craft.core.errors import PermanentError
from etl_craft.core.items import ItemRecord

if TYPE_CHECKING:
    from etl_craft.scripting import Offset, ScriptResult, ScriptTask


def position(
    key: str, offset: "Offset | None", committed: "Offset | None", kind: str
) -> int | None:
    """Refuse an item position outside its partition and committed task cursor."""
    if offset is None:
        return None
    from etl_craft.core.item_offsets import position as checked_position

    previous = None
    if committed is not None and isinstance(committed.value, Mapping):
        previous = committed.value
    return checked_position(
        key,
        offset.value,
        offset.datatype,
        previous,
        None if committed is None else committed.datatype,
        kind,
    )


def combined(task: "ScriptTask", records: tuple[ItemRecord, ...]) -> "Offset | None":
    """Retained successes carry their own positions; offset-free items keep committed positions."""
    from etl_craft.scripting import Offset

    positions = {r.key: r.offset_position for r in records if r.offset_position is not None}
    if not positions:
        return None
    previous: dict[str, int] = {}
    if task.offset is not None:
        committed_value = task.offset.value
        assert isinstance(committed_value, Mapping)
        previous.update(committed_value)
    for key, value in positions.items():
        position(key, Offset.partitions({key: value}), task.offset, ScriptKind.INGESTION)
    previous.update(positions)
    task._item_positions.update(positions)
    return Offset.partitions(previous)


def check_return(task: "ScriptTask", result: "ScriptResult") -> None:
    """Refuse scripts overriding or omitting their combined provisional positions."""
    if not task._item_positions:
        return
    value = result.offset.value if result.offset is not None else None
    for key, expected in task._item_positions.items():
        found = value.get(key) if isinstance(value, Mapping) else None
        if not isinstance(value, Mapping) or value.get(key) != expected:
            raise PermanentError(
                f"item {key}: script returned position {found!r}; "
                f"expected retained position {expected}; "
                "return the combined fan_out offset unchanged"
            )
