"""Adopt an existing warehouse table as the target of its configured SQL writer.

Adoption builds a new table with the writer's complete managed shape, fills it in one INSERT
from a SELECT over the existing table, then swaps it in. The original is dropped unless the
caller keeps it as ``<target>_pre_adopt``. Managed columns the SELECT supplies keep their values;
the others start as ``ACTIVE_FLAG='Y'``, ``DELETE_FLAG='N'``, the adoption time and the
``adopt-target`` writer. Merge targets are then rehashed, which publishes hash version 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.engine import Connection, Engine

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.adoption import AdoptResult
from etl_craft.core.enums import Handler, SqlAction
from etl_craft.core.errors import ConfigurationError, HandlerError
from etl_craft.core.protection import PROTECTION_COLUMNS
from etl_craft.core.text import qualify, split_object_ref
from etl_craft.dialects.warehouse import WarehouseDialect
from etl_craft.dialects.warehouse.row_ids import row_number
from etl_craft.engine import locks
from etl_craft.engine.project_scope import configured_project
from etl_craft.engine.repository.tasks import fetch_task_parameters
from etl_craft.engine.repository.validation import fetch_active_tasks
from etl_craft.engine.task_store import LocalTaskStore
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql import task_dialect
from etl_craft.handlers.sql.protection import refuse_replacement
from etl_craft.handlers.sql.replacement import promote
from etl_craft.handlers.sql.session import ROW_ID_COLUMN, Session
from etl_craft.handlers.sql.tables import (
    AUDIT_COLUMNS,
    IDENTITY_COLUMNS,
    check_column_names,
    create_target_shape,
    require_target,
)
from etl_craft.warehouse.connection import open_warehouse

MERGES = frozenset({SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE})
WRITERS = frozenset({SqlAction.APPEND_TABLE, SqlAction.OVERWRITE_TABLE, *MERGES})
ADOPT_WRITER = "adopt-target"
KEPT_SUFFIX = "_pre_adopt"
SUPPLIED = ("CREATE_DATE", "CREATED_BY", "UPDATE_DATE", "UPDATED_BY", "ACTIVE_FLAG", "DELETE_FLAG")
"""Managed columns the SELECT may carry over; the engine assigns every other managed column."""
DEFAULTS = {
    "CREATE_DATE": ":now",
    "UPDATE_DATE": ":now",
    "CREATED_BY": ":writer",
    "UPDATED_BY": ":writer",
    "ACTIVE_FLAG": "'Y'",
    "DELETE_FLAG": "'N'",
}


@dataclass(frozen=True)
class AdoptRequest:
    """The target, the SELECT that maps its rows, and whether the original stays."""

    target: str
    select_sql: str | None
    keep_original: bool
    dry_run: bool


@configured_project
def adopt_target(engine: Engine, config: ConnectorConfig, request: AdoptRequest) -> AdoptResult:
    """Adopt the target under its mutation lock, then rehash a merge target."""
    if config.warehouse is None:
        raise ConfigurationError("adopt-target needs a Warehouse section in craft-connector.yml")
    split_object_ref(request.target)
    catalog = active_catalog(config)
    qualified = qualify(request.target, catalog)
    with engine.connect() as conn:
        action, dialect = _writer(conn, config, qualified, catalog)
    locker = LocalLocker(engine, config)
    with (
        locks.target(qualified, "").hold(locker),
        open_warehouse(config, locker) as warehouse,
        warehouse.connect() as conn,
    ):
        session = Session(
            conn,
            dialect,
            catalog=catalog,
            action=ADOPT_WRITER,
            target_object=qualified,
            task_run_id=0,
            params={},
        )
        session.protection_store = LocalTaskStore.standalone(engine, config, locker)
        try:
            result = _adopt(session, action, request)
        finally:
            session.sweep()
        conn.commit()
    if not result.adopted or result.dry_run or action not in MERGES:
        return result
    from etl_craft.services.rehash import rehash

    rehashed = rehash(engine, config, request.target)
    return AdoptResult(**{**result.__dict__, "rehash": rehashed})


def _writer(
    conn: Connection, config: ConnectorConfig, qualified: str, catalog: str
) -> tuple[str, WarehouseDialect]:
    """Return the one write action and dialect the target's active SQL tasks agree on."""
    found: set[str] = set()
    dialects: dict[str, WarehouseDialect] = {}
    for task in fetch_active_tasks(conn):
        params = fetch_task_parameters(conn, task.task_id)
        written = (params.get("TARGET_OBJECT") or "").strip()
        if not written or qualify(written, catalog).lower() != qualified.lower():
            continue
        if task.handler != Handler.SQL:
            raise HandlerError(
                f"{qualified}: written by {task.label} ({task.handler}); adopt-target adopts "
                "targets of SQL actions only; expected SQL_ACTION writers; give the script "
                "its own table or add the columns with an explicit migration"
            )
        kind = (params.get("SQL_ACTION") or "").strip().upper()
        if kind == SqlAction.SETUP_TABLE:
            kind = (params.get("SETUP_FOR") or "").strip().upper()
        if kind not in WRITERS:
            continue
        found.add(kind)
        context = TaskContext(
            config=config,
            pipeline_id=task.pipeline_id,
            pipeline_code=task.pipeline_code,
            task_id=task.task_id,
            task_code=task.task_code,
            pipeline_run_id=0,
            task_run_id=0,
            attempt=0,
            handler=task.handler,
            refresh_type=task.refresh_type,
            task_params=params,
        )
        dialects[task.label] = task_dialect(context)
    if len(found) != 1:
        raise HandlerError(
            f"{qualified}: active SQL writers use {sorted(found) or 'no'} write action; expected "
            f"exactly one of {', '.join(sorted(WRITERS))}; configure the target's writer first"
        )
    formats = {d.spec.table_format for d in dialects.values()}
    if len(formats) > 1:
        names = ", ".join(f"{label} ({d.spec.table_format})" for label, d in dialects.items())
        raise HandlerError(
            f"{qualified}: active tasks resolve different table formats: {names}; "
            "fix TABLE_FORMAT before adopting"
        )
    return found.pop(), next(iter(dialects.values()))


def _adopt(session: Session, action: str, request: AdoptRequest) -> AdoptResult:
    """Build, fill, check and swap in the adopted table, or only plan it."""
    target = session.target
    present = {name.upper() for name, _ in require_target(session)}
    managed = ("PIPELINE_RUN_ID", *AUDIT_COLUMNS[action])
    if set(managed) <= present:
        return AdoptResult(target, action, False, request.dry_run, None, None, ())
    session.check_target_format()
    refuse_replacement(session)
    kept = f"{target}{KEPT_SUFFIX}" if request.keep_original else None
    if kept is not None and session.relation_types((kept,)):
        raise HandlerError(
            f"{target}: {kept} already exists; expected no table at the kept-original name; "
            "drop or rename it before adopting with --keep-original"
        )
    select_sql = request.select_sql or f"SELECT * FROM {target}"
    supplied, business = _select_columns(session, select_sql)
    audit = AUDIT_COLUMNS[action]
    candidate = Session(
        session.conn,
        session.dialect,
        catalog=session.catalog,
        action=ADOPT_WRITER,
        target_object=session.scratch("adopt", persistent=True),
        task_run_id=0,
        params={},
    )
    mapping = (
        tuple(c for c in audit if c in DEFAULTS and c in supplied),
        tuple(c for c in audit if c in DEFAULTS and c not in supplied),
    )
    names, values = _insert_parts(session, business, supplied, audit)
    if request.dry_run:
        insert = (
            f"INSERT INTO {candidate.target} ({', '.join(names)}) "
            f"SELECT {', '.join(values)} FROM ({select_sql}) s"
        )
        return AdoptResult(target, action, True, True, None, kept, (insert,), *mapping)
    stage = session.create_scratch(
        session.scratch("stage"),
        f"SELECT {', '.join(business)} FROM ({select_sql}) etl_src WHERE 1 = 0",
        step="stage the adopted business columns",
    )
    create_target_shape(candidate, stage, audit)
    session.drop(stage)
    source = session.create_scratch(
        session.scratch("adopt_rows"), select_sql, step="stage the exact adoption rows"
    )
    count = session.count(f"SELECT COUNT(*) FROM {source}", step="count adopted source rows")
    base = session.row_id_base(count, existing="ROW_ID" in present)
    insert = (
        f"INSERT INTO {candidate.target} ({', '.join(names)}, ROW_ID) "
        f"SELECT {', '.join(values)}, {row_number(base)} FROM {source} s"
    )
    params = {"now": datetime.now(UTC), "writer": ADOPT_WRITER}
    session.run(insert, params, step="copy the existing rows")
    _check_values(session, candidate.target, audit)
    rows = session.count(f"SELECT COUNT(*) FROM {candidate.target}", step="count adopted rows")
    promote(session, candidate.target, existing=True, keep_as=kept)
    return AdoptResult(target, action, True, False, rows, kept, (insert,), *mapping)


def _select_columns(session: Session, select_sql: str) -> tuple[dict[str, str], list[str]]:
    """Return the SELECT's supplied managed columns and its business columns."""
    shape = session.describe_select(select_sql)
    if shape is None:
        stage = session.create_scratch(
            session.scratch("stage"),
            f"SELECT * FROM ({select_sql}) etl_src WHERE 1 = 0",
            step="read the adoption SELECT's columns",
        )
        shape = session.columns(stage)
        session.drop(stage)
    assigned = sorted(
        name.upper()
        for name, _ in shape
        if name.upper() in {*IDENTITY_COLUMNS, "HASH_KEY", ROW_ID_COLUMN, *PROTECTION_COLUMNS}
    )
    if assigned:
        raise HandlerError(
            f"{session.target}: the adoption SELECT returns {', '.join(assigned)}; expected only "
            f"business columns and optionally {', '.join(SUPPLIED)}; the engine assigns the "
            "others; pass --select naming the columns to keep"
        )
    supplied = {name.upper(): name for name, _ in shape if name.upper() in SUPPLIED}
    business = [name for name, _ in shape if name.upper() not in SUPPLIED]
    check_column_names(session, business)
    return supplied, business


def _insert_parts(
    session: Session, business: list[str], supplied: dict[str, str], audit: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """Name the inserted columns and their values: supplied managed values, else defaults."""
    names = list(business)
    values = [f"s.{name}" for name in business]
    for column in (c for c in audit if c in DEFAULTS):
        names.append(column)
        source = f"s.{supplied[column]}" if column in supplied else DEFAULTS[column]
        values.append(f"CAST({source} AS {session.dialect.audit_column_type(column)})")
    return names, values


def _check_values(session: Session, candidate: str, audit: tuple[str, ...]) -> None:
    """Refuse supplied flags or stamps the writer cannot maintain, before the swap."""
    checks = [
        f"{flag} IS NULL OR {flag} NOT IN ('Y', 'N')"
        for flag in ("ACTIVE_FLAG", "DELETE_FLAG")
        if flag in audit
    ] + [f"{stamp} IS NULL" for stamp in SUPPLIED[:4] if stamp in audit]
    if not checks:
        return
    invalid = session.count(
        f"SELECT COUNT(*) FROM {candidate} WHERE " + " OR ".join(f"({c})" for c in checks),
        step="check adopted flags and stamps",
    )
    if invalid:
        session.drop(candidate)
        raise HandlerError(
            f"{session.target}: {invalid} adopted row(s) have NULL or invalid managed values "
            f"({' OR '.join(checks)}); expected Y/N flags and non-NULL stamps; correct the "
            "--select mapping (or omit those columns to use the defaults) and retry; the "
            "original table is unchanged"
        )
