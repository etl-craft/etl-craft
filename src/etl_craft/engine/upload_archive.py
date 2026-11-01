"""Durable archive intent, streaming copy verification and idempotent restoration."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import BinaryIO
from urllib.parse import parse_qs, quote, unquote, urlsplit

from etl_craft.config import ConnectorConfig
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.faults import fault_point
from etl_craft.core.file_bytes import open_regular, parent_directory
from etl_craft.dialects.credentials import S3Objects
from etl_craft.engine.upload_storage import (
    StoredUpload,
    exists,
    sync_parents,
    verify_file,
)


def archive_location(config: ConnectorConfig, upload: StoredUpload) -> str:
    """Name an immutable content-specific destination without guessing a profile."""
    destination = config.uploads.archive_to
    if destination.store is None:
        raise ConfigurationError(
            "Uploads.Archive_to is missing; expected file:// or profiled s3://; "
            "configure that location before expiring upload files"
        )
    key = f"{upload.sha256}/{upload.pipeline_code}/{upload.stored_name}"
    location = destination.store.rstrip("/") + "/" + key
    if location.startswith("s3://"):
        if destination.profile not in config.object_stores:
            raise ConfigurationError(
                f"Uploads.Archive_to={destination.store}: profile={destination.profile!r} "
                "is missing; expected an Object_stores profile; configure that profile"
            )
        location += "?profile=" + quote(str(destination.profile), safe="")
    return location


def _s3(config: ConnectorConfig, location: str) -> S3Objects:
    address = urlsplit(location)
    profile = parse_qs(address.query).get("profile", [None])[0]
    if profile not in config.object_stores:
        raise ConfigurationError(
            f"archive {location}: Object_stores profile={profile!r} is missing; expected "
            "the recorded profile; restore that profile before retrying"
        )
    assert profile is not None
    return S3Objects(config, config.object_stores[profile])


@contextmanager
def archive_stream(config: ConnectorConfig, location: str) -> Iterator[BinaryIO]:
    """Read a recorded archive through the existing storage adapter or safe file reader."""
    address = urlsplit(location)
    if address.scheme == "file" and not address.netloc and not address.query:
        path = Path(unquote(address.path))
        if not path.is_absolute():
            raise ConfigurationError(
                f"archive {location}: expected an absolute file:// path; correct it"
            )
        with open_regular(Path(path.anchor), str(path.relative_to(path.anchor))) as stream:
            yield stream
    elif address.scheme == "s3":
        with _s3(config, location).open_stream(
            address.netloc, unquote(address.path).lstrip("/")
        ) as stream:
            yield stream
    else:
        raise ConfigurationError(
            f"archive {location}: unsupported location; expected file:// or s3://; "
            "restore the recorded archive location"
        )


def verify_archive(config: ConnectorConfig, upload: StoredUpload) -> None:
    """Require matching size and SHA-256 before a source can be removed or restored."""
    assert upload.archive_location is not None
    digest, size = hashlib.sha256(), 0
    with archive_stream(config, upload.archive_location) as stream:
        while chunk := stream.read(min(65536, upload.size_bytes - size + 1)):
            size += len(chunk)
            require_size(upload, size)
            digest.update(chunk)
    found = digest.hexdigest()
    if (found, size) != (upload.sha256, upload.size_bytes):
        raise ConfigurationError(
            f"upload {upload.upload_id}, archive {upload.archive_location}: SHA-256={found}, "
            f"size={size}; expected SHA-256={upload.sha256}, size={upload.size_bytes}; "
            "restore the original archive or upload the file again"
        )


def require_size(upload: StoredUpload, found: int) -> None:
    """Refuse oversized recorded archives before allocating unbounded disk or I/O."""
    if found > upload.size_bytes:
        raise ConfigurationError(
            f"upload {upload.upload_id}, archive {upload.archive_location}: size is at least "
            f"{found} bytes; expected exactly {upload.size_bytes} bytes and SHA-256="
            f"{upload.sha256}; restore the original archive or upload the file again"
        )


def copy_stream(source: BinaryIO, output: BinaryIO, upload: StoredUpload) -> None:
    """Copy bounded chunks, leaving the complete source intact until publication."""
    size = 0
    while chunk := source.read(min(65536, upload.size_bytes - size + 1)):
        size += len(chunk)
        require_size(upload, size)
        output.write(chunk)
        fault_point("upload.archive_during_write")
    output.flush()
    os.fsync(output.fileno())


def publish_archive(config: ConnectorConfig, upload: StoredUpload, source: str) -> None:
    """Write before removing local bytes; interrupted writes are safe to repeat."""
    assert upload.archive_location is not None
    verify_file(config, upload, source)
    address = urlsplit(upload.archive_location)
    if address.scheme == "file":
        target = Path(unquote(address.path))
        if exists(Path(target.anchor), str(target.relative_to(target.anchor))):
            verify_archive(config, upload)
            return
    with open_regular(config.host_dir, source) as stream:
        if address.scheme == "s3":
            fault_point("upload.archive_during_write")
            _s3(config, upload.archive_location).write_stream(
                address.netloc, unquote(address.path).lstrip("/"), stream
            )
        else:
            target = Path(unquote(address.path))
            with parent_directory(
                Path(target.anchor), str(target.relative_to(target.anchor)), create=True
            ) as parent:
                temporary = f".incoming-{upload.upload_id}"
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
                try:
                    with os.fdopen(fd, "wb") as output:
                        copy_stream(stream, output, upload)
                    os.replace(temporary, target.name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                finally:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary, dir_fd=parent)
    if address.scheme == "file":
        sync_parents(Path(target.anchor), str(target.relative_to(target.anchor)))
    verify_archive(config, upload)


def restore_upload(config: ConnectorConfig, upload: StoredUpload) -> str:
    """Restore a checked archive to its processed location, retaining the archive record."""
    destination = upload.relative(processed=True)
    if exists(config.host_dir, destination):
        verify_file(config, upload, destination)
        return destination
    assert upload.archive_location is not None
    try:
        with (
            archive_stream(config, upload.archive_location) as source,
            parent_directory(config.host_dir, destination, create=True) as parent,
        ):
            temporary = f".restore-{upload.upload_id}"
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent)
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(fd, "wb") as output:
                    copy_stream(source, output, upload)
                relative = str(Path(destination).parent / temporary)
                verify_file(config, upload, relative)
                os.replace(temporary, upload.stored_name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
    except (ConfigurationError, OSError) as error:
        raise ConfigurationError(
            f"upload {upload.upload_id}, archive {upload.archive_location}: restore failed: "
            f"{error}; expected the original recorded bytes; "
            "restore the archive, disk space and cache permissions or upload the file again"
        ) from error
    sync_parents(config.host_dir, destination)
    return destination
