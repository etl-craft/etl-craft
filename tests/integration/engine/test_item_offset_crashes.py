"""Real process loss retains provisional positions without publishing a task checkpoint."""

import json
from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.engine.repository.offsets import fetch_task_offset
from fixtures.landing import cli_writer, run_writer
from fixtures.lock_fencing import expire_leases
from fixtures.metadata import add_pipeline, start_run
from fixtures.sql_warehouse import warehouses


@pytest.mark.chaos
@warehouses("duckdb")
@pytest.mark.parametrize("point", ["item.after_result", "items.after_success"])
def test_item_positions_survive_task_process_loss(engine_db, sql_world, monkeypatch, point):
    w = sql_world
    w.engine_db = engine_db.engine
    profile = engine_db.config.engine
    if engine_db.engine.dialect.name == "sqlite":
        profile = replace(profile, jdbc_url="jdbc:sqlite:" + engine_db.engine.url.database)
    w.config = replace(w.config, engine=profile)
    with w.engine_db.begin() as conn:
        w.pipeline_id = add_pipeline(conn, "P", refresh_type="INCREMENTAL")
        w.pipeline_run_id = start_run(conn, w.pipeline_id)
    project, token = cli_writer(w)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token)
    path = project.config.python_scripts_dir / "load.py"
    path.write_text("""from etl_craft.scripting import Offset, ScriptResult

def run(task):
    committed = task.offset.value if task.offset else {"0": 0, "1": 0}
    def load(key):
        before = committed[key]
        rows = ({"id": int(key), "name": str(before)},)
        return ScriptResult(task.replace_landing(iter(rows), item_key=key),
                            Offset.partitions({key: before + 1}))
    return task.fan_out(["0", "1"], load, max_parallel=1, max_items=4)
""")
    try:
        code, output = run_writer(w, project, "pipelines", "refresh", timeout=90)
        assert code == 0, output
        code, output = run_writer(w, project, "run", "--pipeline-code", "P", timeout=90)
        assert code == 0, output
        with w.engine_db.connect() as conn:
            before = fetch_task_offset(conn, project.task_id)
        assert json.loads(before.offset_value) == {"0": 1, "1": 1}
        code, output = run_writer(
            w, project, "run", "--pipeline-code", "P", fault=point + ":kill", timeout=90
        )
        assert code != 0, output
        with w.engine_db.connect() as conn:
            assert fetch_task_offset(conn, project.task_id) == before
            run = conn.execute(
                text("SELECT MAX(PIPELINE_RUN_ID) FROM AUD_PIPELINES_RUN_LOG")
            ).scalar_one()
        expire_leases(w.engine_db)
        code, output = run_writer(
            w,
            project,
            "run",
            "--pipeline-code",
            "P",
            "--run-id",
            str(run),
            "--task-code",
            "loader",
            "--rerun",
            "--reason",
            "Retry injected process loss",
            timeout=90,
        )
        assert code == 0, output
        with w.engine_db.connect() as conn:
            assert json.loads(fetch_task_offset(conn, project.task_id).offset_value) == {
                "0": 2,
                "1": 2,
            }
            rows = conn.execute(
                text(
                    "SELECT i.ITEM_KEY AS key,i.STATUS AS status,i.OFFSET_POSITION AS position "
                    "FROM AUD_TASK_ITEMS i JOIN AUD_TASK_RUN_LOG t "
                    "ON t.TASK_RUN_ID=i.TASK_RUN_ID WHERE t.PIPELINE_RUN_ID=:run "
                    "ORDER BY i.ITEM_RECORD_ID"
                ),
                {"run": run},
            ).all()
        assert any(r.key == "0" and r.status == "SKIPPED" and r.position == 2 for r in rows)
        assert sum(r.key == "0" and r.status == "RUNNING" for r in rows) == 1
        assert w.rows(f"SELECT id,name FROM {w.name('landing')} ORDER BY id") == [
            (0, "1"),
            (1, "1"),
        ]
    finally:
        for command in reversed(project.processes):
            command.close()
