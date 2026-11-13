"""Catalog-only lineage states and mapping descriptions, without executing task code."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.engine import Connection

from etl_craft.config import ConnectorConfig
from etl_craft.config.project import sql_script
from etl_craft.config.targets import parse_warehouse_url
from etl_craft.core.enums import Handler, ScriptKind, SqlAction, YesNo
from etl_craft.core.enums_lineage import LineageState
from etl_craft.core.errors import EtlCraftError, MetadataError
from etl_craft.dialects.business_rules import expand_scope
from etl_craft.engine.queries import statement
from etl_craft.handlers.lineage import trace
from etl_craft.handlers.lineage_mapping import TraceContext
from etl_craft.handlers.mapping_logic import MappingLogic, rule_predicates
from etl_craft.handlers.sql.spec import read_action
from etl_craft.handlers.sql.tables import AUDIT_COLUMNS
from etl_craft.services.operations.serialization import encode
from etl_craft.warehouse.connection import warehouse_dialect

if TYPE_CHECKING:
    from etl_craft.services.catalog.collect import Catalog, RuleAsset, TaskAsset


def lineage(task: TaskAsset) -> dict[str, str | None]:
    """Distinguish an expected SQL gap from an intentional limit of arbitrary code."""
    if task.row.handler == Handler.SQL:
        if task.row.active_flag == YesNo.NO:
            return {
                "state": LineageState.UNAVAILABLE,
                "reason": "Inactive SQL task was not parsed; activate it and rebuild the catalog",
            }
        if task.params.get("SQL_ACTION") and read_action(task.params) == SqlAction.DROP_TABLE:
            return {
                "state": LineageState.UNAVAILABLE,
                "reason": "Drop table has no SELECT; lineage is not derived",
            }
        return {
            "state": LineageState.UNAVAILABLE if task.lineage["reason"] else LineageState.DERIVED,
            "reason": task.lineage["reason"],
        }
    if task.row.handler == Handler.PYTHON:
        if task.params.get("SCRIPT_KIND") != ScriptKind.INGESTION:
            reason = "Python utility scripts run arbitrary code; lineage is not derived"
        elif task.params.get("LINEAGE_SOURCE"):
            return {
                "state": LineageState.DECLARED,
                "reason": "The engine doesn't verify declared lineage against the script.",
            }
        else:
            reason = "This ingestion task declares no LINEAGE_SOURCE; add it to document its source"
    elif task.row.handler == Handler.SQL_SCRIPT:
        reason = "SQL scripts run unmanaged statements; lineage is not derived"
    else:
        reason = f"{task.row.handler} does not declare data movement; lineage is not derived"
    return {"state": LineageState.UNAVAILABLE, "reason": reason}


def mapping(task: TaskAsset) -> dict[str, object]:
    """Expose SELECT operators and recorded column edges, with the engine's write contract."""
    action = (
        read_action(task.params)
        if task.row.handler == Handler.SQL and task.params.get("SQL_ACTION")
        else None
    )
    keys = (
        "MERGE_KEY",
        "MERGE_COMPARE_COLUMNS",
        "MERGE_DEDUPE_ORDER",
    )
    return {
        "steps": [encode(step) for step in task.mapping]
        if lineage(task)["state"] != LineageState.UNAVAILABLE
        else [],
        "edges": [encode(edge) for edge in task.column_edges]
        if lineage(task)["state"] != LineageState.UNAVAILABLE
        else [],
        "write": {
            "action": action,
            "managed_columns": list(AUDIT_COLUMNS.get(action, ())) if action else [],
            "keys": {key: task.params[key] for key in keys if key in task.params},
        },
        "source": task.params.get("LINEAGE_SOURCE"),
    }


def declare_columns(task: TaskAsset) -> None:
    """Attach only explicitly declared ingestion edges to the external source."""
    from etl_craft.handlers.declared_lineage import columns
    from etl_craft.handlers.lineage import Edge

    if task.params.get("SCRIPT_KIND") != ScriptKind.INGESTION or not task.params.get(
        "LINEAGE_SOURCE"
    ):
        return
    if task.target:
        task.column_edges = [
            Edge(task.target, target.lower(), task.sources[0], source, "declared", task.label)
            for source, target in columns(task.params, task.row.handler, task.label)
        ]


def complete_definitions(catalog: Catalog, config: ConnectorConfig) -> None:
    """Read effective execution limits once while building the catalog snapshot."""
    from etl_craft.execution.limits import task_timeout_seconds
    from etl_craft.execution.retries import task_retry_policy

    catalog.sql_dialect = warehouse_dialect(config).sqlglot_dialect if config.warehouse else None
    catalog.gate_wait_minutes = config.limits.gate_wait_minutes
    for task in catalog.tasks.values():
        policy = task_retry_policy(task.params, config, task.row.handler)
        task.execution = {
            "retries": policy.retries,
            "retry_on": policy.retry_on,
            "timeout_seconds": task_timeout_seconds(task.params, config),
        }


def definition_parameters(conn: Connection) -> dict[int, dict[str, str]]:
    """Catalog inactive definitions too, without relaxing executable task metadata checks."""
    params: dict[int, dict[str, str]] = {}
    for row in conn.execute(statement(conn, "catalog_definition_parameters")):
        params.setdefault(row.task_id, {})[row.parameter_name] = row.parameter_value
    return params


def check_sources(catalog: Catalog) -> None:
    """Keep missing SQL source contracts as actionable gaps."""
    for task in catalog.tasks.values():
        if task.row.handler != Handler.SQL or task.lineage["reason"]:
            continue
        for source in task.sources:
            table = catalog.tables[source]
            declared = any(column.declared_type for column in table.columns.values())
            derived = any(
                catalog.tasks[writer].row.handler == Handler.SQL
                and bool(catalog.tasks[writer].column_edges)
                and lineage(catalog.tasks[writer])["state"] == LineageState.DERIVED
                for writer in table.writers
            )
            observed = table.in_warehouse and any(
                column.warehouse_present and column.warehouse_type
                for column in table.columns.values()
            )
            missing = (
                sorted(
                    {
                        edge.source_column
                        for edge in task.column_edges
                        if edge.source_object == source
                        and edge.source_column
                        and (
                            edge.source_column not in table.columns
                            or not table.columns[edge.source_column].warehouse_present
                        )
                    }
                )
                if observed
                else []
            )
            if missing:
                task.missing_sources = (source,)
                task.lineage["reason"] = (
                    f"source {source}: columns {missing!r} not found in the observed schema; "
                    "expected every referenced column; correct SELECT or the source schema "
                    "and rebuild the catalog"
                )
                break
            if not declared and not derived and not observed:
                task.missing_sources = (source,)
                task.lineage["reason"] = (
                    f"source {source}: schema missing; declare its active "
                    "columns in columns.csv or rebuild with --with-warehouse to read its schema"
                )
                break


def comparison_identity(catalog: Catalog, config: ConnectorConfig, requested: bool) -> None:
    """Identify the inputs without exporting SQL, credentials or connection strings."""
    inputs: list[object] = []
    for task in catalog.tasks.values():
        params = task.params
        content = params.get("SELECT_QUERY", "")
        if params.get("SCRIPT_FILE") and not task.script:
            try:
                content = sql_script(config, params["SCRIPT_FILE"]).read_text(encoding="utf-8")
            except (EtlCraftError, OSError) as error:
                content = f"unavailable: {type(error).__name__}"
        inputs.append((task.label, task.target, params.get("SQL_ACTION"), content))
    inputs.extend(
        (
            table.name,
            table.declared_kind,
            [
                (c.name, c.declared_type, c.declared_nullable)
                for c in table.columns.values()
                if c.declared
            ],
        )
        for table in catalog.tables.values()
    )
    catalog.contract_version = hashlib.sha256(
        json.dumps(inputs, sort_keys=True).encode()
    ).hexdigest()
    if config.warehouse:
        location = parse_warehouse_url(config.warehouse.jdbc_url)
        catalog.warehouse_identity = (
            f"{config.warehouse.name}: {location.dialect} / "
            f"{location.host or 'local'}:{location.port or 'default'} / "
            f"{location.path or location.database} / catalog {catalog.database or 'absent'}"
        )
    if requested and any(not table.external for table in catalog.tables.values()):
        catalog.compared_at = datetime.now(UTC)
        if config.warehouse is None:
            for table in catalog.tables.values():
                table.warehouse_findings.append(
                    "comparison unavailable: no warehouse connection configured"
                )


def rule_logic(catalog: Catalog, rule: RuleAsset) -> tuple[MappingLogic, ...]:
    """Use the shared scope expander and lineage trace for a rule's own SELECT."""
    schemas = {
        name: {
            column.name: column.declared_type or column.data_type or "UNKNOWN"
            for column in table.columns.values()
        }
        for name, table in catalog.tables.items()
        if table.columns and not table.external
    }
    try:
        traced = trace(
            expand_scope(rule.row.sql, rule.table),
            TraceContext(rule.table, catalog.sql_dialect, catalog.database, schemas),
        )
    except MetadataError as error:
        return (MappingLogic(f"{rule.row.sql} — {error}", ()),)
    return rule_predicates(traced.tree, catalog.sql_dialect)
