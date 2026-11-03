"""Complete stewardship runs use the same reader, scripts and SQL actions on every warehouse."""

from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR, Actor, acting_as
from etl_craft.core.enums import ActionName, ActorKind, ApiRole, RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.runlog import RunSelector
from fixtures.actions import act
from fixtures.sql_warehouse import warehouses
from fixtures.stewardship import configure_upload_world, drive_upload, submit


@pytest.fixture
def upload_world(sql_world, request):
    w = sql_world
    kind = getattr(request, "param", "APPEND_TABLE")
    if isinstance(kind, tuple):
        kind, engine_kind = kind
        if engine_kind == "postgresql":
            from fixtures.scd_protection import use_postgres_engine

            use_postgres_engine(w, request)
    return configure_upload_world(w, kind)


def test_complete_upload_flow_keeps_each_stewards_account(upload_world):
    from etl_craft.controller.uploads import admit_pending

    w, owner = upload_world
    first = submit(owner, "alice", b"id|name\n0|warmup\n")
    alice = submit(owner, "alice", b"id|name\n1|first\n")
    bob = submit(owner, "bob", b"id|name\n2|second\n")
    assert alice["waiting_behind_run_id"] == first["pipeline_run_id"]
    assert bob["waiting_behind_run_id"] == first["pipeline_run_id"]
    warmup = drive_upload(w, first["pipeline_run_id"])
    assert warmup.status == RunStatus.SUCCESS, warmup.message
    assert not list((w.config.host_dir / ".upload_inputs").glob("**/content"))
    admit_pending(owner)
    with w.engine_db.connect() as conn:
        bound = (
            conn.execute(
                text(
                    "SELECT UPLOAD_ID AS upload_id,PIPELINE_RUN_ID AS run_id "
                    "FROM AUD_UPLOADS WHERE UPLOAD_ID IN (:a,:b) ORDER BY UPLOAD_ID"
                ),
                {"a": alice["upload_id"], "b": bob["upload_id"]},
            )
            .mappings()
            .all()
        )
    assert bound[0]["run_id"] == bound[1]["run_id"]
    assert bound[0]["run_id"] != first["pipeline_run_id"]
    result = drive_upload(w, bound[0]["run_id"])
    assert result.status == RunStatus.SUCCESS, result.message
    assert not list((w.config.host_dir / ".upload_inputs").glob("**/content"))
    with w.warehouse.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT id AS id,name AS name,CREATED_BY AS creator,"
                    f"UPDATED_BY AS writer FROM {w.name('uploaded')} ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    with w.warehouse.connect() as conn:
        landed = (
            conn.execute(
                text(
                    f"SELECT id AS id,name AS name,CREATED_BY AS creator,UPDATED_BY AS writer "
                    f"FROM {w.name('landed')} ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert [dict(row) for row in landed] == [dict(row) for row in rows]
    assert [dict(row) for row in rows] == [
        {"id": 0, "name": "warmup", "creator": "alice", "writer": "alice"},
        {"id": 1, "name": "first", "creator": "alice", "writer": "alice"},
        {"id": 2, "name": "second", "creator": "bob", "writer": "bob"},
    ]


def test_bad_stewardship_file_never_reaches_a_project_table(upload_world):
    w, owner = upload_world
    receipt = submit(owner, "alice", b"id,name\n1,bad separator\n")
    result = drive_upload(w, receipt["pipeline_run_id"])
    assert result.status == RunStatus.FAILED
    with w.engine_db.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT STATUS AS status,REASON AS reason FROM AUD_UPLOADS WHERE UPLOAD_ID=:id"
                ),
                {"id": receipt["upload_id"]},
            )
            .mappings()
            .one()
        )
    assert row["status"] == "REFUSED"
    for expected in ("row 1", "header=", "expected id|name", "corrected file"):
        assert expected in row["reason"]
    with w.warehouse.connect() as conn:
        assert (
            conn.execute(text(f"SELECT COUNT(*) AS rows FROM {w.name('uploaded')}"))
            .mappings()
            .one()["rows"]
            == 0
        )


@warehouses("duckdb", "postgres", "duckdb_iceberg", "trino_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_complete_protected_upload_flow_orders_files_and_locks_each_writer(upload_world):
    from etl_craft.controller.uploads import admit_pending

    w, owner = upload_world
    with w.engine_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS "
                "SET PARAMETER_VALUE=PARAMETER_VALUE || ' UNION ALL ' || "
                "PARAMETER_VALUE || ' AND id=2' "
                "WHERE PARAMETER_NAME='SELECT_QUERY' AND TASK_ID IN "
                "(SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE='apply')"
            )
        )
    warmup = submit(owner, "alice", b"id|name\n0|warmup\n")
    alice = submit(owner, "alice", b"id|name|LOCKED\n1|first|false\n2|only alice|true\n")
    bob = submit(owner, "bob", b"id|name|LOCKED\n1|newest|true\n3|only bob|true\n")
    result = drive_upload(w, warmup["pipeline_run_id"])
    assert result.status == RunStatus.SUCCESS, result.message
    admit_pending(owner)
    with w.engine_db.connect() as conn:
        run_id = conn.execute(
            text("SELECT PIPELINE_RUN_ID AS run_id FROM AUD_UPLOADS WHERE UPLOAD_ID=:id"),
            {"id": alice["upload_id"]},
        ).scalar_one()
    result = drive_upload(w, run_id)
    assert result.status == RunStatus.SUCCESS, result.message
    assert not list((w.config.host_dir / ".upload_inputs").glob("**/content"))
    with w.warehouse.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT id AS id,name AS name,CREATED_BY AS creator,UPDATED_BY AS writer "
                    f"FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y' ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert all(r["creator"] == r["writer"] for r in rows)
    assert [(r["id"], r["name"], r["writer"]) for r in rows] == [
        (0, "warmup", "alice"),
        (1, "newest", "bob"),
        (2, "only alice", "alice"),
        (3, "only bob", "bob"),
    ]
    for key, writer in [(1, "bob"), (2, "alice"), (3, "bob")]:
        evidence = act(
            owner, ActionName.DATA_PROVENANCE, pipeline_code="P", task_code="apply", key={"id": key}
        )
        assert any(row["locked"] and row["writer"] == writer for row in evidence.records)
    with w.engine_db.connect() as conn:
        accounts = (
            conn.execute(
                text(
                    "SELECT ACCOUNT AS account FROM AUD_UPLOADS WHERE UPLOAD_ID IN (:a,:b) "
                    "ORDER BY UPLOAD_ID"
                ),
                {"a": alice["upload_id"], "b": bob["upload_id"]},
            )
            .scalars()
            .all()
        )
        assert (
            conn.execute(
                text(
                    "SELECT r.duplicate_count FROM AUD_TASK_RUN_LOG r JOIN CFG_TASKS t "
                    "ON r.task_id=t.task_id WHERE r.pipeline_run_id=:run AND t.task_code='apply'"
                ),
                {"run": run_id},
            ).scalar_one()
            == 1
        )
    assert accounts == ["alice", "bob"]


def test_one_refused_file_does_not_prevent_another_file_loading(upload_world):
    from etl_craft.controller.uploads import admit_pending

    w, owner = upload_world
    warmup = submit(owner, "alice", b"id|name\n0|warmup\n")
    good = submit(owner, "bob", b"id|name\n1|accepted\n")
    bad = submit(owner, "alice", b"id,name\n2,refused\n")
    result = drive_upload(w, warmup["pipeline_run_id"])
    assert result.status == RunStatus.SUCCESS, result.message
    admit_pending(owner)
    with w.engine_db.connect() as conn:
        run_id = conn.execute(
            text("SELECT PIPELINE_RUN_ID AS run_id FROM AUD_UPLOADS WHERE UPLOAD_ID=:id"),
            {"id": good["upload_id"]},
        ).scalar_one()
    result = drive_upload(w, run_id)
    assert result.status == RunStatus.SUCCESS, result.message
    with w.engine_db.connect() as conn:
        records = (
            conn.execute(
                text(
                    "SELECT UPLOAD_ID AS id,STATUS AS status FROM AUD_UPLOADS "
                    "WHERE UPLOAD_ID IN (:good,:bad)"
                ),
                {"good": good["upload_id"], "bad": bad["upload_id"]},
            )
            .mappings()
            .all()
        )
    assert {r["id"]: r["status"] for r in records} == {
        good["upload_id"]: "LOADED",
        bad["upload_id"]: "REFUSED",
    }
    with w.warehouse.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT id AS id,CREATED_BY AS creator,UPDATED_BY AS writer "
                    f"FROM {w.name('uploaded')} ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert [(r["id"], r["creator"], r["writer"]) for r in rows] == [
        (0, "alice", "alice"),
        (1, "bob", "bob"),
    ]


@warehouses("duckdb")
def test_a_run_without_uploads_validates_nothing_and_skips_downstream(upload_world):
    w, _ = upload_world
    with acting_as(SYSTEM_ACTOR), w.engine_db.begin() as conn:
        run_id = transitions.create_run(conn, w.pipeline_id, SYSTEM_ACTOR)
    result = drive_upload(w, run_id)
    assert result.status == RunStatus.SUCCESS, result.message
    with w.engine_db.connect() as conn:
        tasks = dict(
            conn.execute(
                text(
                    "SELECT t.TASK_CODE AS task_code,l.STATUS AS status FROM AUD_TASK_RUN_LOG l "
                    "JOIN CFG_TASKS t ON t.TASK_ID=l.TASK_ID WHERE l.PIPELINE_RUN_ID=:run"
                ),
                {"run": run_id},
            ).all()
        )
    assert tasks["validate_file"] == RunStatus.SUCCESS
    assert tasks["land"] == RunStatus.SKIPPED and tasks["apply"] == RunStatus.SKIPPED
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('uploaded')}") == [(0,)]


@warehouses("duckdb")
def test_a_marked_validation_does_not_release_unvalidated_files(upload_world):
    w, owner = upload_world
    receipt = submit(owner, "alice", b"id|name\n1|never validated\n")
    act(
        owner,
        ActionName.MARK,
        pipeline_code="P",
        task_code="validate_file",
        run_id=receipt["pipeline_run_id"],
        status=RunStatus.SUCCESS,
        rows=1,
        reason="try to skip validation",
    )
    result = drive_upload(w, receipt["pipeline_run_id"])
    assert result.status == RunStatus.FAILED
    with w.engine_db.connect() as conn:
        error = conn.execute(
            text(
                "SELECT a.ERROR_MESSAGE AS error FROM AUD_TASK_ATTEMPTS a "
                "JOIN AUD_TASK_RUN_LOG l ON l.TASK_RUN_ID=a.TASK_RUN_ID "
                "JOIN CFG_TASKS t ON t.TASK_ID=l.TASK_ID WHERE t.TASK_CODE='land' "
                "AND l.PIPELINE_RUN_ID=:run"
            ),
            {"run": receipt["pipeline_run_id"]},
        ).scalar_one()
    assert "FILE_VALIDATION has not accepted" in error
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('landed')}") == [(0,)]


@warehouses("duckdb")
def test_archived_upload_reruns_through_real_validation_and_loading(upload_world, tmp_path):
    from datetime import UTC, datetime, timedelta

    from etl_craft.config.model import Retention
    from etl_craft.config.object_models import Artifacts
    from etl_craft.engine.upload_storage import recorded_upload
    from etl_craft.execution.reruns import rerun_task
    from etl_craft.services.retention import purge_history

    w, owner = upload_world
    w.config = replace(
        w.config,
        retention=Retention(run_history_days=1),
        uploads=replace(w.config.uploads, archive_to=Artifacts((tmp_path / "archive").as_uri())),
    )
    owner = replace(owner, config=w.config)
    receipt = submit(owner, "alice", b"id|name\n1|archived\n")
    run_id = receipt["pipeline_run_id"]
    result = drive_upload(w, run_id)
    assert result.status == RunStatus.SUCCESS, result.message
    with acting_as(SYSTEM_ACTOR):
        with w.engine_db.begin() as conn:
            conn.execute(
                text("UPDATE AUD_UPLOADS SET ENDED_AT=:ended WHERE UPLOAD_ID=:id"),
                {"ended": datetime.now(UTC) - timedelta(days=2), "id": receipt["upload_id"]},
            )
        counts = purge_history(w.engine_db, w.config, datetime.now(UTC), dry_run=False)
        assert counts["upload_files"] == 1
    upload = recorded_upload(w.engine_db, receipt["upload_id"])
    assert not (w.config.host_dir / upload.relative(processed=True)).exists()
    assert not list((w.config.host_dir / ".upload_inputs").glob("**/content"))
    w.warehouse.dispose()
    with acting_as(Actor("alice", ActorKind.USER)):
        result = rerun_task(
            w.engine_db,
            w.config,
            "P",
            "validate_file",
            "restore archived input",
            with_downstream=True,
            selector=RunSelector(run_id=run_id),
        )
    assert result.status == RunStatus.SUCCESS, result.message
    assert not list((w.config.host_dir / ".upload_inputs").glob("**/content"))
    with w.warehouse.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT name AS name,CREATED_BY AS creator,UPDATED_BY AS writer "
                    f"FROM {w.name('uploaded')} WHERE id=1"
                )
            )
            .mappings()
            .all()
        )
    assert [dict(row) for row in rows] == [
        {"name": "archived", "creator": "alice", "writer": "alice"}
    ]
    assert (w.config.host_dir / upload.relative(processed=True)).read_bytes() == (
        b"id|name\n1|archived\n"
    )
    with w.engine_db.connect() as conn:
        accepted_attempts = conn.execute(
            text(
                "SELECT COUNT(*) AS count FROM AUD_TASK_ATTEMPTS a "
                "JOIN AUD_TASK_RUN_LOG tr ON tr.TASK_RUN_ID=a.TASK_RUN_ID "
                "JOIN CFG_TASKS t ON t.TASK_ID=tr.TASK_ID "
                "WHERE tr.PIPELINE_RUN_ID=:run AND t.TASK_CODE='validate_file' "
                "AND a.STATUS='SUCCESS'"
            ),
            {"run": run_id},
        ).scalar_one()
    assert accepted_attempts == 2


@warehouses("duckdb")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_api_edit_and_cli_upload_keep_each_cells_actual_human_writer(
    upload_world, monkeypatch, capsys, tmp_path
):
    import json

    from fastapi.testclient import TestClient

    from etl_craft.api.app import create_app
    from etl_craft.cli import main
    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    w, owner = upload_world
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
    tokens = {}
    for name in ("alice", "bob"):
        tokens[name] = act(
            owner, ActionName.LOGIN, name=name, password="correct horse battery"
        ).access_token
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
    with TestClient(create_app(owner)) as client:
        alice = {"Authorization": "Bearer " + tokens["alice"]}
        uploaded = client.post(
            "/api/v1/projects/default/uploads?pipeline_code=P",
            headers=alice,
            files={"file": ("data.csv", b"id|name\n1|Initial\n", "text/csv")},
        )
        assert uploaded.status_code == 200, uploaded.text
        first = uploaded.json()
        assert drive_upload(w, first["pipeline_run_id"]).status == RunStatus.SUCCESS
        edited = client.post(
            "/api/v1/projects/default/values",
            headers=alice,
            json={
                "pipeline_code": "P",
                "task_code": "apply",
                "key": {"id": 1},
                "values": {"name": "Corrected"},
                "reason": "correct",
            },
        )
        assert edited.status_code == 200, edited.text
        assert w.rows(f"SELECT UPLOAD_ID FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y'") == [
            (first["upload_id"],)
        ]
        path = tmp_path / "data.csv"
        path.write_bytes(b"id|name\n1|From Bob\n")
        refreshed = act(owner, ActionName.PIPELINE_REFRESH, pipeline_code="P")
        assert not refreshed.failed, refreshed
        monkeypatch.setenv("ETL_CRAFT_TOKEN", tokens["bob"])
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
        assert drive_upload(w, second["pipeline_run_id"]).status == RunStatus.SUCCESS
        evidence = client.post(
            "/api/v1/projects/default/values/provenance",
            headers=alice,
            json={"pipeline_code": "P", "task_code": "apply", "key": {"id": 1}},
        )
        assert evidence.status_code == 200, evidence.text
        cells = {r["column_name"]: r for r in evidence.json()["records"]}
        assert cells["id"]["writer"] == "alice"
        assert cells["name"]["writer"] == "bob"
        assert cells["name"]["locked"]
        assert "upload_id" not in cells
        refused = client.post(
            "/api/v1/projects/default/values",
            headers=alice,
            json={
                "pipeline_code": "P",
                "task_code": "apply",
                "key": {"id": 1},
                "values": {"upload_id": 999},
                "reason": "cannot forge provenance",
            },
        )
        assert refused.status_code == 400 and "managed" in refused.text
        assert w.rows(f"SELECT UPLOAD_ID FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y'") == [
            (second["upload_id"],)
        ]


@warehouses("duckdb", "postgres", "trino_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_first_upload_refuses_nested_target_before_any_target_write(upload_world):
    from fixtures.single_merge import target_mutations

    w, owner = upload_world
    kind = "ARRAY(INTEGER)" if w.kind == "trino_iceberg" else "INTEGER[]"
    w.execute(f"ALTER TABLE {w.name('uploaded')} ADD COLUMN numbers {kind}")
    before = w.rows(f"SELECT * FROM {w.name('uploaded')}")
    upload = submit(owner, "alice", b"id|name\n1|Manual\n")
    with target_mutations(w, "uploaded") as statements:
        outcome = drive_upload(w, upload["pipeline_run_id"])
    assert outcome.status == RunStatus.FAILED
    with w.engine_db.connect() as conn:
        attempts = (
            conn.execute(
                text(
                    "SELECT ERROR_MESSAGE AS error_message,LOG_PATH AS log_path "
                    "FROM AUD_TASK_ATTEMPTS WHERE STATUS='FAILED'"
                )
            )
            .mappings()
            .all()
        )
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS")).scalar_one() == 0
    assert len(attempts) == 1
    from pathlib import Path

    for part in (
        w.name("uploaded"),
        "numbers",
        kind,
        "canonical scalar hash",
        "cast it to a scalar type in the SELECT",
    ):
        assert part.upper() in attempts[0]["error_message"].upper(), attempts
        assert part.upper() in Path(attempts[0]["log_path"]).read_text(encoding="utf-8").upper()
    assert statements == []
    assert w.rows(f"SELECT * FROM {w.name('uploaded')}") == before


@warehouses("duckdb", "postgres", "trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_upload_false_releases_row_and_cells_and_true_relocks(
    upload_world, monkeypatch, capsys, tmp_path
):
    from fixtures.stewardship import check_upload_controls

    check_upload_controls(upload_world, monkeypatch, capsys, tmp_path)


@warehouses("duckdb", "postgres", "trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE"], indirect=True)
def test_upload_schema_refuses_invalid_locked_value_without_target_write(upload_world):
    w, owner = upload_world
    uploaded = submit(owner, "alice", b"id|name|LOCKED\n1|bad|maybe\n")
    result = drive_upload(w, uploaded["pipeline_run_id"])
    assert result.status == RunStatus.FAILED
    with w.engine_db.connect() as conn:
        reason = conn.execute(
            text("SELECT REASON AS reason FROM AUD_UPLOADS WHERE UPLOAD_ID=:id"),
            {"id": uploaded["upload_id"]},
        ).scalar_one()
    for part in (
        str(uploaded["upload_id"]),
        "row 2",
        "LOCKED",
        "maybe",
        "true",
        "false",
        "NULL",
        "corrected file",
    ):
        assert part in reason, reason
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('uploaded')}") == [(0,)]


@warehouses("duckdb", "postgres", "trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_staged_locked_text_is_refused_before_target_write(upload_world):
    w, owner = upload_world
    with w.engine_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE=replace(PARAMETER_VALUE,"
                "',LOCKED ',',CAST(LOCKED AS VARCHAR) AS LOCKED ') "
                "WHERE PARAMETER_NAME='SELECT_QUERY'"
            )
        )
    uploaded = submit(owner, "alice", b"id|name|LOCKED\n1|valid file|true\n")
    result = drive_upload(w, uploaded["pipeline_run_id"])
    assert result.status == RunStatus.FAILED
    with w.engine_db.connect() as conn:
        message = conn.execute(
            text(
                "SELECT ERROR_MESSAGE AS message FROM AUD_TASK_RUN_LOG "
                "WHERE PIPELINE_RUN_ID=:run AND STATUS='FAILED'"
            ),
            {"run": uploaded["pipeline_run_id"]},
        ).scalar_one()
    found_type = "CHARACTER VARYING" if w.kind == "postgres" else "VARCHAR"
    for part in ("P.apply", "LOCKED", found_type, "BOOLEAN", "CAST", "landing"):
        assert part in message, message
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('uploaded')}") == [(0,)]
    with w.engine_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS")).scalar_one() == 0


@warehouses("duckdb", "postgres", "trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize("upload_world", ["SCD1_MERGE", "SCD2_MERGE"], indirect=True)
def test_service_upload_false_neither_creates_nor_releases_locks(upload_world):
    import json

    from fastapi.testclient import TestClient

    from etl_craft.api.app import create_app
    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    w, owner = upload_world
    human = submit(owner, "alice", b"id|name\n1|human\n")
    result = drive_upload(w, human["pipeline_run_id"])
    assert result.status == RunStatus.SUCCESS, result.message
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
    token = act(owner, ActionName.TOKEN_CREATE, name="robot", role=ApiRole.ADMIN)
    with TestClient(create_app(owner)) as client:
        response = client.post(
            "/api/v1/projects/default/uploads?pipeline_code=P",
            headers={"Authorization": "Bearer " + token.token},
            files={
                "file": ("service.csv", b"id|name|LOCKED\n1|robot|false\n2|new|true\n", "text/csv")
            },
        )
        assert response.status_code == 200, response.text
        result = drive_upload(w, response.json()["pipeline_run_id"])
        assert result.status == RunStatus.SUCCESS, result.message
    rows = w.rows(
        f"SELECT id,name,ETL_PROTECTION FROM {w.name('uploaded')} WHERE ACTIVE_FLAG='Y' ORDER BY id"
    )
    assert rows[0][1] == "human"
    assert json.loads(rows[0][2])["cells"]["*"]["locked"]
    assert rows[1][1] == "new"
    assert not any(cell["locked"] for cell in json.loads(rows[1][2])["cells"].values())
    with w.engine_db.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS "
                    "WHERE UPLOAD_ID=:upload AND KIND='UNLOCK'"
                ),
                {"upload": response.json()["upload_id"]},
            ).scalar_one()
            == 0
        )


@warehouses("duckdb", "postgres", "trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize(
    "upload_world", [("SCD2_MERGE", "sqlite"), ("SCD2_MERGE", "postgresql")], indirect=True
)
@pytest.mark.parametrize(
    "point", ["before_pending", "after_pending", "after_merge", "after_committed"]
)
def test_false_upload_unlock_events_recover_with_the_same_merge(upload_world, monkeypatch, point):
    from fixtures.stewardship import check_upload_recovery

    check_upload_recovery(upload_world, monkeypatch, point)


@warehouses("postgres")
@pytest.mark.parametrize(
    "upload_world",
    [
        ("SCD1_MERGE", "sqlite"),
        ("SCD1_MERGE", "postgresql"),
        ("SCD2_MERGE", "sqlite"),
        ("SCD2_MERGE", "postgresql"),
    ],
    indirect=True,
)
def test_pre15_real_uploads_preserve_controls_and_mixed_writers(
    upload_world, monkeypatch, capsys, tmp_path
):
    import os

    from etl_craft.dialects.warehouse.postgres import PostgresWarehouse
    from fixtures.stewardship import check_upload_controls

    monkeypatch.setattr(PostgresWarehouse, "supports_insert_merge", lambda self, conn: False)
    setup = (
        "from etl_craft.dialects.warehouse.postgres import PostgresWarehouse\n"
        "PostgresWarehouse.supports_insert_merge = lambda self, conn: False\n"
    )
    hook = tmp_path / "pre15"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(setup)
    monkeypatch.setenv("PYTHONPATH", str(hook) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    check_upload_controls(
        upload_world, monkeypatch, capsys, tmp_path, child_setup=setup, merge_statements=2
    )
