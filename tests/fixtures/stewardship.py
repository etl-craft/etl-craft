"""One real received-upload project for local and cloud provider acceptance."""

from dataclasses import replace

import yaml
from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.core.actor import SYSTEM_ACTOR, Actor, acting_as
from etl_craft.core.enums import ActionName, ActorKind, ApiRole, RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.runlog import RunSelector
from etl_craft.execution.pipeline import run_pipeline
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.uploads import UploadRequest, receive
from etl_craft.warehouse.connection import warehouse_dialect
from fixtures.actions import act
from fixtures.engine_db import profile_block
from fixtures.metadata import add_dependency, add_source_column, add_task

VALIDATOR = """
from etl_craft.scripting import PermanentError

def validate(task):
    rows = task.reader.rows(schema={"LOCKED": bool})
    header = next(rows, None)
    if header not in (("id", "name"), ("id", "name", "LOCKED")):
        raise PermanentError(
            f"row 1 header={header!r}; expected id|name with a pipe separator; "
            "upload a corrected file"
        )
    seen = set()
    for number, row in enumerate(rows, 2):
        if len(row) != len(header) or not row[0].isdigit() or int(row[0]) in seen:
            raise PermanentError(
                f"row {number} value={row!r}; expected a unique integer id and name; "
                "upload a corrected file"
            )
        seen.add(int(row[0]))
"""


def configure_upload_world(w, kind, *, prefix=""):
    """Create the same validator, loader and merge graph on a supplied warehouse."""
    root = w.config.project_dir
    (root / "validation_scripts").mkdir()
    (root / "python_scripts").mkdir()
    (root / "validation_scripts/check.py").write_text(VALIDATOR)
    text_type = warehouse_dialect(w.config).string_type
    uploaded = prefix + "uploaded"
    source, target = w.name(prefix + "landed"), w.name(uploaded)
    w.execute(
        f"CREATE TABLE {source} (id INTEGER,name {text_type},LOCKED BOOLEAN,UPLOAD_ID BIGINT,"
        f"CREATED_BY {text_type},UPDATED_BY {text_type})"
    )
    if kind == "APPEND_TABLE":
        w.execute(
            f"CREATE TABLE {target} (id INTEGER,name {text_type},UPLOAD_ID BIGINT,"
            f"CREATED_BY {text_type},UPDATED_BY {text_type},"
            "PIPELINE_RUN_ID BIGINT,PIPELINE_ID BIGINT,"
            "TASK_RUN_ID BIGINT,CREATE_DATE TIMESTAMP WITH TIME ZONE,ROW_ID BIGINT)"
        )
    else:
        w.setup(uploaded, f"SELECT id,name,UPLOAD_ID FROM {source}", kind)
        with w.engine_db.begin() as conn:
            conn.execute(text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N'"))
    loader = """
import csv
from sqlalchemy import text
from etl_craft.scripting import ScriptResult, UploadReader

def run(task):
    written = 0
    with task.warehouse() as engine, engine.begin() as conn:
        for upload in task.uploads:
            conn.execute(
                text("DELETE FROM SOURCE_TABLE WHERE UPLOAD_ID=:upload"),
                {"upload": upload.upload_id},
            )
            rows = UploadReader(upload, "CSV").rows(schema={"LOCKED": bool})
            header = next(rows)
            for row in rows:
                values = dict(zip(header, row))
                conn.execute(text(
                    "INSERT INTO SOURCE_TABLE (id,name,LOCKED,UPLOAD_ID,CREATED_BY,UPDATED_BY) "
                    "VALUES (:id,:name,:locked,:upload,:account,:account)"
                ), {
                    "id": int(values["id"]), "name": values["name"],
                    "locked": values.get("LOCKED"),
                    "upload": upload.upload_id, "account": upload.account,
                })
                written += 1
    return ScriptResult(row_count=written)
""".replace("SOURCE_TABLE", source)
    (root / "python_scripts/load.py").write_text(loader)
    config_file = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {
            "Project": "default",
            "Task_timeout_seconds": 600 if w.kind == "cloud" else 60,
        },
        "Engine": {"dev": profile_block(w.config.engine, w.config.engine.schema or "main")},
        "Warehouse": {
            "Name": {
                "duckdb": "DuckDB",
                "duckdb_iceberg": "DuckDB",
                "postgres": "Postgres",
                "trino_iceberg": "Trino",
            }[w.kind]
            if w.kind != "cloud"
            else yaml.safe_load(w.config.config_path.read_text())["Warehouse"]["Name"],
            "Table_format": str(w.config.warehouse_table_format),
            "dev": profile_block(w.config.warehouse, w.schema),
        },
    }
    if w.config.engine.jdbc_url.startswith("jdbc:postgresql:"):
        config_file["Artifacts"] = {"Store": (root / "artifacts").as_uri()}
    config_file["Privacy"] = {"Hmac_secret": "ETL_CRAFT_TEST_PRIVACY_SECRET"}
    w.config.config_path.write_text(yaml.safe_dump(config_file, sort_keys=False))
    w.config = load_config(w.config.config_path)
    owner = OperationContext(
        w.engine_db, w.config, SYSTEM_ACTOR, role=ApiRole.ADMIN, project="default", project_id=1
    )
    for name in ("alice", "bob"):
        act(
            owner,
            ActionName.ACCOUNT_ADD,
            name=name,
            role=ApiRole.ADMIN,
            password="correct horse battery",
        )
    with w.engine_db.begin() as conn:
        for position, (column, data_type) in enumerate(
            (
                ("id", "INTEGER"),
                ("name", text_type),
                ("LOCKED", "BOOLEAN"),
                ("UPLOAD_ID", "BIGINT"),
                ("CREATED_BY", text_type),
                ("UPDATED_BY", text_type),
            ),
            1,
        ):
            add_source_column(conn, source, column, data_type, position)
        transitions.finalize_pipeline_run(conn, w.pipeline_run_id, RunStatus.SUCCESS)
        validation = add_task(
            conn,
            w.pipeline_id,
            "validate_file",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
        )
        load = add_task(
            conn,
            w.pipeline_id,
            "land",
            "PYTHON",
            SCRIPT_FILE="python_scripts/load.py",
            SCRIPT_KIND="INGESTION",
        )
        append = add_task(
            conn,
            w.pipeline_id,
            "apply",
            "SQL",
            SQL_ACTION=kind,
            **(
                {
                    "MERGE_KEY": "id",
                    "MERGE_COMPARE_COLUMNS": "name",
                    "MERGE_DEDUPE_ORDER": "UPLOAD_ID ASC",
                }
                if kind != "APPEND_TABLE"
                else {}
            ),
            TARGET_OBJECT=f"{w.schema}.{uploaded}",
            SELECT_QUERY=(
                f"SELECT id,name,UPLOAD_ID{',LOCKED' if kind != 'APPEND_TABLE' else ''} "
                f"FROM {source} WHERE UPLOAD_ID IN ($$upload_ids)"
            ),
        )
        add_dependency(conn, w.pipeline_id, load, validation, "HAS_DATA")
        add_dependency(conn, w.pipeline_id, append, load)
        conn.execute(
            text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y' WHERE PIPELINE_ID=:id"),
            {"id": w.pipeline_id},
        )
    return w, owner


def submit(owner, account, content):
    caller = replace(owner, actor=Actor(account, ActorKind.USER))
    with receive(caller, UploadRequest(pipeline_code="P")) as receipt:
        receipt.begin_file("corrections.csv", "text/csv")
        receipt.write(content)
    return receipt.result


def drive_upload(w, run_id):
    w.warehouse.dispose()
    with acting_as(SYSTEM_ACTOR):
        return run_pipeline(w.engine_db, w.config, "P", selector=RunSelector(run_id=run_id))


def check_upload_controls(
    upload_world,
    monkeypatch,
    capsys,
    tmp_path,
    *,
    table="uploaded",
    child_setup="",
    merge_statements=1,
):
    import json
    import os
    from pathlib import Path

    from fastapi.testclient import TestClient

    from etl_craft.api.app import create_app
    from etl_craft.cli import main
    from etl_craft.engine.migrations import mark_packaged_migrations_applied
    from fixtures.round_trips import database

    w, owner = upload_world
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
    token = act(
        owner, ActionName.LOGIN, name="alice", password="correct horse battery"
    ).access_token
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
    headers = {"Authorization": "Bearer " + token}
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token)
    with TestClient(create_app(owner)) as client:
        response = client.post(
            "/api/v1/projects/default/uploads?pipeline_code=P",
            headers=headers,
            files={"file": ("initial.csv", b"id|name\n1|first\n2|other\n", "text/csv")},
        )
        assert response.status_code == 200, response.text
        initial = response.json()
        result = drive_upload(w, initial["pipeline_run_id"])
        assert result.status == RunStatus.SUCCESS, result.message
        # An upload releases an administrator's deliberate row and cell lock too.
        edited = client.post(
            "/api/v1/projects/default/values",
            headers=headers,
            json={
                "pipeline_code": "P",
                "task_code": "apply",
                "key": {"id": 1},
                "values": {"name": "admin"},
                "reason": "correct",
                "row_lock": True,
            },
        )
        assert edited.status_code == 200, edited.text
        refreshed = act(owner, ActionName.PIPELINE_REFRESH, pipeline_code="P")
        assert not refreshed.failed, refreshed.refreshes[0].findings
        path = tmp_path / "release.csv"
        path.write_bytes(b"id|name|LOCKED\n1|admin|false\n2|changed|true\n3|new|false\n4|null|\n")
        assert (
            main(
                [
                    "--config",
                    str(w.config.config_path),
                    "upload",
                    "--project",
                    "default",
                    "--pipeline-code",
                    "P",
                    str(path),
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        second = json.loads(capsys.readouterr().out)
        instrumentation = tmp_path / "instrumentation"
        instrumentation.mkdir()
        records = tmp_path / "statements.jsonl"
        if w.kind == "cloud":
            child_setup += (
                "from fixtures.stewardship import record_child_scratch\n"
                f"record_child_scratch({str(tmp_path / 'scratch-tables.txt')!r})\n"
            )
        (instrumentation / "sitecustomize.py").write_text(
            child_setup + "from fixtures.round_trips import install_child_counter\n"
            f"install_child_counter({str(records)!r}, {database(w.engine_db.url)!r})\n"
        )
        monkeypatch.setenv(
            "PYTHONPATH", os.pathsep.join((str(instrumentation), str(Path(__file__).parents[1])))
        )
        result = drive_upload(w, second["pipeline_run_id"])
        events = [json.loads(line) for line in records.read_text().splitlines()]
        target = w.name(table).upper()
        statements = [
            row["query"].upper()
            for row in events
            if row["kind"] == "warehouse"
            and row["measure"] == "statements"
            and any(
                row["query"].upper().startswith(f"OTHER: {verb} {target} ")
                for verb in ("MERGE INTO", "UPDATE", "INSERT INTO", "DELETE FROM")
            )
        ]
        assert len(statements) == merge_statements, statements
        if merge_statements == 1:
            assert statements[0].startswith("OTHER: MERGE INTO "), statements
        else:
            assert statements[0].startswith("OTHER: UPDATE "), statements
            assert statements[1].startswith("OTHER: INSERT INTO "), statements
        assert result.status == RunStatus.SUCCESS, result.message
        states = {
            row[0]: json.loads(row[1])
            for row in w.rows(
                f"SELECT id AS id,ETL_PROTECTION AS protection FROM {w.name(table)} "
                "WHERE ACTIVE_FLAG='Y'"
            )
        }
        assert not any(c["locked"] for c in states[1]["cells"].values())
        assert not any(c["locked"] for c in states[3]["cells"].values())
        assert states[2]["cells"]["name"]["locked"]
        assert states[4]["cells"]["*"]["locked"]
        assert "locked" not in states[1]["cells"]
        with w.engine_db.connect() as conn:
            events = (
                conn.execute(
                    text(
                        "SELECT KIND AS kind,UPLOAD_ID AS upload_id,CREATED_BY AS actor,"
                        "TARGET_ID AS target_id,KEY_HASH AS key_hash,COLUMN_NAMES AS column_names,"
                        "VALUE_HASHES AS value_hashes,REQUEST_ID AS request_id,STATUS AS status "
                        "FROM AUD_PROTECTION_EVENTS "
                        "WHERE UPLOAD_ID=:upload"
                    ),
                    {"upload": second["upload_id"]},
                )
                .mappings()
                .all()
            )
        assert any(e["kind"] == "UNLOCK" for e in events)
        assert all(e["actor"] == "alice" for e in events)
        assert "admin" not in str(events) and "changed" not in str(events)
        evidence = act(
            owner, ActionName.DATA_PROVENANCE, pipeline_code="P", task_code="apply", key={"id": 1}
        )
        assert any(
            event["reason"] == f"upload {second['upload_id']}: LOCKED=false"
            and event["actor"] == "alice"
            for event in evidence.history
        )
        # Same value must acquire a lock without manufacturing an SCD2 version.
        versions_before = w.rows(f"SELECT COUNT(*) FROM {w.name(table)} WHERE id=1")[0][0]
        response = client.post(
            "/api/v1/projects/default/uploads?pipeline_code=P",
            headers=headers,
            files={"file": ("relock.csv", b"id|name|LOCKED\n1|admin|TRUE\n", "text/csv")},
        )
        assert response.status_code == 200, response.text
        result = drive_upload(w, response.json()["pipeline_run_id"])
        assert result.status == RunStatus.SUCCESS, result.message
        assert w.rows(f"SELECT COUNT(*) FROM {w.name(table)} WHERE id=1") == [(versions_before,)]
        raw = w.rows(f"SELECT ETL_PROTECTION FROM {w.name(table)} WHERE id=1 AND ACTIVE_FLAG='Y'")
        assert json.loads(raw[0][0])["cells"]["name"]["locked"]
        with w.engine_db.connect() as conn:
            kind = conn.execute(
                text(
                    "SELECT PARAMETER_VALUE AS kind FROM CFG_TASK_PARAMETERS "
                    "WHERE TASK_ID=:task AND PARAMETER_NAME='SETUP_FOR'"
                ),
                {"task": w.tasks["setup_" + table]},
            ).scalar_one()
        with w.engine_db.connect() as conn:
            counts = (
                conn.execute(
                    text(
                        "SELECT t.INSERT_COUNT AS inserted,t.UPDATE_COUNT AS updated "
                        "FROM AUD_TASK_RUN_LOG t JOIN CFG_TASKS c ON c.TASK_ID=t.TASK_ID "
                        "WHERE t.PIPELINE_RUN_ID=:run AND c.TASK_CODE='apply'"
                    ),
                    {"run": second["pipeline_run_id"]},
                )
                .mappings()
                .one()
            )
        assert counts["inserted"] == (3 if kind == "SCD2_MERGE" else 2)
        assert counts["updated"] == 1
        reloaded = w.run(
            "source_reload",
            SQL_ACTION=kind,
            TARGET_OBJECT=table,
            SELECT_QUERY="SELECT 3 AS id,'source' AS name,CAST(NULL AS BIGINT) AS UPLOAD_ID",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
        )
        assert reloaded.update_count == 1
        assert w.rows(f"SELECT name FROM {w.name(table)} WHERE id=3 AND ACTIVE_FLAG='Y'") == [
            ("source",)
        ]
        with w.engine_db.begin() as conn:
            conn.execute(
                text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N' WHERE TASK_ID=:task"),
                {"task": w.tasks["source_reload"]},
            )


def check_upload_recovery(upload_world, monkeypatch, point, *, table="uploaded", kind="SCD2_MERGE"):
    """Kill and replay a real received upload, through both available recovery paths."""
    import json

    from fixtures.lock_fencing import expire_leases

    w, owner = upload_world
    initial = submit(owner, "alice", f"id|name\n1|initial-{point}\n".encode())
    assert drive_upload(w, initial["pipeline_run_id"]).status == RunStatus.SUCCESS
    paths = (
        ("local", "agent")
        if w.config.engine.jdbc_url.startswith("jdbc:postgresql:")
        else ("local",)
    )
    for recovery in paths:
        if recovery == "agent":
            act(
                replace(owner, actor=Actor("alice", ActorKind.USER)),
                ActionName.DATA_EDIT,
                pipeline_code="P",
                task_code="apply",
                key={"id": 1},
                values={"name": f"initial-agent-{point}"},
                row_lock=True,
                reason="reset",
            )
        uploaded = submit(
            owner, "bob", f"id|name|LOCKED\n1|released-{recovery}-{point}|false\n".encode()
        )
        monkeypatch.setenv("ETL_CRAFT_FAULT", "protection." + point + ":kill")
        result = drive_upload(w, uploaded["pipeline_run_id"])
        assert result.status == RunStatus.FAILED
        monkeypatch.delenv("ETL_CRAFT_FAULT")
        if w.kind == "cloud":
            cleanup_upload_scratch(w)
        expire_leases(w.engine_db)
        from fixtures.protection_acceptance import recover_mutation

        recover_mutation(w, owner, "apply", table, {"SQL_ACTION": kind}, recovery == "agent")
        with w.engine_db.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT KIND AS kind,STATUS AS status,UPLOAD_ID AS upload_id "
                        "FROM AUD_PROTECTION_EVENTS "
                        "WHERE UPLOAD_ID=:upload ORDER BY EVENT_ID"
                    ),
                    {"upload": uploaded["upload_id"]},
                )
                .mappings()
                .all()
            )
        state = json.loads(
            w.rows(f"SELECT ETL_PROTECTION FROM {w.name(table)} WHERE id=1 AND ACTIVE_FLAG='Y'")[0][
                0
            ]
        )
        if point == "before_pending":
            assert not rows
        else:
            assert any(row["kind"] == "UNLOCK" for row in rows)
            finals = [row for row in rows if row["status"] != "PENDING"]
            assert len(finals) == 1
            assert finals[0]["status"] == ("ABANDONED" if point == "after_pending" else "COMMITTED")
        assert any(cell["locked"] for cell in state["cells"].values()) == (
            point in {"before_pending", "after_pending"}
        )
        versions = w.rows(f"SELECT COUNT(*) FROM {w.name(table)} WHERE id=1")[0][0]
        w.warehouse.dispose()
        replay = act(
            owner,
            ActionName.RUN,
            pipeline_code="P",
            task_code="apply",
            run_id=uploaded["pipeline_run_id"],
            rerun=True,
            reason="replay the interrupted upload",
        )
        assert replay.status == RunStatus.SUCCESS, replay.message
        current = w.rows(
            f"SELECT name,ETL_PROTECTION FROM {w.name(table)} WHERE id=1 AND ACTIVE_FLAG='Y'"
        )
        assert len(current) == 1 and current[0][0] == f"released-{recovery}-{point}"
        writers = json.loads(current[0][1])["cells"]
        assert writers["id"]["writer"] == "alice"
        assert writers["name"]["writer"] == "bob"
        if point in {"after_merge", "after_committed"}:
            assert w.rows(f"SELECT COUNT(*) FROM {w.name(table)} WHERE id=1") == [(versions,)]


def record_child_scratch(path):
    """Retain exact generated table identities when a cloud task is deliberately killed."""
    import os

    from etl_craft.handlers.sql.session import Session

    original = Session.scratch

    def scratch(self, suffix, *, persistent=False):
        name = original(self, suffix, persistent=persistent)
        if "." in name:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, (name + "\n").encode())
            finally:
                os.close(descriptor)
        return name

    Session.scratch = scratch


def cleanup_upload_scratch(w):
    """Drop only scratch names recorded by this test's own child processes."""
    path = w.config.project_dir.parent / "scratch-tables.txt"
    if not path.exists():
        return
    for name in sorted(set(path.read_text().splitlines())):
        w.execute(f"DROP TABLE IF EXISTS {name}")
    path.unlink()
