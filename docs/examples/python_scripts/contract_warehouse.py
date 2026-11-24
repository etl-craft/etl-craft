"""Read a warehouse summary without advancing an ingestion checkpoint."""

from sqlalchemy import text

from etl_craft.scripting import ScriptResult, ScriptTask


def run(task: ScriptTask) -> ScriptResult:
    """Return summary variables for a utility task, with no row count or offset."""
    with task.warehouse() as engine, engine.connect() as conn:
        summary = (
            conn.execute(
                text(
                    "SELECT count(*) AS orders, coalesce(sum(amount), 0) AS amount FROM main.orders"
                )
            )
            .mappings()
            .one()
        )
    task.logger.info("orders=%s amount=%s", summary["orders"], summary["amount"])
    return ScriptResult(variables=dict(summary))
