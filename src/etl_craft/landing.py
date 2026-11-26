"""Bounded staging and fenced publication for script-owned landing batches."""

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from etl_craft.core.errors import HandlerError
from etl_craft.core.landing import LandingWrite, current_item

if TYPE_CHECKING:
    from etl_craft.scripting import ScriptTask


def replace_landing(
    task: "ScriptTask", rows: Iterable[Mapping[str, object]], *, item_key: str | None
) -> int:
    """Refuse foreign item scopes before reading metadata or opening the warehouse."""
    item = current_item.get()
    if (item_key is not None and item != (task.task_run_id, item_key)) or (
        item_key is None and item is not None
    ):
        raise HandlerError(
            f"{task.pipeline_code}.{task.task_code}: item_key={item_key!r}; expected the "
            "current fan_out item key; remedy: replace only this item inside its function"
        )
    if task._landing is None or (contract := task._landing()) is None or not contract.columns:
        raise HandlerError(
            f"{task.pipeline_code}.{task.task_code}: replace_landing has no declared target "
            "and CFG_COLUMNS types; remedy: declare the landing table and all business columns"
        )
    from etl_craft.config.targets import active_catalog
    from etl_craft.engine import locks
    from etl_craft.warehouse.connection import warehouse_dialect
    from etl_craft.warehouse.landing import publish

    if task._locks is None:
        raise HandlerError("replace_landing needs an admitted target lock; run through etl-craft")
    lock = locks.target(contract.target, active_catalog(task.config))
    write = LandingWrite(
        contract,
        task.pipeline_id,
        task.pipeline_run_id,
        task.task_run_id,
        item_key,
    )
    with (
        task._warehouse_mutex,
        task._locks.hold(lock.key, lock.name, 30),
        task.warehouse() as engine,
        engine.connect() as conn,
    ):
        return publish(conn, warehouse_dialect(task.config), write, rows)
