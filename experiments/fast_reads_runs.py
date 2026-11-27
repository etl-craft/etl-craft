"""Run-read experiment against the same 5,000-pipeline seed as the browser."""

import json
from concurrent.futures import ThreadPoolExecutor
from statistics import median, quantiles
from threading import Barrier
from time import perf_counter

from sqlalchemy import bindparam
from etl_craft.engine.queries import statement


def sample(label, action, repeats=9):
    timings = []
    for _ in range(repeats):
        start = perf_counter()
        rows = action()
        timings.append((perf_counter() - start) * 1000)
    print("run sample", label, "rows", len(rows), "bytes",
          len(json.dumps([dict(row._mapping) for row in rows], default=str).encode()),
          "median ms", round(median(timings), 2), "max ms", round(max(timings), 2), flush=True)
    return rows


def benchmark(engine):
    with engine.begin() as conn:
        # Spread 25 rounds uniformly over the 730-day model window.
        conn.exec_driver_sql("""
            UPDATE AUD_PIPELINES_RUN_LOG
               SET RUN_DATE = date('now', printf('-%d days', (24 - (PIPELINE_RUN_ID-1)/5000)*30)),
                   START_DATE = datetime('now', printf('-%d days', (24 - (PIPELINE_RUN_ID-1)/5000)*30)),
                   END_DATE = datetime('now', printf('-%d days', (24 - (PIPELINE_RUN_ID-1)/5000)*30), '+1 second')
        """)
        conn.exec_driver_sql("""
            UPDATE AUD_PIPELINES_RUN_LOG SET STATUS='IN-PROGRESS', END_DATE=NULL
            WHERE PIPELINE_RUN_ID > 124950
        """)
        conn.exec_driver_sql("""
            INSERT INTO AUD_TASK_ATTEMPTS
                (TASK_RUN_ID, ATTEMPT_NUMBER, STATUS, STARTED_AT, ENDED_AT, POOL)
            SELECT t.TASK_RUN_ID, 1, CASE WHEN t.PIPELINE_RUN_ID > 124950 THEN 'RUNNING' ELSE 'SUCCESS' END,
                   r.START_DATE, r.END_DATE, CASE WHEN t.TASK_RUN_ID % 101=0 THEN 'rare' ELSE 'default' END
            FROM AUD_TASK_RUN_LOG t JOIN AUD_PIPELINES_RUN_LOG r USING (PIPELINE_RUN_ID)
            WHERE t.TASK_RUN_ID % 10=0 OR r.PIPELINE_ID=1 OR t.PIPELINE_RUN_ID > 124950
        """)

    live = """
        SELECT PIPELINE_RUN_ID AS id, PIPELINE_ID AS pipeline, STATUS AS status
        FROM AUD_PIPELINES_RUN_LOG WHERE STATUS IN ('QUEUED','IN-PROGRESS')
        ORDER BY PIPELINE_RUN_ID DESC LIMIT 50
    """
    recent = """
        SELECT PIPELINE_RUN_ID AS id, END_DATE AS ended, STATUS AS status
        FROM AUD_PIPELINES_RUN_LOG
        WHERE END_DATE >= datetime('now','-1 day')
        ORDER BY END_DATE DESC, PIPELINE_RUN_ID DESC LIMIT 50
    """
    with engine.connect() as conn:
        history = statement(conn, "pipeline_run_history").bindparams(
            bindparam("pipeline_ids", expanding=True), bindparam("statuses", expanding=True))
        ids = list(conn.exec_driver_sql("SELECT PIPELINE_ID FROM CFG_PIPELINES").scalars())
        params = dict(pipeline_ids=ids, statuses=["SUCCESS"], run_id=None, before=None,
                      status_filter=0, pool=None, agent=None, failure_class=None, limit=50)
        for label, overrides in [
            ("history", {}), ("keyset", {"before": 5000}), ("rare pool", {"pool": "rare"}),
            ("absent pool", {"pool": "absent"}), ("grid headers", {"pipeline_ids": [1], "limit": 25})
        ]:
            rows = sample(label, lambda: conn.execute(history, params | overrides).all(),
                          repeats=3 if label == "absent pool" else 9)
        cells = statement(conn, "history_cells").bindparams(bindparam("run_ids", expanding=True))
        sample("grid cells", lambda: conn.execute(cells, {"run_ids": [r.pipeline_run_id for r in rows]}).all())
        sample("active feed", lambda: conn.exec_driver_sql(live).all())
        sample("recent feed", lambda: conn.exec_driver_sql(recent).all())
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE INDEX fast_reads_recent ON AUD_PIPELINES_RUN_LOG (END_DATE DESC, PIPELINE_RUN_ID DESC)"
        )
        sample("recent feed with index", lambda: conn.exec_driver_sql(recent).all())
    for cadence in (15, 5, 3):
        results = []
        with ThreadPoolExecutor(max_workers=50) as pool:
            from time import sleep
            for wave in range(2):
                if wave:
                    sleep(max(0, scheduled - perf_counter()))
                scheduled = perf_counter() + cadence
                barrier = Barrier(50)
                def poll(_):
                    barrier.wait(timeout=10)
                    start = perf_counter()
                    with engine.connect() as conn:
                        assert len(conn.exec_driver_sql(live).all()) == 50
                    return (perf_counter() - start) * 1000
                results.extend(pool.map(poll, range(50)))
        print("run sample poll", cadence, "seconds", len(results), "samples, p95 ms",
              round(quantiles(results, n=20)[18], 2), flush=True)
