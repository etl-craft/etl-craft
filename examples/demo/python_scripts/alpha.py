"""Land two fixture rows per run, returning the last numeric identifier as the offset.

Four records cover a valid row, a hard-deleted test row, an unknown agent with a long
call, and an invalid rating. Later batches repeat those cases under new identifiers.
"""

from datetime import date, timedelta

from sqlalchemy import text

from etl_craft.scripting import Offset, ScriptResult, ScriptTask


def interaction(n: int) -> dict[str, str | int]:
    """Return Client Alpha's interaction ``n``, every field as its desk exports it."""
    case = (n - 1) % 4
    agent = ("A01", "TEST", "A99", "A02")[case]
    return {
        "interaction_id": n,
        "agent_code": agent,
        "support_area": "billing",
        "contact_date": (date(2026, 9, 1) + timedelta(days=n % 28)).isoformat(),
        "status": "resolved" if n % 4 else "pending",
        "duration_seconds": "630" if case == 2 else "30",
        "rating": "6" if case == 3 else "3",
    }


def run(task: ScriptTask) -> ScriptResult:
    """Land the next interactions after the stored offset."""
    last = int(task.offset.value) if task.offset else 0
    count = int(task.input_params.get("rows", 2))
    table = task.table("lnd.client_alpha")
    rows = [interaction(n) for n in range(last + 1, last + count + 1)]
    with task.warehouse() as engine, engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {table} (interaction_id BIGINT, "
                "agent_code VARCHAR(100), support_area VARCHAR(100), contact_date VARCHAR(100), "
                "status VARCHAR(100), duration_seconds VARCHAR(100), rating VARCHAR(100), "
                "pipeline_run_id BIGINT, pipeline_id BIGINT, task_run_id BIGINT)"
            )
        )
        for row in rows:
            conn.execute(
                text(
                    f"INSERT INTO {table} VALUES (:interaction_id, :agent_code, :support_area, "
                    ":contact_date, :status, :duration_seconds, :rating, "
                    ":pipeline_run_id, :pipeline_id, :task_run_id)"
                ),
                {
                    **row,
                    "pipeline_run_id": task.pipeline_run_id,
                    "pipeline_id": task.pipeline_id,
                    "task_run_id": task.task_run_id,
                },
            )
    task.logger.info("landed Client Alpha interactions %d to %d", last + 1, last + count)
    return ScriptResult(row_count=len(rows), offset=Offset.number(last + count))
