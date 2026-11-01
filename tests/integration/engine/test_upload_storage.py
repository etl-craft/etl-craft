"""Upload bytes and their audit identities recover together after real process loss."""

import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from etl_craft.config.model import Retention
from etl_craft.config.object_models import Artifacts
from etl_craft.core.actor import Actor, acting_as
from etl_craft.core.enums import ActorKind, RunStatus
from etl_craft.core.errors import ConfigurationError
from etl_craft.engine import transitions
from etl_craft.engine.upload_recovery import archive_uploads, finish_run_files, recover_uploads
from etl_craft.engine.upload_storage import local_file, recorded_upload, storage_lock
from etl_craft.services.operations.uploads import UploadRequest, receive
from fixtures.engine_db import profile_block
from fixtures.uploads import upload_api as upload_api

CONTENT = b"id|name\n1|accepted\n"


def caller(ctx):
    return replace(ctx, actor=Actor("writer", ActorKind.SERVICE), project_id=1, project="default")


def submit(ctx, data=CONTENT, name="data.csv"):
    with receive(caller(ctx), UploadRequest(pipeline_code="P")) as receipt:
        receipt.begin_file(name, "text/csv")
        receipt.write(data)
    return receipt.result


def file_rows(ctx):
    with ctx.engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT UPLOAD_ID AS upload_id,STORED_NAME AS stored_name,STATUS AS status,"
                    "PIPELINE_RUN_ID AS run_id FROM AUD_UPLOADS ORDER BY UPLOAD_ID"
                )
            )
            .mappings()
            .all()
        )


def end_run(ctx, run_id, status=RunStatus.SUCCESS):
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        transitions.finalize_pipeline_run(conn, run_id, status)
    finish_run_files(ctx.engine, ctx.config, run_id)


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("../recognisable.csv", ".._recognisable.csv"),
        (r"..\folder\name.csv", ".._folder_name.csv"),
        ("résumé.csv", "r_sum_.csv"),
        ("", "upload"),
        ("x" * 251 + ".csv", "x" * 251 + ".csv"),
    ],
)
def test_stored_names_are_safe_immutable_and_visible(upload_api, name, safe):
    ctx, client, writer, _ = upload_api
    from urllib.parse import quote

    filename = "filename*=UTF-8''" + quote(name, safe="") if name else 'filename=""'
    body = (
        (
            '--upload\r\nContent-Disposition: form-data; name="file"; '
            + filename
            + "\r\nContent-Type: text/csv\r\n\r\n"
        ).encode()
        + CONTENT
        + b"\r\n--upload--\r\n"
    )
    response = client.post(
        "/api/v1/uploads?pipeline_code=P",
        content=body,
        headers={
            "Authorization": f"Bearer {writer.token}",
            "Content-Type": "multipart/form-data; boundary=upload",
        },
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    row = file_rows(ctx)[0]
    assert row["stored_name"] == f"{receipt['upload_id']}-{safe}"[:255]
    assert len(row["stored_name"].encode("ascii")) <= 255
    path = ctx.config.host_dir / "uploads" / "P" / row["stored_name"]
    assert path.read_bytes() == CONTENT
    assert "/" not in row["stored_name"] and "\\" not in row["stored_name"]
    response = client.get(
        "/api/v1/uploads?pipeline_code=P", headers={"Authorization": f"Bearer {writer.token}"}
    )
    assert response.status_code == 200
    assert response.json()["uploads"][0]["stored_name"] == row["stored_name"]
    assert response.json()["uploads"][0]["file_name"] == name
    with pytest.raises(Exception, match="STORED_NAME is immutable"), ctx.engine.begin() as conn:
        conn.execute(text("UPDATE AUD_UPLOADS SET STORED_NAME='99-changed.csv'"))


@pytest.mark.parametrize("status", [RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED])
def test_ended_files_leave_the_pipeline_folder_but_later_queue_stays(upload_api, status):
    from etl_craft.controller.uploads import admit_pending

    ctx, _, _, _ = upload_api
    first = submit(ctx)
    later = submit(ctx, CONTENT.replace(b"accepted", b"later"))
    end_run(ctx, first["pipeline_run_id"], status)
    rows = file_rows(ctx)
    assert (
        ctx.config.host_dir / "processed_uploads/P" / rows[0]["stored_name"]
    ).read_bytes() == CONTENT
    assert not (ctx.config.host_dir / "uploads/P" / rows[0]["stored_name"]).exists()
    assert (ctx.config.host_dir / "uploads/P" / rows[1]["stored_name"]).exists()
    admit_pending(ctx)
    with ctx.engine.connect() as conn:
        run_id = conn.execute(
            text("SELECT PIPELINE_RUN_ID AS id FROM AUD_UPLOADS WHERE UPLOAD_ID=:id"),
            {"id": later["upload_id"]},
        ).scalar_one()
    end_run(ctx, run_id)
    assert not (ctx.config.host_dir / "uploads/P" / rows[1]["stored_name"]).exists()
    assert (ctx.config.host_dir / "processed_uploads/P" / rows[1]["stored_name"]).exists()


def test_file_archive_restores_recorded_bytes_and_refuses_corruption(upload_api, tmp_path):
    ctx, _, _, _ = upload_api
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            retention=Retention(run_history_days=1),
            uploads=replace(
                ctx.config.uploads, archive_to=Artifacts((tmp_path / "archive").as_uri())
            ),
        ),
    )
    first = submit(ctx)
    end_run(ctx, first["pipeline_run_id"])
    with acting_as(ctx.actor):
        assert archive_uploads(ctx.engine, ctx.config, datetime.now(UTC) + timedelta(days=2)) == 1
    upload = recorded_upload(ctx.engine, first["upload_id"])
    assert upload.archive_location is not None and upload.archived_at is not None
    assert not (ctx.config.host_dir / upload.relative(processed=True)).exists()
    with storage_lock(ctx.config, upload.upload_id):
        relative = local_file(ctx.config, upload)
    assert (ctx.config.host_dir / relative).read_bytes() == CONTENT
    (ctx.config.host_dir / relative).unlink()
    archive = Path(upload.archive_location.removeprefix("file://"))
    archive.write_bytes(b"changed")
    with pytest.raises(ConfigurationError) as failure:
        local_file(ctx.config, upload)
    for expected in [
        str(upload.upload_id),
        "SHA-256",
        upload.sha256,
        hashlib.sha256(b"changed").hexdigest(),
        "upload the file again",
    ]:
        assert expected in str(failure.value)
    archive.unlink()
    with pytest.raises(ConfigurationError, match=r"restore.*archive|archive.*restore"):
        local_file(ctx.config, upload)


@pytest.mark.parametrize("acknowledged", [False, True])
def test_commit_error_is_resolved_before_deleting_the_file(upload_api, acknowledged):
    ctx, _, _, _ = upload_api
    dialect = ctx.engine.dialect
    original = dialect.do_commit
    injected = False

    def commit(connection):
        nonlocal injected
        # The receipt transaction has its final file; the earlier audit identity does not.
        files = list((ctx.config.host_dir / "uploads/P").glob("[0-9]*-*.csv"))
        if files and not injected:
            injected = True
            if acknowledged:
                original(connection)
            raise OSError("lost commit acknowledgement")
        return original(connection)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(dialect, "do_commit", commit)
        if acknowledged:
            result = submit(ctx)
            assert result["upload_id"]
        else:
            with pytest.raises(ConfigurationError, match="storage failed"):
                submit(ctx)
    assert injected
    files = list((ctx.config.host_dir / "uploads/P").glob("[0-9]*-*.csv"))
    assert len(files) == int(acknowledged)
    rows = file_rows(ctx)
    assert rows[0]["status"] == ("QUEUED" if acknowledged else "REFUSED")


def child_receive(ctx, directory, point):
    config_file = directory / "craft-connector.yml"
    engine = profile_block(ctx.config.engine, ctx.config.engine.schema)
    if ctx.engine.dialect.name == "sqlite":
        engine["Jdbc_url"] = "jdbc:sqlite:" + str(Path(ctx.engine.url.database).absolute())
    config_file.write_text(
        yaml.safe_dump(
            {"Secrets": {"Source_type": "ENVIRONMENT"}, "Engine": {"dev": engine}}, sort_keys=False
        )
    )
    script = """
import sys
from etl_craft.config import load_config
from etl_craft.dialects.engine import build_engine
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.uploads import receive, UploadRequest
from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActorKind, ApiRole
config = load_config(sys.argv[1])
ctx = OperationContext(build_engine(config), config, Actor("writer", ActorKind.SERVICE),
                       role=ApiRole.ADMIN, project="default", project_id=1)
with receive(ctx, UploadRequest(pipeline_code="P")) as receipt:
    receipt.begin_file("data.csv", "text/csv")
    receipt.write(b"id|name\\n1|accepted\\n")
"""
    env = dict(os.environ, ETL_CRAFT_FAULT=point + ":kill")
    result = subprocess.run(
        [sys.executable, "-c", script, str(config_file)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 137, result.stdout + result.stderr


@pytest.mark.chaos
@pytest.mark.parametrize(
    "point", ["upload.after_bytes", "upload.after_rename", "upload.after_commit"]
)
def test_real_receive_kill_recovers_only_committed_files(upload_api, point):
    ctx, _, _, _ = upload_api
    child_receive(ctx, ctx.config.host_dir, point)
    recover_uploads(ctx.engine, ctx.config)
    files = list((ctx.config.host_dir / "uploads/P").glob("[0-9]*-*.csv"))
    incoming = list((ctx.config.host_dir / "uploads/P/.incoming").iterdir())
    assert incoming == []
    rows = file_rows(ctx)
    if point == "upload.after_commit":
        assert len(rows) == len(files) == 1
        assert files[0].read_bytes() == CONTENT
    else:
        assert rows == [] and files == []


def test_concurrent_identical_receipts_leave_exactly_one_file(upload_api):
    from etl_craft.core.errors import UsageError
    from fixtures.races import two_at_once

    ctx, _, _, _ = upload_api

    def upload():
        try:
            return submit(ctx)
        except UsageError as error:
            assert "duplicates upload" in str(error)
            assert "expected new file contents" in str(error)
            return None

    results = two_at_once(
        upload, upload, at="etl_craft.services.operations.uploads._require_pipeline"
    )
    assert sum(result is not None for result in results) == 1
    rows = file_rows(ctx)
    assert sum(row["status"] == "QUEUED" for row in rows) == 1
    assert sum(row["status"] == "REFUSED" for row in rows) == 1
    assert len(list((ctx.config.host_dir / "uploads/P").glob("[0-9]*-*.csv"))) == 1
    assert list((ctx.config.host_dir / "uploads/P/.incoming").iterdir()) == []


@pytest.mark.chaos
@pytest.mark.parametrize(
    "point",
    [
        "upload.after_ending_commit",
        "upload.during_rename",
        "upload.after_processed_rename",
        "upload.after_archive_commit",
        "upload.archive_during_write",
        "upload.before_local_delete",
    ],
)
def test_real_ending_and_archive_kills_recover_without_lost_bytes(upload_api, point):
    ctx, _, _, _ = upload_api
    first = submit(ctx)
    engine = profile_block(ctx.config.engine, ctx.config.engine.schema)
    if ctx.engine.dialect.name == "sqlite":
        engine["Jdbc_url"] = "jdbc:sqlite:" + str(Path(ctx.engine.url.database).absolute())
    archive = ctx.config.host_dir / "archive"
    config_file = ctx.config.host_dir / "craft-connector.yml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "Secrets": {"Source_type": "ENVIRONMENT"},
                "Engine": {"dev": engine},
                "Retention": {"Run_history_days": 1},
                "Uploads": {"Archive_to": archive.as_uri()},
            },
            sort_keys=False,
        )
    )
    script = """
import sys
from datetime import UTC, datetime, timedelta
from etl_craft.config import load_config
from etl_craft.dialects.engine import build_engine
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.upload_recovery import finish_run_files, archive_uploads
config = load_config(sys.argv[1])
engine = build_engine(config)
with acting_as(SYSTEM_ACTOR):
    with engine.begin() as conn:
        transitions.finalize_pipeline_run(conn, int(sys.argv[2]), RunStatus.SUCCESS)
    finish_run_files(engine, config, int(sys.argv[2]))
    archive_uploads(engine, config, datetime.now(UTC) + timedelta(days=2))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(config_file), str(first["pipeline_run_id"])],
        env=dict(os.environ, ETL_CRAFT_FAULT=point + ":kill"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 137, result.stdout + result.stderr
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            retention=Retention(run_history_days=1),
            uploads=replace(ctx.config.uploads, archive_to=Artifacts(archive.as_uri())),
        ),
    )
    recover_uploads(ctx.engine, ctx.config)
    with acting_as(ctx.actor):
        archive_uploads(ctx.engine, ctx.config, datetime.now(UTC) + timedelta(days=2))
    upload = recorded_upload(ctx.engine, first["upload_id"])
    assert upload.archive_location is not None
    assert not (ctx.config.host_dir / upload.relative(processed=False)).exists()
    assert not (ctx.config.host_dir / upload.relative(processed=True)).exists()
    assert (ctx.config.host_dir / local_file(ctx.config, upload)).read_bytes() == CONTENT
    assert file_rows(ctx)[0]["run_id"] == first["pipeline_run_id"]


def test_missing_committed_file_names_upload_paths_and_remedy(upload_api):
    ctx, _, _, _ = upload_api
    first = submit(ctx)
    upload = recorded_upload(ctx.engine, first["upload_id"])
    expected = ctx.config.host_dir / upload.relative(processed=False)
    expected.unlink()
    with pytest.raises(ConfigurationError) as failure:
        local_file(ctx.config, upload)
    assert str(upload.upload_id) in str(failure.value)
    assert str(expected) in str(failure.value)
    assert "upload the file again" in str(failure.value)


def test_s3_archive_uses_explicit_profile_and_restores_verified_bytes(upload_api, monkeypatch):
    from urllib.parse import urlsplit
    from uuid import uuid4

    from etl_craft.config.object_models import ObjectStore
    from etl_craft.core.enums import ObjectStoreAuth, ObjectUrlStyle
    from etl_craft.dialects.credentials import S3Objects
    from fixtures.services import MINIO_BUCKET, MINIO_PASSWORD, MINIO_USER, require

    minio = require("minio")
    monkeypatch.setenv("UPLOAD_ACCESS", MINIO_USER)
    monkeypatch.setenv("UPLOAD_SECRET", MINIO_PASSWORD)
    profile = ObjectStore(
        "archive",
        minio.http_url,
        "us-east-1",
        ObjectUrlStyle.PATH,
        ObjectStoreAuth.KEYS,
        "UPLOAD_ACCESS",
        "UPLOAD_SECRET",
    )
    ctx, _, _, _ = upload_api
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            object_stores={"archive": profile},
            retention=Retention(run_history_days=1),
            uploads=replace(
                ctx.config.uploads,
                archive_to=Artifacts(f"s3://{MINIO_BUCKET}/uploads/{uuid4().hex}", "archive"),
            ),
        ),
    )
    first = submit(ctx)
    end_run(ctx, first["pipeline_run_id"])
    with acting_as(ctx.actor):
        assert archive_uploads(ctx.engine, ctx.config, datetime.now(UTC) + timedelta(days=2)) == 1
    upload = recorded_upload(ctx.engine, first["upload_id"])
    address = urlsplit(upload.archive_location)
    key = address.path.lstrip("/")
    client = S3Objects(ctx.config, profile).client
    try:
        assert (ctx.config.host_dir / local_file(ctx.config, upload)).read_bytes() == CONTENT
        (ctx.config.host_dir / upload.relative(processed=True)).unlink()
        missing = replace(ctx.config, object_stores={})
        with pytest.raises(ConfigurationError, match=r"profile.*archive.*missing.*restore"):
            local_file(missing, upload)
        client.put_object(Bucket=MINIO_BUCKET, Key=key, Body=b"changed")
        with pytest.raises(ConfigurationError, match=r"SHA-256.*expected SHA-256"):
            local_file(ctx.config, upload)
        client.delete_object(Bucket=MINIO_BUCKET, Key=key)
        with pytest.raises(ConfigurationError, match=r"upload.*archive.*restore"):
            local_file(ctx.config, upload)
    finally:
        client.delete_object(Bucket=MINIO_BUCKET, Key=key)


def test_read_refuses_symlink_in_place_of_recorded_bytes(upload_api, tmp_path):
    ctx, _, _, _ = upload_api
    first = submit(ctx)
    upload = recorded_upload(ctx.engine, first["upload_id"])
    path = ctx.config.host_dir / upload.relative(processed=False)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(CONTENT)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ConfigurationError, match="without symlinks"):
        local_file(ctx.config, upload)
    assert outside.read_bytes() == CONTENT


def test_pipeline_rename_keeps_the_recorded_receipt_folder(upload_api):
    ctx, _, _, _ = upload_api
    first = submit(ctx)
    end_run(ctx, first["pipeline_run_id"])
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_PIPELINES SET PIPELINE_CODE='RENAMED' WHERE PIPELINE_CODE='P'")
        )
    upload = recorded_upload(ctx.engine, first["upload_id"])
    assert upload.pipeline_code == "P"
    assert (ctx.config.host_dir / local_file(ctx.config, upload)).read_bytes() == CONTENT


def test_controller_start_removes_uncommitted_leftovers_and_logs_them(upload_api, caplog):
    import logging
    import threading

    from etl_craft.controller.supervisor import serve

    ctx, _, _, _ = upload_api
    folder = ctx.config.host_dir / "uploads/P/.incoming"
    folder.mkdir(parents=True)
    incoming = folder / "9000-uncommitted"
    final = folder.parent / "9001-orphan.csv"
    incoming.write_bytes(CONTENT)
    final.write_bytes(CONTENT)
    stop = threading.Event()
    stop.set()
    ctx = replace(
        ctx,
        config=replace(
            ctx.config, artifacts=Artifacts((ctx.config.host_dir / "artifacts").as_uri())
        ),
    )
    with caplog.at_level(logging.INFO):
        serve(caller(ctx), stop)
    assert not incoming.exists() and not final.exists()
    assert str(incoming) in caplog.text and str(final) in caplog.text


def test_oversized_archive_is_bounded_before_restoration(upload_api, monkeypatch, tmp_path):
    from contextlib import contextmanager

    from etl_craft.engine import upload_archive

    ctx, _, _, _ = upload_api
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            retention=Retention(run_history_days=1),
            uploads=replace(
                ctx.config.uploads, archive_to=Artifacts((tmp_path / "archive").as_uri())
            ),
        ),
    )
    first = submit(ctx)
    end_run(ctx, first["pipeline_run_id"])
    with acting_as(ctx.actor):
        archive_uploads(ctx.engine, ctx.config, datetime.now(UTC) + timedelta(days=2))
    upload = recorded_upload(ctx.engine, first["upload_id"])
    archive = Path(upload.archive_location.removeprefix("file://"))
    archive.write_bytes(CONTENT * 65536)
    original = upload_archive.archive_stream
    reads = []

    class Bounded:
        def __init__(self, stream):
            self.stream = stream

        def read(self, size):
            assert 0 < size <= upload.size_bytes + 1
            data = self.stream.read(size)
            reads.append(len(data))
            return data

    @contextmanager
    def observed(config, location):
        with original(config, location) as stream:
            yield Bounded(stream)

    monkeypatch.setattr(upload_archive, "archive_stream", observed)
    with pytest.raises(ConfigurationError, match=r"size is at least.*expected exactly.*upload"):
        local_file(ctx.config, upload)
    assert sum(reads) == upload.size_bytes + 1
    assert not (ctx.config.host_dir / upload.relative(processed=True)).exists()
    assert archive.stat().st_size == len(CONTENT) * 65536


@pytest.mark.engine_postgres
@pytest.mark.parametrize("empty_engine_db", ["postgresql"], indirect=True)
def test_receipt_absence_waits_for_the_original_admission_transaction(upload_api, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    from etl_craft.engine import standing_pauses
    from etl_craft.engine.upload_storage import settled_upload
    from fixtures.cancellation import wait_for

    ctx, _, _, _ = upload_api
    first = submit(ctx)
    upload = recorded_upload(ctx.engine, first["upload_id"])
    with ctx.engine.connect() as conn:
        pipeline_id = conn.execute(text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES")).scalar_one()
    reached = threading.Event()
    waiting_pid = []
    original = standing_pauses.lock

    def observed(conn, identity):
        waiting_pid.append(conn.execute(text("SELECT pg_backend_pid() AS pid")).scalar_one())
        reached.set()
        return original(conn, identity)

    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        original(conn, pipeline_id)
        monkeypatch.setattr(standing_pauses, "lock", observed)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(copy_context().run, settled_upload, ctx.engine, upload.upload_id)
            try:
                assert reached.wait(10)
                with ctx.engine.connect() as observer:
                    wait_for(
                        lambda: (
                            future.done()
                            or observer.execute(
                                text(
                                    "SELECT EXISTS(SELECT 1 AS waiting FROM pg_locks "
                                    "WHERE pid=:pid AND locktype='advisory' "
                                    "AND NOT granted) AS blocked"
                                ),
                                {"pid": waiting_pid[0]},
                            ).scalar_one()
                        )
                    )
                assert not future.done()
            finally:
                conn.commit()
            assert future.result(timeout=10) == upload


@pytest.mark.chaos
@pytest.mark.skipif(os.geteuid() == 0, reason="Root bypasses filesystem permission checks")
def test_unwritable_incoming_folder_refuses_then_recovers_the_orphan(upload_api):
    ctx, _, _, _ = upload_api
    incoming = ctx.config.host_dir / "uploads/P/.incoming"
    try:
        with (
            pytest.raises(ConfigurationError, match=r"upload file.*errno=.*restore.*permissions"),
            receive(caller(ctx), UploadRequest(pipeline_code="P")) as receipt,
        ):
            receipt.begin_file("data.csv", "text/csv")
            receipt.write(CONTENT)
            incoming.chmod(0)
    finally:
        incoming.chmod(0o700)
    rows = file_rows(ctx)
    assert rows[0]["status"] == "REFUSED" and rows[0]["stored_name"] is None
    assert rows[0]["run_id"] is None
    recover_uploads(ctx.engine, ctx.config)
    assert list(incoming.iterdir()) == []
    assert list(incoming.parent.glob("[0-9]*-*.csv")) == []
