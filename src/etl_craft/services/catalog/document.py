"""The catalog as one JSON document: what the app's catalog pages render.

``catalog_document`` reads the same ``Catalog`` the static site is written from, so the two never
disagree. It is a stable, flat shape (lists of assets that name each other by label) rather than the
internal model: a page picks what it needs without walking object graphs.
"""

from __future__ import annotations

from typing import Any

from etl_craft.services.catalog.collect import Catalog, PipelineAsset, TableAsset, TaskAsset
from etl_craft.services.catalog.gaps import gap_snapshot
from etl_craft.services.operations.serialization import encode

SCHEMA = "etl-craft/catalog/1"
"""The document's schema name, as the operation documents carry theirs."""

RUNS = 10
"""How many of a pipeline's newest runs the document carries."""


def _pipeline(asset: PipelineAsset) -> dict[str, Any]:
    row = asset.row
    return {
        "code": row.pipeline_code,
        "name": row.pipeline_name,
        "description": row.description,
        "schedule": row.run_schedule,
        "auto_restart_condition": row.auto_restart_condition,
        "refresh_type": row.refresh_type,
        "sla_in_hours": row.sla_in_hours,
        "tags": list(row.tags),
        "paused": None if asset.paused is None else encode(asset.paused),
        "tasks": list(asset.tasks),
        "depends_on": [list(pair) for pair in asset.depends_on],
        "depended_on_by": list(asset.depended_on_by),
        "runs": [encode(run) for run in asset.runs[:RUNS]],
    }


def _task(label: str, asset: TaskAsset) -> dict[str, Any]:
    row = asset.row
    return {
        "label": label,
        "pipeline": row.pipeline_code,
        "code": row.task_code,
        "handler": row.handler,
        "run_condition": row.run_condition,
        "documentation": asset.documentation,
        "documentation_version": asset.documentation_version,
        "target": asset.target,
        "sources": list(asset.sources),
        "script": asset.script,
        "lineage_error": asset.lineage_error,
        "upstream": [list(pair) for pair in asset.upstream],
        "downstream": [list(pair) for pair in asset.downstream],
        "rules": list(asset.rules),
        "runs": [encode(run) for run in asset.runs[:RUNS]],
    }


def _table(catalog: Catalog, name: str, asset: TableAsset) -> dict[str, Any]:
    database, schema, table = catalog.where(name)
    return {
        "name": name,
        "database": database,
        "schema": schema,
        "table": table,
        "external": asset.external,
        "label": asset.label,
        "declared_kind": asset.declared_kind,
        "warehouse_kind": asset.warehouse_kind,
        "in_warehouse": asset.in_warehouse,
        "warehouse_checked": asset.warehouse_checked,
        "findings": list(asset.warehouse_findings),
        "writers": list(asset.writers),
        "readers": list(asset.readers),
        "rules": list(asset.rules),
        "columns": [encode(column) for column in asset.columns.values()],
    }


def catalog_document(catalog: Catalog) -> dict[str, Any]:
    """The whole catalog as plain JSON values."""
    return {
        "schema": SCHEMA,
        "generated_at": catalog.generated_at.isoformat(),
        "compared_at": catalog.compared_at.isoformat() if catalog.compared_at else None,
        "project": catalog.project_code,
        "environment": catalog.environment_label,
        "database": catalog.database,
        "sql_dialect": catalog.sql_dialect,
        "warehouse": catalog.warehouse_identity,
        "contract_version": catalog.contract_version,
        "pipelines": [_pipeline(p) for p in catalog.pipelines.values()],
        "tasks": [_task(label, t) for label, t in catalog.tasks.items()],
        "tables": [_table(catalog, name, t) for name, t in catalog.tables.items()],
        "rules": [
            {
                "id": rule_id,
                "name": rule.row.name,
                "type": rule.row.rule_type,
                "level": rule.row.business_rule_level,
                "table": rule.table,
                "task": rule.task,
                "key_column": rule.row.key_column,
                "observations": [encode(o) for o in rule.observations],
            }
            for rule_id, rule in catalog.rules.items()
        ],
        "scripts": [
            {"name": name, "tasks": list(s.tasks), "exists": s.exists}
            for name, s in catalog.scripts.items()
        ],
        "table_edges": [encode(edge) for edge in catalog.table_edges],
        "column_edges": [encode(edge) for edge in catalog.column_edges],
        "triggers": [encode(link) for link in catalog.trigger_links],
        "gaps": [encode(record) for record in gap_snapshot(catalog).records],
    }
