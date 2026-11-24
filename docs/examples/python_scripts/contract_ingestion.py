"""Ingest a bounded batch from a team's JSON delivery file into an existing table."""

import json

from sqlalchemy import text

from etl_craft.scripting import Offset, ScriptResult, ScriptTask


def run(task: ScriptTask) -> ScriptResult:
    """Return the measured batch size and last source ID for an ingestion task."""
    source = task.config.host_dir / "orders.json"
    after = task.offset.value if task.offset else 0
    rows = [row for row in json.loads(source.read_text()) if row["id"] > after]
    with task.warehouse() as engine, engine.begin() as conn:
        for row in rows:
            # Replaying this batch after a failed attempt replaces the same business key.
            conn.execute(text("DELETE FROM main.orders WHERE id = :id"), {"id": row["id"]})
            conn.execute(
                text(
                    "INSERT INTO main.orders "
                    "(id, amount, pipeline_id, pipeline_run_id, task_run_id) "
                    "VALUES (:id, :amount, :pipeline, :run, :task)"
                ),
                dict(
                    row, pipeline=task.pipeline_id, run=task.pipeline_run_id, task=task.task_run_id
                ),
            )
    return ScriptResult(row_count=len(rows), offset=Offset.number(rows[-1]["id"]) if rows else None)
