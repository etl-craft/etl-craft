"""Startup recovery and read-only diagnostics over the common protection event service."""

import logging
from collections import defaultdict

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import SqlAction
from etl_craft.core.errors import ConfigurationError, LockTimeoutError
from etl_craft.dialects.warehouse import WarehouseDialect
from etl_craft.dialects.warehouse.protection import recovery_candidates
from etl_craft.engine import locks
from etl_craft.engine.protection_events import target_identity
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id
from etl_craft.engine.task_store import LocalTaskStore
from etl_craft.handlers.protection_recovery import recover
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.session import Session
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect

logger = logging.getLogger(__name__)


def startup(engine: Engine, config: ConnectorConfig) -> None:
    """Defer inaccessible projects once; every mutation still recovers under its target lock."""
    with engine.connect() as conn:
        targets = conn.execute(
            statement(conn, "protection_targets"), {"project_id": current_project_id()}
        ).all()
    if not targets:
        return
    locker = LocalLocker(engine, config)
    try:
        with open_warehouse(config, locker) as warehouse, warehouse.connect():
            pass
    except (ConfigurationError, SQLAlchemyError, OSError) as error:
        logger.info(
            "project %s: protection recovery deferred: warehouse "
            "cannot be opened (%s); recovery runs before its "
            "next mutation",
            config.project,
            type(error).__name__,
        )
        return
    for row in targets:
        try:
            _recover_target(engine, config, row.target_id)
        except LockTimeoutError:
            logger.info(
                "project %s, target %s: protection recovery deferred "
                "while its lock is busy; recover before the next "
                "mutation",
                config.project,
                row.target_id,
            )


def _recover_target(engine: Engine, config: ConnectorConfig, target: str) -> None:
    locker = LocalLocker(engine, config)
    store = LocalTaskStore.standalone(engine, config, locker)
    with (
        locks.target(target_identity(config, target)[1], active_catalog(config)).hold(locker),
        open_warehouse(config, locker) as warehouse,
        warehouse.begin() as conn,
    ):
        session = _session(conn, warehouse_dialect(config), config, target)
        try:
            recover(session, store)
        finally:
            session.sweep()


def problems(engine: Engine, config: ConnectorConfig) -> list[str]:
    """Report externally removed locked keys without turning membership into a write gate."""
    with engine.connect() as conn:
        targets = (
            conn.execute(
                statement(conn, "protection_all_targets"), {"project_id": current_project_id()}
            )
            .scalars()
            .all()
        )
    if not targets:
        return []
    from etl_craft.engine.privacy import check

    with engine.connect() as conn:
        privacy_key = check(conn, config)
    assert privacy_key is not None
    result = []
    for target in targets:
        with engine.connect() as conn:
            rows = conn.execute(
                statement(conn, "protection_locked_keys"),
                {"project_id": current_project_id(), "target": target},
            ).all()
        locked: dict[str, set[str]] = defaultdict(set)
        columns: dict[str, tuple[str, ...]] = {}
        for row in rows:
            import json

            from etl_craft.core.enums_protection import ProtectionKind

            names = tuple(json.loads(row.column_names))
            if row.kind == ProtectionKind.KEY:
                columns[row.key_hash] = names
            elif row.kind == ProtectionKind.LOCK:
                locked[row.key_hash].update(names)
            elif row.kind == ProtectionKind.UNLOCK:
                locked[row.key_hash].difference_update(names)
            elif columns.get(row.key_hash) == names:
                locked.pop(row.key_hash, None)
        expected = {key: columns[key] for key, cells in locked.items() if cells and key in columns}
        missing = _missing(engine, config, target, expected, privacy_key)
        if missing:
            result.append(
                f"{target}: {len(missing)} locked key hashes are "
                f"missing: {', '.join(sorted(missing))}; expected "
                "rows retained under protection; restore a consistent "
                "backup or recreate the rows through authenticated "
                "edits and re-apply locks; restrict warehouse write "
                "permissions"
            )
    return result


def _missing(
    engine: Engine,
    config: ConnectorConfig,
    target: str,
    expected: dict[str, tuple[str, ...]],
    key: str,
) -> set[str]:
    from etl_craft.core.privacy import PrivacyDomain, fingerprint
    from etl_craft.core.protection import MAX_PROTECTION_EVENTS

    if not expected:
        return set()
    locker = LocalLocker(engine, config)
    found: set[str] = set()
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for key_hash, columns in expected.items():
        groups[columns].append(key_hash)
    with (
        locks.target(target_identity(config, target)[1], active_catalog(config)).hold(locker),
        open_warehouse(config, locker) as warehouse,
        warehouse.begin() as conn,
    ):
        session = _session(conn, warehouse_dialect(config), config, target)
        try:
            if not session.target_columns():
                return set(expected)
            for columns in groups:
                from etl_craft.dialects.business_rules import quote_output_key

                hashed = session.hash(
                    [f"t.{quote_output_key(c, session.dialect.sqlglot_dialect)}" for c in columns],
                    columns,
                )
                with session.run(
                    recovery_candidates(session.target, hashed),
                    step="doctor compare locked key membership",
                ) as rows:
                    for page in rows.scalars().partitions(MAX_PROTECTION_EVENTS):
                        found.update(
                            private
                            for value in page
                            if (private := fingerprint(key, PrivacyDomain.KEY, target, str(value)))
                            in expected
                        )
                        if expected.keys() <= found:
                            break
        finally:
            session.sweep()
    return set(expected) - found


def _session(
    conn: Connection, dialect: WarehouseDialect, config: ConnectorConfig, target: str
) -> Session:
    """Read a stored physical identity without folding its quoted component names."""
    canonical, physical = target_identity(config, target)
    session = Session(
        conn,
        dialect,
        catalog=active_catalog(config),
        action=SqlAction.SCD1_MERGE,
        target_object=canonical,
        task_run_id=0,
        params={},
    )
    session.cache_metadata(
        session.target, dialect.read_metadata(conn, dialect.erasure_metadata_table(physical))
    )
    return session
