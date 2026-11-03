"""Idempotent, upstream-first deletion of explicitly registered direct identifiers."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from graphlib import CycleError, TopologicalSorter

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.definitions import using
from etl_craft.core.enums import Handler, ScriptKind, SqlAction
from etl_craft.core.erasure import (
    ErasedTable,
    ErasureEntry,
    ErasureReport,
    ErasureSelection,
    Unfollowed,
)
from etl_craft.core.errors import HandlerError
from etl_craft.core.faults import fault_point
from etl_craft.core.redaction import mask_text, registering
from etl_craft.dialects.business_rules import quote_output_key
from etl_craft.dialects.warehouse.erasure import resolved_column, selection_columns
from etl_craft.engine import locks
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.normalization import object_identity
from etl_craft.engine.repository.tasks import fetch_all_task_parameters
from etl_craft.engine.task_store import TaskStore
from etl_craft.handlers.erasure_delete import count_or_delete
from etl_craft.handlers.erasure_lineage import boundaries, project_graph
from etl_craft.handlers.lineage import COPY, TaskLineage, collect, table_name
from etl_craft.handlers.registry import HandlerResult, TaskContext, task_store
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.spec import WRITERS
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect, warehouse_task


def secret(config: ConnectorConfig) -> str:
    """Use the project secret shared with protection history."""
    from etl_craft.config.privacy import privacy_secret

    return privacy_secret(config)


def identity(config: ConnectorConfig, table: str, *, stored: bool = False) -> str:
    """Resolve identifiers with the warehouse's case and quoting rules."""
    dialect = warehouse_dialect(config).sqlglot_dialect
    if stored:
        table = ".".join(quote_output_key(part, dialect) for part in table.split("."))
    try:
        parts = object_identity(
            table, active_catalog(config), warehouse_dialect(config).sqlglot_dialect
        )
    except ValueError:
        raise HandlerError(
            f"table {table!r}: expected schema.table or catalog.schema.table; correct --table"
        ) from None
    return ".".join(str(part) for part in parts)


def _managed(engine: Engine, config: ConnectorConfig) -> set[str]:
    with engine.connect() as conn:
        params = fetch_all_task_parameters(conn, Handler.SQL)
        ingestion = fetch_all_task_parameters(conn, Handler.PYTHON)
    managed = {
        identity(config, p["TARGET_OBJECT"])
        for p in params.values()
        if p.get("TARGET_OBJECT") and p.get("SQL_ACTION") in WRITERS | {SqlAction.SETUP_TABLE}
    }
    # Ingestion targets are managed entry points, but are opaque when reached downstream.
    for p in ingestion.values():
        if p.get("TARGET_OBJECT") and p.get("SCRIPT_KIND") == ScriptKind.INGESTION:
            managed.add(identity(config, p["TARGET_OBJECT"], stored=True))
    return managed


def _table(config: ConnectorConfig, value: str, managed: set[str]) -> str:
    canonical = identity(config, value)
    matches = [table for table in managed if table.lower() == canonical.lower()]
    if len(matches) > 1:
        raise HandlerError(
            f"table {value}: case-distinct lineage targets {matches}; expected one unambiguous "
            "warehouse identity; give these targets distinct names before erasing"
        )
    return matches[0] if matches else canonical


@dataclass(frozen=True)
class Coverage:
    """One pinned project graph shared by every entry in an apply."""

    lineages: list[TaskLineage]
    managed: set[str]
    aggregates: set[str]


def project_coverage(engine: Engine, config: ConnectorConfig) -> Coverage:
    """Build the pinned project graph shared by every entry in an erasure pass."""
    graph, scripts = project_graph(engine, config)
    with using(graph):
        lineages = [
            scripts.get(t.task, t) for t in collect(engine, config, refresh=True, record=False)
        ]
        managed = _managed(engine, config)
        opaque_tasks, aggregates = boundaries(engine, config)
        lineages.extend(opaque_tasks)
    return Coverage(lineages, managed, aggregates)


def coverage(
    config: ConnectorConfig, entry: ErasureEntry, graph: Coverage
) -> tuple[list[tuple[str, str]], list[Unfollowed]]:
    """Follow only direct-copy edges; do not cross opaque writers or expression boundaries."""
    catalog = active_catalog(config)
    lineages, managed, aggregates = graph.lineages, graph.managed, graph.aggregates
    if entry.table not in managed:
        return [], [Unfollowed(entry.table, "Team-written or unmanaged table; no managed writer.")]
    _table(config, entry.table, managed)
    start = (table_name(entry.table.split("."), catalog), entry.column.lower())
    queue = [start]
    seen = {start}
    reached = []
    parents: dict[tuple[str, str], set[tuple[str, str]]] = {start: set()}
    blocked: dict[str, Unfollowed] = {}
    while queue:
        source, column = queue.pop(0)
        qualified = entry.table if (source, column) == start else _table(config, source, managed)
        if qualified not in managed:
            blocked[qualified] = Unfollowed(
                qualified, "Team-written or unmanaged table; etl-craft does not own its writes."
            )
            continue
        reached.append((qualified, column))
        for lineage in lineages:
            if source not in lineage.sources:
                continue
            target = lineage.target_object
            if not target:
                for opaque in lineage.targets:
                    name = _table(config, opaque, managed)
                    blocked[name] = Unfollowed(
                        name, lineage.error or "Unmanaged SQL_SCRIPT target."
                    )
                continue
            target_id = _table(config, target, managed)
            edges = [
                e for e in lineage.edges if e.source_object == source and e.source_column == column
            ]
            copies = [
                e
                for e in edges
                if e.transformation == COPY
                and table_name(target.split("."), catalog) not in aggregates
            ]
            if target_id not in managed or lineage.error or not copies or len(copies) != len(edges):
                blocked[target_id] = Unfollowed(
                    target_id,
                    lineage.error
                    or (
                        "Expression, hash, aggregate, surrogate key or opaque writer "
                        "prevents direct pass-through."
                    ),
                )
            for edge in copies:
                node = (edge.target_object, edge.target_column)
                if target_id in managed:
                    parents.setdefault(node, set()).add((source, column))
                if target_id in managed and node not in seen:
                    seen.add(node)
                    queue.append(node)
    return _ordered(config, entry, reached, parents), list(blocked.values())


def _ordered(
    config: ConnectorConfig,
    entry: ErasureEntry,
    reached: list[tuple[str, str]],
    parents: dict[tuple[str, str], set[tuple[str, str]]],
) -> list[tuple[str, str]]:
    table_parents: dict[str, set[str]] = {}
    for (table, _), sources in parents.items():
        table_parents.setdefault(table, set()).update(
            source for source, _ in sources if source != table
        )
    try:
        ordered = list(TopologicalSorter(table_parents).static_order())
    except CycleError:
        raise HandlerError(
            f"{entry.table}.{entry.column}: cyclic lineage found; expected upstream-first "
            "erasure order; correct the task sources and dependencies before erasing"
        ) from None
    allowed = set(reached)
    native = {table.lower(): table for table, _ in reached}
    reached = [
        (native[identity(config, t).lower()], c)
        for t in ordered
        for table, c in sorted(allowed)
        if identity(config, t).lower() == table.lower()
    ]
    return reached


def _selections(
    entry: ErasureEntry,
    reached: list[tuple[str, str]],
    graph: Coverage,
    unfollowed: list[Unfollowed],
) -> list[ErasureSelection]:
    grouped: dict[str, list[str]] = {}
    for table, column in reached:
        grouped.setdefault(table, []).append(column)
    excluded = graph.managed | {boundary.table for boundary in unfollowed}
    selections = []
    for table, selected in grouped.items():
        parent = table.removesuffix("__rejects") if table.endswith("__rejects") else None
        selections.append(ErasureSelection(replace(entry, table=table), tuple(selected), parent))
        rejected = table + "__rejects"
        if rejected not in excluded:
            selections.append(
                ErasureSelection(
                    replace(entry, table=rejected), tuple(selected), table, optional=True
                )
            )
    return selections


def apply_entries(
    engine: Engine,
    config: ConnectorConfig,
    entries: tuple[ErasureEntry, ...],
    *,
    dry_run: bool = False,
    store: TaskStore | None = None,
) -> ErasureReport:
    """Preflight all coverage before deleting, then commit tables in upstream-first order."""
    from etl_craft.engine.privacy import check

    with engine.connect() as conn:
        check(conn, config)
    hmac_secret = secret(config)
    tables, boundaries = [], {}
    with registering(hmac_secret, *(e.value for e in entries)):
        graph = project_coverage(engine, config) if entries else None
        plans = (
            [] if graph is None else [(entry, *coverage(config, entry, graph)) for entry in entries]
        )
        with (
            warehouse_task(),
            open_warehouse(config, LocalLocker(engine, config), hide_parameters=True) as warehouse,
        ):
            for entry, reached, unfollowed in plans:
                check_column(warehouse, config, entry.table, entry.column)
                reached[:] = [
                    (target, check_column(warehouse, config, target, column, lineage=True))
                    for target, column in reached
                ]
                assert graph is not None
                for selection in _selections(entry, reached, graph, unfollowed):
                    selection_columns(warehouse, warehouse_dialect(config), selection)
        for entry, reached, unfollowed in plans:
            assert graph is not None
            for selection in _selections(entry, reached, graph, unfollowed):
                name = selection.entry.table
                locker = store or LocalLocker(engine, config)
                with (
                    locks.target(selection.parent, active_catalog(config)).hold(locker)
                    if selection.parent
                    else nullcontext(),
                    locks.target(name, active_catalog(config)).hold(locker),
                    warehouse_task(),
                    open_warehouse(config, locker, hide_parameters=True) as warehouse,
                ):
                    if store is not None:
                        store.state()
                    count = count_or_delete(
                        engine, warehouse, config, selection, dry_run=dry_run, store=store
                    )
                    if count is not None:
                        tables.append(
                            ErasedTable(
                                mask_text(name),
                                mask_text("|".join(selection.columns)),
                                entry.key_hmac,
                                count,
                            )
                        )
                if not dry_run:
                    fault_point("erasure.after_table")
            boundaries.update(
                {
                    b.table: replace(
                        b,
                        table=mask_text(b.table),
                        reason=mask_text(b.reason),
                        remedy=mask_text(b.remedy),
                    )
                    for b in unfollowed
                }
            )
    return ErasureReport(tuple(tables), tuple(boundaries.values()), dry_run)


def check_column(
    warehouse: Engine, config: ConnectorConfig, table: str, column: str, *, lineage: bool = False
) -> str:
    """Refuse unknown or ambiguous objects without sampling personal values."""
    return resolved_column(warehouse, warehouse_dialect(config), table, column, lineage=lineage)


def run(context: TaskContext, backend: Engine | TaskStore) -> HandlerResult:
    """Reapply every active project entry using the run's pinned metadata."""
    if not isinstance(backend, Engine):
        report = backend.erasure()
    else:
        with using(context._definition):
            with backend.connect() as conn:
                entries = tuple(
                    ErasureEntry(r.table_name, r.column_name, r.subject_key, r.key_hmac)
                    for r in conn.execute(
                        statement(conn, "erasure_entries"), {"all_entries": False}
                    )
                )
            report = apply_entries(
                backend,
                context.config,
                entries,
                store=task_store(context, backend, with_warehouse=False),
            )
    return HandlerResult(
        delete_count=sum(t.rows for t in report.tables),
        variables={
            Handler.ERASURE: {
                "tables": [asdict(t) for t in report.tables],
                "unfollowed": [asdict(t) for t in report.unfollowed],
            }
        },
    )
