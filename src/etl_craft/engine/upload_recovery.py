"""Recover committed upload moves and remove uncommitted receive leftovers."""

import logging
import os
import shutil
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import ConfigurationError, LockTimeoutError
from etl_craft.core.faults import fault_point
from etl_craft.core.file_bytes import parent_directory
from etl_craft.core.upload_names import upload_key
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id
from etl_craft.engine.upload_archive import archive_location, publish_archive, verify_archive
from etl_craft.engine.upload_storage import (
    StoredUpload,
    exists,
    processed_file,
    recorded_upload,
    settled_upload,
    storage_lock,
    unlink_file,
)

logger = logging.getLogger(__name__)


def clean_run_inputs(engine: Engine, config: ConnectorConfig, run_id: int) -> None:
    """Discard only ended attempts' private copies, never a canonical upload source."""
    with engine.connect() as conn:
        attempts = tuple(
            conn.execute(statement(conn, "upload_run_attempts"), {"run_id": run_id}).scalars()
        )
    for attempt_id in attempts:
        relative = f".upload_inputs/{attempt_id}"
        try:
            with parent_directory(config.host_dir, relative) as parent:
                shutil.rmtree(str(attempt_id), dir_fd=parent)
                os.fsync(parent)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ConfigurationError(
                f"run {run_id}, attempt {attempt_id}, cache {config.host_dir / relative}: "
                f"errno={error.errno}; expected a writable private attempt directory; "
                "restore the upload cache layout and permissions, then retry cleanup"
            ) from error


def finish_run_files(engine: Engine, config: ConnectorConfig, run_id: int) -> None:
    """After the ending commits, finish every file's same-filesystem move."""
    fault_point("upload.after_ending_commit")
    with engine.connect() as conn:
        ids = tuple(
            conn.execute(statement(conn, "upload_completed_run"), {"run_id": run_id}).scalars()
        )
    if ids:
        clean_run_inputs(engine, config, run_id)
    for upload_id in ids:
        with storage_lock(config, upload_id):
            upload = recorded_upload(engine, upload_id)
            if upload.archive_location is None:
                processed_file(config, upload)


def finish_archive(config: ConnectorConfig, upload: StoredUpload) -> None:
    """Keep a valid local source until the recorded archive is complete and verified."""
    try:
        source = upload.relative(processed=True)
        if exists(config.host_dir, source):
            publish_archive(config, upload, source)
            fault_point("upload.before_local_delete")
            if upload.run_status not in {RunStatus.IN_PROGRESS, RunStatus.QUEUED}:
                unlink_file(config.host_dir, source)
        else:
            verify_archive(config, upload)
    except (ConfigurationError, OSError) as error:
        raise ConfigurationError(
            f"upload {upload.upload_id}, archive {upload.archive_location}: {error}; "
            "expected the recorded file in local storage or its verified archive; "
            "restore the archive and storage permissions or upload the file again"
        ) from error


def archive_uploads(
    engine: Engine, config: ConnectorConfig, now: datetime, *, dry_run: bool = False
) -> int:
    """Use the existing run-history lifetime while preserving every upload audit row."""
    days = config.retention.run_history_days
    if days is None:
        return 0
    params = {
        "project_id": current_project_id(),
        "cutoff": now - timedelta(days=days),
        "after_id": 0,
    }
    count = 0
    while True:
        with engine.connect() as conn:
            ids = tuple(
                conn.execute(statement(conn, "upload_retention_candidates"), params).scalars()
            )
        if not ids:
            return count
        if dry_run:
            count += len(ids)
            params["after_id"] = ids[-1]
            continue
        for upload_id in ids:
            with storage_lock(config, upload_id), acting_as(SYSTEM_ACTOR):
                upload = recorded_upload(engine, upload_id)
                if upload.run_id is not None:
                    clean_run_inputs(engine, config, upload.run_id)
                processed_file(config, upload)
                location = archive_location(config, upload)
                with engine.begin() as conn:
                    conn.execute(
                        statement(conn, "upload_archive"),
                        {"upload_id": upload_id, "location": location, "now": now},
                    )
                fault_point("upload.after_archive_commit")
                finish_archive(config, recorded_upload(engine, upload_id))
                count += 1


def _files(root: Path) -> Iterator[tuple[Path, bool]]:
    if root.is_symlink():
        raise ConfigurationError(
            f"upload directory {root}: found a symlink; expected an ordinary directory; "
            "restore the managed upload tree"
        )
    if not root.exists():
        return
    with os.scandir(root) as folders:
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir(follow_symlinks=False):
                raise ConfigurationError(
                    f"upload directory {folder.path}: expected an ordinary pipeline folder; "
                    "restore the managed upload tree"
                )
            upload_key(folder.name, "1-upload")
            with os.scandir(folder.path) as files:
                for entry in files:
                    if entry.name == ".incoming" and entry.is_dir(follow_symlinks=False):
                        with os.scandir(entry.path) as temporary:
                            for pending in temporary:
                                yield Path(pending.path), True
                    else:
                        yield Path(entry.path), False


@acting_as(SYSTEM_ACTOR)
def recover_uploads(engine: Engine, config: ConnectorConfig) -> None:
    """Startup and maintenance reconcile only names on disk against committed rows."""
    cleaned = set()
    for directory in ("uploads", "processed_uploads"):
        for path, incoming in _files(config.host_dir / directory):
            restoring = path.name.startswith(".restore-")
            identity = path.name.removeprefix(".restore-").split("-", 1)[0]
            if not identity.isdecimal():
                raise ConfigurationError(
                    f"upload file {path}: expected an id-prefixed stored name; "
                    "restore the managed upload tree"
                )
            try:
                with storage_lock(config, int(identity), wait_seconds=0.001):
                    upload = settled_upload(engine, int(identity))
                    relative = str(path.relative_to(config.host_dir))
                    if upload is None or incoming or restoring:
                        unlink_file(config.host_dir, relative)
                        logger.info("removed uncommitted upload leftover %s", path)
                        continue
                    expected = upload.relative(processed=directory == "processed_uploads")
                    if relative != expected:
                        raise ConfigurationError(
                            f"upload {upload.upload_id}: path={path}; expected "
                            f"{config.host_dir / expected}; restore the stored name"
                        )
                    if upload.ended_at is not None:
                        if upload.run_id is not None and upload.run_id not in cleaned:
                            clean_run_inputs(engine, config, upload.run_id)
                            cleaned.add(upload.run_id)
                        if directory == "uploads":
                            processed_file(config, upload)
                        if upload.archive_location is not None:
                            finish_archive(config, upload)
            except LockTimeoutError:
                # A receiving or reading process still owns this exact file; it is not an orphan.
                continue
