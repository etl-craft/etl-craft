"""Recorded upload locations, verified reads and recoverable local moves."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.faults import fault_point
from etl_craft.core.file_bytes import open_regular, parent_directory
from etl_craft.core.filelock import file_lock
from etl_craft.core.upload_names import upload_key
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class StoredUpload:
    """Committed file facts; client names never participate in location resolution."""

    upload_id: int
    stored_name: str
    sha256: str
    size_bytes: int
    ended_at: datetime | None
    archive_location: str | None
    archived_at: datetime | None
    run_id: int | None
    pipeline_code: str
    project_id: int
    run_status: str | None

    def relative(self, *, processed: bool) -> str:
        """Build only a checked recorded file identity under its state's directory."""
        directory = "processed_uploads" if processed else "uploads"
        return f"{directory}/{upload_key(self.pipeline_code, self.stored_name)}"


def recorded_upload(engine: Engine, upload_id: int) -> StoredUpload:
    """Start every file read from committed audit metadata."""
    with engine.connect() as conn:
        row = conn.execute(
            statement(conn, "upload_storage"), {"upload_id": upload_id}
        ).one_or_none()
    if row is None:
        raise ConfigurationError(
            f"upload {upload_id}: no committed stored file; expected a received upload; "
            "upload the file again"
        )
    result = StoredUpload(**row._mapping)
    upload_key(result.pipeline_code, result.stored_name)
    return result


def settled_upload(
    engine: Engine, upload_id: int, pipeline_id: int | None = None
) -> StoredUpload | None:
    """Wait for the original admission transaction before proving receipt absence."""
    from etl_craft.engine.standing_pauses import lock

    if pipeline_id is None:
        with engine.connect() as conn:
            pipeline_id = conn.execute(
                statement(conn, "upload_receipt_pipeline"), {"upload_id": upload_id}
            ).scalar_one_or_none()
    with engine.begin() as conn:
        if pipeline_id is not None:
            lock(conn, pipeline_id)
        row = conn.execute(
            statement(conn, "upload_storage"), {"upload_id": upload_id}
        ).one_or_none()
    return StoredUpload(**row._mapping) if row is not None else None


@contextmanager
def storage_lock(
    config: ConnectorConfig, upload_id: int, wait_seconds: float = 0
) -> Iterator[None]:
    """Keep startup cleanup, receipts and storage recovery from racing each other."""
    relative = f".upload_locks/{upload_id}.lock"
    with (
        parent_directory(config.host_dir, relative, create=True),
        file_lock(config.host_dir / relative, wait_seconds),
    ):
        yield


def digest_file(root: Path, relative: str) -> tuple[str, int]:
    """Hash bounded chunks of a regular file without following links."""
    digest, size = hashlib.sha256(), 0
    with open_regular(root, relative) as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def verify_file(config: ConnectorConfig, upload: StoredUpload, relative: str) -> None:
    """Reject corrupt bytes before a script or archival delete can use them."""
    try:
        found, size = digest_file(config.host_dir, relative)
    except ConfigurationError as error:
        raise ConfigurationError(
            f"upload {upload.upload_id}: {error}; expected the recorded file "
            f"SHA-256={upload.sha256}; restore its regular path or upload the file again"
        ) from error
    if (found, size) != (upload.sha256, upload.size_bytes):
        raise ConfigurationError(
            f"upload {upload.upload_id}, path {config.host_dir / relative}: SHA-256={found}, "
            f"size={size}; expected SHA-256={upload.sha256}, size={upload.size_bytes}; "
            "restore the original recorded file or upload the file again"
        )


def exists(root: Path, relative: str) -> bool:
    """Check the leaf without following directory or file links."""
    try:
        with parent_directory(root, relative) as parent:
            os.stat(relative.rsplit("/", 1)[-1], dir_fd=parent, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def rename_file(root: Path, source: str, destination: str) -> None:
    """Rename on the same filesystem and durably publish both directory entries."""
    with (
        parent_directory(root, source) as before,
        parent_directory(root, destination, create=True) as after,
    ):
        fault_point("upload.during_rename")
        try:
            os.rename(
                source.rsplit("/", 1)[-1],
                destination.rsplit("/", 1)[-1],
                src_dir_fd=before,
                dst_dir_fd=after,
            )
        except OSError as error:
            raise ConfigurationError(
                f"upload move {root / source} to {root / destination}: errno={error.errno}; "
                "expected writable directories on the same filesystem; restore disk space, "
                "permissions and the project folder layout, then retry"
            ) from error
        fault_point("upload.after_processed_rename")
        os.fsync(after)
        os.fsync(before)
    sync_parents(root, destination)


def sync_parents(root: Path, relative: str) -> None:
    """Persist new directory ancestors before discarding the only older copy."""
    parts = Path(relative).parts
    for length in range(len(parts)):
        prefix = "/".join(parts[:length])
        with parent_directory(root, f"{prefix}/.entry".lstrip("/")) as parent:
            os.fsync(parent)


def unlink_file(root: Path, relative: str) -> None:
    """Remove a checked leaf idempotently and persist its directory entry."""
    try:
        with parent_directory(root, relative) as parent:
            os.unlink(relative.rsplit("/", 1)[-1], dir_fd=parent)
            os.fsync(parent)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ConfigurationError(
            f"upload file {root / relative}: errno={error.errno}; expected writable managed "
            "storage; restore disk space and permissions, then retry cleanup"
        ) from error


def processed_file(config: ConnectorConfig, upload: StoredUpload) -> str:
    """Finish an ending's committed move before returning its processed location."""
    source, destination = upload.relative(processed=False), upload.relative(processed=True)
    if exists(config.host_dir, destination):
        verify_file(config, upload, destination)
        if exists(config.host_dir, source):
            verify_file(config, upload, source)
            unlink_file(config.host_dir, source)
        return destination
    if exists(config.host_dir, source):
        verify_file(config, upload, source)
        rename_file(config.host_dir, source, destination)
        return destination
    raise ConfigurationError(
        f"upload {upload.upload_id}: file missing; checked {config.host_dir / source} and "
        f"{config.host_dir / destination}; expected the original recorded file; "
        "upload the file again"
    )


def local_file(config: ConnectorConfig, upload: StoredUpload) -> str:
    """Recover the recorded state; archived inputs restore through the same read path."""
    if upload.archive_location is not None:
        from etl_craft.engine.upload_archive import restore_upload
        from etl_craft.engine.upload_recovery import finish_archive

        finish_archive(config, upload)
        return restore_upload(config, upload)
    relative = (
        processed_file(config, upload)
        if upload.ended_at is not None
        else upload.relative(processed=False)
    )
    if not exists(config.host_dir, relative):
        raise ConfigurationError(
            f"upload {upload.upload_id}: missing {config.host_dir / relative}; expected its "
            "committed file; upload the file again"
        )
    verify_file(config, upload, relative)
    return relative
