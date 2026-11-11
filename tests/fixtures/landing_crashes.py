"""Crash oracles shared by local and cloud warehouses."""

import json
import os
from uuid import uuid4

from sqlalchemy import text

from fixtures.landing import cli_writer, run_writer
from fixtures.lock_fencing import expire_leases


def check_landing_exit(w, monkeypatch, point):
    target = "landing_" + uuid4().hex[:12]
    monkeypatch.setenv(
        "ETL_CRAFT_TEST_PRIVACY_SECRET",
        os.environ.get("ETL_CRAFT_TEST_PRIVACY_SECRET", "landing-test-only"),
    )
    project, token = cli_writer(w, target)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token)
    try:
        code, output = run_writer(w, project, "pipelines", "refresh", timeout=90)
        assert code == 0, output
        code, output = run_writer(
            w, project, "run", "--reason", "test requested run", "--pipeline-code", "P", timeout=120
        )
        assert code == 0, output
        before = w.rows(f"SELECT id,name,task_run_id FROM {w.name(target)} WHERE item_key='1'")
        assert len(before) == 1
        with w.engine_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                    "VALUES (:id,'INPUT_PARAMS',:params)"
                ),
                {"id": project.task_id, "params": json.dumps({"keys": ["0"], "value": "new"})},
            )
        assert run_writer(w, project, "pipelines", "refresh", timeout=90)[0] == 0
        code, output = run_writer(
            w,
            project,
            "run",
            "--reason",
            "test requested run",
            "--pipeline-code",
            "P",
            fault=point + ":kill",
            timeout=120,
        )
        assert code != 0, output
        with w.engine_db.connect() as conn:
            run_id = conn.execute(
                text("SELECT MAX(PIPELINE_RUN_ID) FROM AUD_PIPELINES_RUN_LOG")
            ).scalar_one()
            successes = conn.execute(
                text(
                    "SELECT COUNT(*) FROM AUD_TASK_ITEMS i JOIN AUD_TASK_RUN_LOG t "
                    "ON t.TASK_RUN_ID=i.TASK_RUN_ID WHERE t.PIPELINE_RUN_ID=:run "
                    "AND i.STATUS='SUCCESS'"
                ),
                {"run": run_id},
            ).scalar_one()
        assert successes == 0
        expire_leases(w.engine_db)
        code, output = run_writer(
            w,
            project,
            "run",
            "--pipeline-code",
            "P",
            "--run-id",
            str(run_id),
            "--task-code",
            "loader",
            "--rerun",
            "--reason",
            "Retry the injected landing crash",
            timeout=120,
        )
        assert code == 0, output
        assert w.rows(f"SELECT id,name FROM {w.name(target)} WHERE item_key='0'") == [(0, "new")]
        assert (
            w.rows(f"SELECT id,name,task_run_id FROM {w.name(target)} WHERE item_key='1'") == before
        )
        assert not any(name.startswith("etl_landing_") for name in w.tables())
    finally:
        for command in reversed(project.processes):
            command.close()
        w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")


def check_landing_inflight(w, monkeypatch):
    from fixtures.landing import install_inflight_barrier, kill_inflight

    target = "landing_" + uuid4().hex[:12]
    monkeypatch.setenv(
        "ETL_CRAFT_TEST_PRIVACY_SECRET",
        os.environ.get("ETL_CRAFT_TEST_PRIVACY_SECRET", "landing-test-only"),
    )
    project, token = cli_writer(w, target)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token)
    try:
        assert run_writer(w, project, "pipelines", "refresh", timeout=90)[0] == 0
        code, output = run_writer(
            w, project, "run", "--reason", "test requested run", "--pipeline-code", "P", timeout=120
        )
        assert code == 0, output
        before = w.rows(f"SELECT id,name,task_run_id FROM {w.name(target)} WHERE item_key='1'")
        marker = install_inflight_barrier(w, project)
        with w.engine_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                    "VALUES (:id,'INPUT_PARAMS',:params)"
                ),
                {
                    "id": project.task_id,
                    "params": json.dumps({"keys": ["0"], "value": "new", "slow": True}),
                },
            )
        assert run_writer(w, project, "pipelines", "refresh", timeout=90)[0] == 0
        w.warehouse.dispose()
        command = project.start("run", "--reason", "test requested run", "--pipeline-code", "P")
        kill_inflight(w, project, marker)
        assert command.wait(timeout=120) != 0
        with w.engine_db.connect() as conn:
            run_id = conn.execute(
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
            str(run_id),
            "--task-code",
            "loader",
            "--rerun",
            "--reason",
            "Retry SIGKILL during landing",
            timeout=120,
        )
        assert code == 0, output
        assert w.rows(f"SELECT id,name FROM {w.name(target)} WHERE item_key='0'") == [(0, "new")]
        assert (
            w.rows(f"SELECT id,name,task_run_id FROM {w.name(target)} WHERE item_key='1'") == before
        )
    finally:
        for command in reversed(project.processes):
            command.close()
        w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")
