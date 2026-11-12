"""Catalog-only lineage states and mapping descriptions, without executing task code."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.engine import Connection

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums import Handler, ScriptKind, SqlAction, YesNo
from etl_craft.core.enums_lineage import LineageState
from etl_craft.engine.queries import statement
from etl_craft.handlers.sql.spec import read_action
from etl_craft.handlers.sql.tables import AUDIT_COLUMNS
from etl_craft.services.operations.serialization import encode

if TYPE_CHECKING:
    from etl_craft.services.catalog.collect import Catalog, TaskAsset


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
                "reason": "DROP_TABLE has no SELECT; lineage is not derived",
            }
        return {
            "state": LineageState.UNAVAILABLE if task.lineage_error else LineageState.DERIVED,
            "reason": task.lineage_error,
        }
    if task.row.handler == Handler.PYTHON:
        if task.params.get("SCRIPT_KIND") != ScriptKind.INGESTION:
            reason = "Python utility scripts run arbitrary code; lineage is not derived"
        elif task.params.get("LINEAGE_SOURCE"):
            return {
                "state": LineageState.DECLARED,
                "reason": "The engine does not verify declared lineage against the script",
            }
        else:
            reason = "This ingestion task declares no LINEAGE_SOURCE; add it to document its source"
    elif task.row.handler == Handler.SQL_SCRIPT:
        reason = "SQL_SCRIPT runs unmanaged statements; lineage is not derived"
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

    check_sources(catalog)
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
        if task.row.handler != Handler.SQL or task.lineage_error:
            continue
        for source in task.sources:
            table = catalog.tables[source]
            declared = any(column.declared_type for column in table.columns.values())
            derived = any(
                catalog.tasks[writer].row.handler == Handler.SQL
                and not catalog.tasks[writer].lineage_error
                for writer in table.writers
            )
            if not declared and not derived:
                task.missing_sources = (source,)
                task.lineage_error = (
                    f"source {source}: schema missing; declare its active "
                    "columns in columns.csv and rebuild the catalog"
                )
                break
