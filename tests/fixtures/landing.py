"""Real CLI landing writers and crash recovery shared by warehouse acceptance."""

from dataclasses import replace

import yaml
from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.core.enums import Handler, RunStatus
from etl_craft.engine import transitions
from etl_craft.handlers.python_scripts import script_task
from etl_craft.handlers.registry import task_store
from fixtures.auth import service_token
from fixtures.cli_project import CliProject
from fixtures.metadata import add_source_column


def landing_task(w, target="landing"):
    """Declare a landing shape and bind a script to its own target contract."""
    w.setup(
        target,
        "SELECT CAST(NULL AS BIGINT) AS id, CAST(NULL AS VARCHAR(100)) AS name WHERE 1=0",
        "APPEND_TABLE",
    )
    context = replace(
        w.task("loader", TARGET_OBJECT=w.name(target), SCRIPT_KIND="INGESTION"),
        handler=Handler.PYTHON,
    )
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='PYTHON' WHERE TASK_ID=:id"),
            {"id": w.tasks["loader"]},
        )
        add_source_column(conn, w.name(target), "id", "BIGINT", 1)
        add_source_column(conn, w.name(target), "name", "VARCHAR(100)", 2)
    return script_task(context, task_store(context, w.engine_db), None, {}), context


def cli_writer(w, target="landing"):
    """Serialize the real service profiles for a separately launched task process."""
    task, context = landing_task(w, target)
    task.replace_landing(iter(()))
    from etl_craft.warehouse.connection import warehouse_dialect

    with w.warehouse.connect() as conn:
        actual = warehouse_dialect(w.config).full_column_types(conn, w.name(target))
    with w.engine_db.begin() as conn:
        for position, (name, kind) in enumerate(actual.items(), 3):
            if name in {"id", "name"}:
                conn.execute(
                    text(
                        "UPDATE CFG_COLUMNS SET DATA_TYPE=:kind WHERE TABLE_ID="
                        "(SELECT TARGET_TABLE_ID FROM CFG_TASKS WHERE TASK_ID=:task) "
                        "AND COLUMN_NAME=:name"
                    ),
                    {"kind": kind, "task": context.task_id, "name": name},
                )
            else:
                add_source_column(conn, w.name(target), name, kind, position)
    from fixtures.engine_db import profile_block

    profile = w.config.warehouse
    fields = {k.capitalize(): v for k, v in profile.extra.items() if k != "secret_var"}
    fields.update(
        Jdbc_url=profile.jdbc_url,
        Schema=profile.schema,
        User=profile.user,
        Auth_mode=str(profile.auth_mode),
    )
    if "secret_var" in profile.extra:
        fields["Secret"] = profile.secret_var
    raw = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {"Project": "default", "Log_dir": "logs", "Api_address": "127.0.0.1:0"},
        "Engine": {"dev": profile_block(w.config.engine, w.config.engine.schema)},
        "Warehouse": {"Table_format": str(w.config.warehouse_table_format), "dev": fields},
        "Artifacts": {"Store": (w.project / "artifacts").as_uri()},
        "Privacy": {"Hmac_secret": "ETL_CRAFT_TEST_PRIVACY_SECRET"},
    }
    w.config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    config = load_config(w.config.config_path)
    config.python_scripts_dir.mkdir(exist_ok=True)
    (
        config.python_scripts_dir / "load.py"
    ).write_text("""from etl_craft.scripting import ScriptResult

def run(task):
    def load(key):
        rows = ({"id":int(key), "name":task.input_params.get("value", "old")},)
        return ScriptResult(task.replace_landing(iter(rows), item_key=key))
    return task.fan_out(task.input_params.get("keys", ["0", "1"]), load,
                        max_parallel=2, max_items=4)
""")
    with w.engine_db.begin() as conn:
        conn.execute(
            text("DELETE FROM CFG_TASK_PARAMETERS WHERE TASK_ID=:id"), {"id": context.task_id}
        )
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "VALUES (:id,'SCRIPT_KIND','INGESTION'),"
                "(:id,'SCRIPT_FILE','python_scripts/load.py')"
            ),
            {"id": context.task_id},
        )
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N' WHERE TASK_ID<>:id"), {"id": context.task_id}
        )
    with w.engine_db.begin() as conn:
        transitions.finalize_pipeline_run(conn, w.pipeline_run_id, RunStatus.SUCCESS)
    project = CliProject(w.engine_db, config, w.pipeline_id, context.task_id, [])
    return project, service_token(w.engine_db)


def run_writer(w, project, *arguments, **options):
    """Release the oracle's embedded file connection before launching another process."""
    w.warehouse.dispose()
    return project.run(*arguments, **options)


def install_inflight_barrier(w, project):
    """Instrument the target statement so SIGKILL occurs while the real engine executes it."""

    marker = project.config.project_dir / "landing-in-statement.json"
    slow = {
        "postgres": "SELECT 1 AS barrier FROM pg_sleep(120)",
        "trino_iceberg": "SELECT count(*) AS barrier FROM UNNEST(sequence(1,10000)) a "
        "CROSS JOIN UNNEST(sequence(1,10000)) b CROSS JOIN UNNEST(sequence(1,10000)) c",
        "snowflake": "SELECT SYSTEM$WAIT(120) AS barrier",
        "databricks": "SELECT MAX(sha2(CAST(id AS STRING),256)) AS barrier FROM range(10000000000)",
    }
    condition = (
        "barrier_source.barrier > 0"
        if w.kind in {"postgres", "trino_iceberg"}
        else ("barrier_source.barrier IS NOT NULL")
    )
    path = project.config.python_scripts_dir / "load.py"
    source = path.read_text()
    injection = f"""    if task.input_params.get("slow"):
        import os
        import json
        import threading
        from pathlib import Path
        import etl_craft.warehouse.landing as publication
        marker = Path({str(marker)!r})
        original = publication.publish_statements
        def barrier_statement(conn, dialect, write, stage, kinds, actual):
            if marker.exists():
                return original(conn, dialect, write, stage, kinds, actual)
            if {w.kind!r} == "duckdb":
                def inside_query():
                    marker.write_text(json.dumps({{"pid":os.getpid()}}))
                    threading.Event().wait(120)
                    return True
                conn.connection.driver_connection.create_function(
                    "etl_landing_barrier", inside_query, [], "BOOLEAN", side_effects=True)
                stage = f"(SELECT * FROM {{stage}} WHERE etl_landing_barrier())"
            else:
                stage = (f"(SELECT n.* FROM {{stage}} n CROSS JOIN "
                         f"({slow.get(w.kind, "")}) barrier_source WHERE {condition})")
            result = original(conn, dialect, write, stage, kinds, actual)
            if {w.kind!r} != "duckdb":
                marker.write_text(json.dumps({{"pid":os.getpid()}}))
            return result
        publication.publish_statements = barrier_statement
"""
    path.write_text(source.replace("def run(task):\n", "def run(task):\n" + injection))
    return marker


def kill_inflight(w, project, marker):
    """Wait for observed SQL execution, then kill the task child rather than its supervisor."""
    import json
    import os
    import signal
    import time

    from etl_craft.core.ownership import attempt_holder
    from etl_craft.engine.resource_locks import holder_tag
    from etl_craft.warehouse.connection import warehouse_dialect

    deadline = time.monotonic() + 90
    while True:
        if marker.exists():
            data = json.loads(marker.read_text())
            running = w.kind == "duckdb"
            if not running:
                with w.engine_db.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT ATTEMPT_ID AS attempt_id,OWNER_ID AS owner "
                            "FROM AUD_TASK_ATTEMPTS ORDER BY ATTEMPT_ID DESC LIMIT 1"
                        )
                    ).one()
                with w.warehouse.begin() as conn:
                    running = (
                        warehouse_dialect(w.config).running_tagged(
                            conn, holder_tag(attempt_holder(row.attempt_id, row.owner))
                        )
                        > 0
                    )
            if running:
                os.kill(data["pid"], signal.SIGKILL)
                return
        assert time.monotonic() < deadline, "the target statement never entered execution"
        time.sleep(0.05)
