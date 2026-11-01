"""Read-only erasure checks for validation and doctor."""

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums import Handler
from etl_craft.core.erasure import ErasureEntry
from etl_craft.core.errors import EtlCraftError
from etl_craft.core.redaction import registering
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.validation import fetch_active_tasks
from etl_craft.handlers.erasure import apply_entries, check_column, secret
from etl_craft.handlers.resources import LocalLocker
from etl_craft.warehouse.connection import open_warehouse


def problems(engine: Engine, config: ConnectorConfig, *, check_coverage: bool = True) -> list[str]:
    """Preflight active entries and report every lineage boundary without modifying data."""
    with engine.connect() as conn:
        entries = tuple(
            ErasureEntry(r.table_name, r.column_name, r.subject_key, r.key_hmac)
            for r in conn.execute(statement(conn, "erasure_entries"), {"all_entries": False})
        )
        tasks = fetch_active_tasks(conn)
    has_task = any(task.handler == Handler.ERASURE for task in tasks)
    if not entries and not has_task:
        return []
    try:
        with registering(*(entry.value for entry in entries)):
            return _problems(engine, config, entries, has_task, check_coverage)
    except EtlCraftError as error:
        return [str(error)]


def _problems(
    engine: Engine,
    config: ConnectorConfig,
    entries: tuple[ErasureEntry, ...],
    has_task: bool,
    check_coverage: bool,
) -> list[str]:
    if not check_coverage:
        secret(config)
        with open_warehouse(config, LocalLocker(engine, config), hide_parameters=True) as warehouse:
            for entry in entries:
                check_column(warehouse, config, entry.table, entry.column)
        return []
    report = apply_entries(engine, config, entries, dry_run=True)
    found = [f"{b.table}: {b.reason} {b.remedy}" for b in report.unfollowed]
    if entries and not has_task:
        found.append("active erasure entries have no ERASURE task; add one after loads or nightly")
    return found
