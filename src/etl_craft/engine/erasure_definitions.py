"""One immutable project graph assembled from the versions admitted to its pipelines."""

import json

from sqlalchemy.engine import Engine

from etl_craft.core.definitions import Definition, current, using
from etl_craft.core.errors import MetadataError
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.queries import statement
from etl_craft.engine.refreshes import admitted
from etl_craft.engine.repository.config_rows import TABLES


def pinned(engine: Engine) -> tuple[Definition, dict[str, str | None]]:
    """Retain the run's image and pin other pipelines to their last passing refresh."""
    running = current.get()
    images: list[tuple[int, Definition]] = []
    selected: dict[int, Definition] = {}
    with using(None), read_snapshot(engine) as conn:
        if running is not None and running.run_id is not None:
            owner = conn.execute(
                statement(conn, "run_definition"), {"run_id": running.run_id}
            ).one()
            selected[owner.pipeline_id] = running
        pipelines = conn.execute(statement(conn, "active_pipelines")).all()
        for ref in pipelines:
            if ref.pipeline_id in selected:
                continue
            if engine.get_execution_options().get("refresh_required"):
                snapshot, _, bundle = admitted(conn, ref.pipeline_id)
            else:
                snapshot = conn.execute(
                    statement(conn, "refresh_current"), {"pipeline_id": ref.pipeline_id}
                ).scalar_one()
                bundle = None
            images.append((ref.pipeline_id, Definition.read(snapshot, bundle_id=bundle)))
    images.extend(selected.items())
    identities = {table.table: table.id_column.lower() for table in TABLES}
    bundles: dict[str, str | None] = {}
    columns: dict[str, tuple[str, ...]] = {}
    rows: dict[str, dict[object, dict[str, object]]] = {}
    for pipeline, image in images:
        bundles.update(
            {
                str(r["pipeline_code"]): image.bundle_id
                for r in image.rows.get("CFG_PIPELINES", ())
                if r["pipeline_id"] == pipeline
            }
        )
        tasks = {
            r["task_id"] for r in image.rows.get("CFG_TASKS", ()) if r["pipeline_id"] == pipeline
        }
        for table, records in image.rows.items():
            columns[table] = tuple(dict.fromkeys((*columns.get(table, ()), *image.columns[table])))
            for row in records:
                if (
                    "pipeline_id" in row
                    and table in {"CFG_PIPELINES", "CFG_TASKS", "CFG_PIPELINE_DEPENDENCY"}
                    and row["pipeline_id"] != pipeline
                ):
                    continue
                if "task_id" in row and table != "CFG_TASKS" and row["task_id"] not in tasks:
                    continue
                key = row[identities[table]]
                previous = rows.setdefault(table, {}).get(key)
                if previous is not None and table in {"CFG_TABLES", "CFG_COLUMNS"}:
                    audit = {"created_by", "create_date", "updated_by", "updated_date"}
                    if {k: v for k, v in previous.items() if k not in audit} != {
                        k: v for k, v in row.items() if k not in audit
                    }:
                        raise MetadataError(
                            f"{table} identity {key}: conflicting pinned contracts; expected "
                            "consistent table and column identities; refresh the affected pipelines"
                        )
                rows[table][key] = row
    definition = Definition.read(
        json.dumps(
            {"_version": 2}
            | {
                table: {"columns": fields, "rows": list(rows.get(table, {}).values())}
                for table, fields in columns.items()
            }
        )
    )
    return definition, bundles
