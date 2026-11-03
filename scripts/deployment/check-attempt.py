"""Assert one completed attempt for an exact deployment smoke run."""

import sys
import time

from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.dialects.engine import build_engine

run_key, owner = sys.argv[1:]
engine = build_engine(load_config("craft-connector.yml"))
deadline = time.monotonic() + 90
while True:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT a.status AS status, a.target_count AS target_count, "
                    "a.owner_id AS owner_id FROM AUD_TASK_ATTEMPTS a "
                    "JOIN AUD_TASK_RUN_LOG t ON t.task_run_id=a.task_run_id "
                    "JOIN AUD_PIPELINES_RUN_LOG r ON r.pipeline_run_id=t.pipeline_run_id "
                    "WHERE r.run_key=:key"
                ),
                {"key": run_key},
            )
            .mappings()
            .all()
        )
    if len(rows) == 1 and rows[0]["status"] == "SUCCESS":
        assert rows[0]["target_count"] == 7
        assert str(rows[0]["owner_id"]) == owner
        break
    assert time.monotonic() < deadline and all(row["status"] != "FAILED" for row in rows), rows
    time.sleep(0.25)
engine.dispose()
print(f"{run_key}: exactly one attempt completed on agent {owner}")
