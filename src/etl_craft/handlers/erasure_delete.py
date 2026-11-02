"""One erased table's write-ahead intent, atomic warehouse deletion and final outcome."""

import json
from collections.abc import Iterator, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import SqlAction
from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.erasure import ErasureSelection
from etl_craft.core.errors import HandlerError, SqlGuardError
from etl_craft.core.protection import ProtectionEvent
from etl_craft.dialects.business_rules import quote_output_key
from etl_craft.dialects.warehouse.erasure import ErasureDelete, deletion_plan, selection_columns
from etl_craft.engine.task_store import LocalTaskStore, TaskStore
from etl_craft.handlers.protection_recovery import committed, pending, recover
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.protection import refuse_legacy
from etl_craft.handlers.sql.session import Session
from etl_craft.warehouse.connection import warehouse_dialect


def count_or_delete(
    engine: Engine,
    warehouse: Engine,
    config: ConnectorConfig,
    selection: ErasureSelection,
    *,
    dry_run: bool,
    store: TaskStore | None,
) -> int | None:
    """Keep keys out of errors, logs and events, including failed warehouse statements."""
    dialect = warehouse_dialect(config)
    selected = selection_columns(warehouse, dialect, selection)
    if not selected:
        return None
    try:
        with warehouse.begin() as conn:
            plan = deletion_plan(conn, dialect, selection.entry.table, selected)
            session = Session(
                conn,
                dialect,
                catalog=active_catalog(config),
                action=SqlAction.DELETE_ROWS,
                target_object=plan.target,
                task_run_id=0,
                params={},
            )
            session.cache_metadata(
                session.target,
                dialect.read_metadata(conn, dialect.erasure_metadata_table(plan.native)),
            )
            locker = LocalLocker(engine, config)
            event_store = (
                store.erasure_target(plan.target)
                if isinstance(store, LocalTaskStore)
                else LocalTaskStore.standalone(engine, config, locker)
            )
            session.protection_store = event_store
            params = {"erasure_value": selection.entry.value}
            try:
                refuse_legacy(session)
                if not dry_run:
                    recover(session, event_store)
                count = int(conn.execute(text(plan.count), params).scalar_one())
                if not dry_run and count:
                    names = {c.lower(): c for c, _ in session.target_columns()}
                    keys = tuple(
                        dict.fromkeys(
                            (*((names["row_id"],) if "row_id" in names else ()), *selected)
                        )
                    )
                    _intent(session, plan, keys, _keys(session, selected), params)
                    conn.execute(text(plan.statement(keys, dialect, conn)), params)
            finally:
                session.sweep()
        if not dry_run:
            committed(event_store, session.target, session.protection_requests)
        return count
    except SqlGuardError:
        raise
    except (SQLAlchemyError, HandlerError) as error:
        raise HandlerError(
            f"{selection.entry.table} columns {selected}, entry {selection.entry.key_hmac}: "
            f"row-level deletion failed ({type(error).__name__}); expected a table supporting "
            "transactional DELETE (Iceberg format version 2 "
            "or later); correct its format/permissions "
            "or restore the connection and retry erasure. Parameters are withheld"
        ) from None


def _keys(session: Session, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Retain the protected target's business-key identity even when erasing another column."""
    columns = {c.lower(): c for c, _ in session.target_columns()}
    if "etl_protection" in columns:
        rows = session.run(
            f"SELECT ETL_PROTECTION AS protection FROM {session.target} "
            "WHERE ETL_PROTECTION IS NOT NULL",
            step="read erasure key contract",
        )
        for row in rows:
            raw = json.loads(row.protection)
            if raw.get("contract"):
                return tuple(columns[c.lower()] for c in raw["contract"][1])
    return tuple(columns[c.lower()] for c in fallback)


def _intent(
    session: Session,
    plan: ErasureDelete,
    physical: tuple[str, ...],
    business: tuple[str, ...],
    params: Mapping[str, object],
) -> None:
    """Prove exact row absence and retain whole-key deletion evidence for doctor."""
    from itertools import chain

    def events(keys: tuple[str, ...], whole: bool) -> Iterator[ProtectionEvent]:
        hashed = session.hash(
            [f"t.{quote_output_key(c, session.dialect.sqlglot_dialect)}" for c in keys], keys
        )
        sql = (
            plan.fully_selected_hashes(hashed, keys, session.dialect)
            if whole
            else plan.hashes(hashed)
        )
        for key in session.run(sql, params, step="fingerprint exact erasure keys").scalars():
            yield ProtectionEvent(ProtectionKind.ERASURE, str(key), keys, (None,) * len(keys))

    store = session.protection_store
    assert store is not None
    pending(
        store,
        session.target,
        chain(events(physical, False), events(business, True) if business != physical else ()),
        session.protection_requests,
    )
