"""Validate provisional item evidence at the fenced persistence boundary."""

import json

from sqlalchemy.engine import Connection

from etl_craft.core.enums import OffsetType
from etl_craft.core.item_offsets import position
from etl_craft.core.items import ItemRecord
from etl_craft.core.script_kinds import script_kind
from etl_craft.engine.repository.offsets import fetch_task_offset
from etl_craft.engine.repository.tasks import fetch_task_parameters


def check(conn: Connection, task_id: int, event: ItemRecord) -> None:
    """Apply the same own-key partition contract to local and remote item reports."""
    if event.offset_position is None:
        return
    stored = fetch_task_offset(conn, task_id)
    committed = (
        json.loads(stored.offset_value)
        if stored is not None
        and stored.offset_type == OffsetType.PARTITIONS
        and stored.offset_value is not None
        else None
    )
    params = fetch_task_parameters(conn, task_id)
    kind = script_kind(params, f"task {task_id}")
    position(
        event.key,
        {event.key: event.offset_position},
        OffsetType.PARTITIONS,
        committed,
        None if stored is None else stored.offset_type,
        kind,
    )
