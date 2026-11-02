"""One stamped target MERGE for hash maintenance and its recoverable event outcome."""

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import SqlAction
from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.errors import HandlerError, SqlGuardError
from etl_craft.core.hashing import RehashResult
from etl_craft.core.protection import PROTECTION_COLUMNS, ProtectionEvent
from etl_craft.core.protection_state import RowProtection
from etl_craft.dialects.warehouse.merges import matched_merge, rehash_source
from etl_craft.engine.repository.hash_versions import save_hash_version
from etl_craft.engine.task_store import LocalTaskStore
from etl_craft.handlers.protection_recovery import committed, pending, recover
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.protection import refuse_legacy
from etl_craft.handlers.sql.protection_columns import business_columns, fingerprint
from etl_craft.handlers.sql.session import Session
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect


def rehash_target(
    engine: Engine, config: ConnectorConfig, target: str, columns: tuple[str, ...], *, dry_run: bool
) -> RehashResult:
    """Publish a new hash version only after the warehouse update has committed."""
    locker = LocalLocker(engine, config)
    store = LocalTaskStore.standalone(engine, config, locker)
    with open_warehouse(config, locker) as warehouse:
        with warehouse.begin() as conn:
            session = Session(
                conn,
                warehouse_dialect(config),
                catalog=active_catalog(config),
                action=SqlAction.SCD1_MERGE,
                target_object=target,
                task_run_id=0,
                params={},
            )
            session.protection_store = store
            try:
                refuse_legacy(session)
                if not dry_run:
                    recover(session, store)
                shape = {c.lower() for c, _ in session.target_columns()}
                if not {"hash_key", "row_id"} <= shape:
                    raise HandlerError(
                        f"{session.target}: HASH_KEY or ROW_ID is missing; "
                        "expected an existing merge target; recreate it "
                        "with SETUP_TABLE before rehashing"
                    )
                if not dry_run:
                    for column in PROTECTION_COLUMNS:
                        if column.lower() not in shape:
                            session.add_column(
                                session.target, column, session.dialect.audit_column_type(column)
                            )
                rows = session.count(
                    f"SELECT COUNT(*) FROM {session.target}", step="rows to rehash"
                )
                sql = _statement(session, columns, shape)
                if not dry_run:
                    _check(session)
                    request_id = _intent(session, columns)
                    session.run(
                        sql,
                        {"protection_request_id": request_id},
                        step="merge rehashed fingerprints",
                    )
            finally:
                session.sweep()
        if not dry_run:
            committed(store, session.target, session.protection_requests)
            if not session.protection_requests:
                with engine.begin() as engine_conn:
                    save_hash_version(engine_conn, session.target, 2)
    return RehashResult(session.target, rows, sql, dry_run)


def _statement(session: Session, columns: tuple[str, ...], original: set[str]) -> str:
    business = business_columns(tuple(c for c, _ in session.target_columns()))
    session.bindings["protection_baseline"] = RowProtection(None).encoded()
    metadata = (
        "COALESCE(t.ETL_PROTECTION,:protection_baseline)"
        if "etl_protection" in original
        else ":protection_baseline"
    )
    hashed = session.hash([f"t.{c}" for c in columns], columns)
    source = rehash_source(
        session.target, hashed, metadata, fingerprint(session, business, "t", metadata)
    )
    assignments = {
        "HASH_KEY": "s.new_hash",
        "ETL_PROTECTION": "s.protection",
        "ETL_ROW_FINGERPRINT": "s.fingerprint",
        "ETL_PROTECTION_REQUEST_ID": ":protection_request_id",
    }
    if session.dialect.supports_insert_merge(session.conn):
        return matched_merge(session.target, source, assignments)
    return session.dialect.update_from_stage(
        session.target, source, ("ROW_ID",), assignments, "TRUE"
    )


def _check(session: Session) -> None:
    business = business_columns(tuple(c for c, _ in session.target_columns()))
    hashed = fingerprint(session, business, "t", "t.ETL_PROTECTION")
    if session.count(
        f"SELECT COUNT(*) FROM {session.target} t WHERE "
        "ETL_PROTECTION IS NOT NULL AND (ETL_ROW_FINGERPRINT "
        "IS NULL OR ETL_ROW_FINGERPRINT IS DISTINCT FROM "
        f"{hashed})",
        step="check rehash in-row fingerprint",
    ):
        raise SqlGuardError(
            f"{session.target}: unobserved writes differ from "
            "in-row fingerprints; expected authenticated writers; "
            "restore a consistent backup before rehashing"
        )


def _intent(session: Session, columns: tuple[str, ...]) -> str | None:
    store = session.protection_store
    assert store is not None
    key = session.hash(["t.ROW_ID"], ("ROW_ID",))
    cells = ",".join(
        f"{session.hash([f't.{column}'], (column,))} AS cell_{i}"
        for i, column in enumerate(columns)
    )
    rows = session.run(
        f"SELECT {key} AS key_hash,{cells} FROM {session.target} t",
        step="fingerprint rehash intent",
    ).mappings()
    events = (
        ProtectionEvent(
            ProtectionKind.REHASH,
            row["key_hash"],
            columns,
            tuple(row[f"cell_{i}"] for i in range(len(columns))),
        )
        for row in rows
    )
    return pending(store, session.target, events, session.protection_requests)
