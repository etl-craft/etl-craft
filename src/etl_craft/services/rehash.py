"""Upgrade a target's stored change hashes without altering its rows or audit columns."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import SqlAction
from etl_craft.core.errors import HandlerError
from etl_craft.core.hashing import RehashResult as RehashResult
from etl_craft.core.text import is_safe_identifier, qualify, split_object_ref
from etl_craft.engine import locks
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.tasks import fetch_task_parameters
from etl_craft.handlers.resources import LocalLocker


def rehash(
    engine: Engine, config: ConnectorConfig, target: str, *, dry_run: bool = False
) -> RehashResult:
    """Recompute every target version using its active merge tasks' common compare columns."""
    split_object_ref(target)
    catalog = active_catalog(config)
    qualified = qualify(target, catalog)
    with locks.target(target, catalog).hold(LocalLocker(engine, config)):
        with engine.connect() as conn:
            task_ids = conn.execute(statement(conn, "rehash_tasks")).scalars().all()
            tasks = {task_id: fetch_task_parameters(conn, task_id) for task_id in task_ids}
        contracts = set()
        for params in tasks.values():
            if params.get("SQL_ACTION") not in {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}:
                continue
            if (
                not params.get("TARGET_OBJECT")
                or qualify(params["TARGET_OBJECT"], catalog).lower() != qualified.lower()
            ):
                continue
            columns = tuple(
                c.strip().lower() for c in params.get("MERGE_COMPARE_COLUMNS", "").split("|")
            )
            if not columns or any(not is_safe_identifier(c) for c in columns):
                raise HandlerError(
                    f"{qualified}: active merge task has invalid MERGE_COMPARE_COLUMNS; "
                    "fix its metadata"
                )
            contracts.add(columns)
        if len(contracts) != 1:
            raise HandlerError(
                f"{qualified}: expected one common ordered MERGE_COMPARE_COLUMNS contract "
                f"across active merge tasks; found {sorted(contracts)}. "
                "Configure matching compare columns before rehashing"
            )
        columns = next(iter(contracts))
        from etl_craft.handlers.rehash import rehash_target

        return rehash_target(engine, config, target, columns, dry_run=dry_run)
