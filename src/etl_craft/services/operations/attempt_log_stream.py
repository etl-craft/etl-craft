"""The canonical reader shared by authorized raw and anchored attempt log reads."""

import json
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import replace

from etl_craft.core.errors import ConfigurationError, EtlCraftError, ResourceNotFoundError
from etl_craft.core.file_bytes import open_regular
from etl_craft.core.time import as_utc
from etl_craft.engine.logs import LogAttempt, log_key, log_location, stored_log
from etl_craft.execution.attempt_records import local_attempt_log
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import AnchorState, AttemptError


def canonical_log(
    ctx: OperationContext, row: LogAttempt, offset: int
) -> Generator[bytes, None, None]:
    """Open a published stream whose attempt has already passed the operation's scope check."""
    if row.log_path is None:
        raise ResourceNotFoundError(
            f"attempt_id={row.attempt_id}: no published log; retry log publication"
        )
    if "://" in row.log_path:
        key = log_key(
            row.engine_id, row.project_id, row.pipeline_run_id, row.task_run_id, row.attempt_id
        )
        expected_location = log_location(ctx.config, key)
        if row.log_path != expected_location:
            raise ResourceNotFoundError(
                f"attempt_id={row.attempt_id}: LOG_PATH={row.log_path!r}; expected "
                f"{expected_location!r}; restore the original Logs.Store and canonical identity"
            )
        return stored_log(ctx.config, key, offset)
    return local_log(ctx, row, offset)


def local_log(ctx: OperationContext, row: LogAttempt, offset: int) -> Generator[bytes, None, None]:
    """Hold each local path ancestor while reading, refusing symlinks and special files."""
    path = local_attempt_log(ctx.config, row)
    try:
        with open_regular(
            ctx.config.log_dir.absolute(),
            path.relative_to(ctx.config.log_dir.absolute()).as_posix(),
        ) as stream:
            stream.seek(offset)
            while data := stream.read(65536):
                yield data
    except ConfigurationError as error:
        raise ResourceNotFoundError(
            f"attempt_id={row.attempt_id}: log file is unavailable; {error}"
        ) from error


def resolve_error(
    ctx: OperationContext, row: LogAttempt, anchor: AttemptError, initial_chunk: str | None
) -> AttemptError:
    """Resolve one recorded event without another Engine DB read."""
    label = f"Attempt {row.attempt_number} log"
    if row.log_removed_at is not None:
        date = as_utc(row.log_removed_at).date().isoformat()
        return replace(anchor, state=AnchorState.EXPIRED, message=f"{label} expired on {date}")
    try:
        found = _read_event(ctx, row, anchor, initial_chunk)
    except (OSError, EtlCraftError):
        return replace(
            anchor,
            state=AnchorState.READ_FAILED,
            message=f"{label} could not be read. Retry the log read.",
        )
    if found is None:
        return replace(
            anchor,
            state=AnchorState.MISSING,
            message=f"Location not recorded for attempt {row.attempt_number}. Open the raw log.",
        )
    offset, line, text = found
    archived = row.log_path is not None and "://" in row.log_path
    return replace(
        anchor,
        state=AnchorState.ARCHIVED if archived else AnchorState.LIVE,
        offset=offset,
        line=line,
        text=text,
    )


def _read_event(
    ctx: OperationContext, row: LogAttempt, anchor: AttemptError, initial_chunk: str | None
) -> tuple[int, int, str] | None:
    offset = anchor.offset if anchor.offset is not None else 0
    with closing(_evidence_chunks(ctx, row, offset, initial_chunk)) as source:
        found = _locate(
            source, anchor.event.sequence, offset, anchor.line or 1, exact=anchor.offset is not None
        )
    if found is None and anchor.offset is not None:
        with closing(_evidence_chunks(ctx, row, 0, initial_chunk)) as source:
            return _locate(source, anchor.event.sequence, 0, 1)
    return found


def _evidence_chunks(
    ctx: OperationContext, row: LogAttempt, offset: int, initial_chunk: str | None
) -> Generator[bytes, None, None]:
    if row.log_path is not None:
        yield from canonical_log(ctx, row, offset)
    elif initial_chunk is not None:
        yield initial_chunk.encode()[offset:65536]
    else:
        raise ResourceNotFoundError(
            f"attempt_id={row.attempt_id}: log is unavailable; retry publication"
        )


SCAN_BYTES = 1024 * 1024
LINE_BYTES = 16 * 1024


def _locate(
    chunks: Iterator[bytes], sequence: int, offset: int, line: int, *, exact: bool = False
) -> tuple[int, int, str] | None:
    token = f"[event {sequence}]".encode()
    pending = b""
    total = 0
    for chunk in chunks:
        remaining = SCAN_BYTES - total
        if remaining <= 0:
            break
        data = chunk[:remaining]
        total += len(data)
        lines = (pending + data).split(b"\n")
        pending = lines.pop()
        for content in lines:
            if token in content if exact else _has_marker(content, token):
                return offset, line, content[:LINE_BYTES].decode("utf-8", errors="replace")
            if exact:
                return None
            offset += len(content) + 1
            line += 1
    if token in pending if exact else _has_marker(pending, token):
        return offset, line, pending[:LINE_BYTES].decode("utf-8", errors="replace")
    return None


def _has_marker(content: bytes, token: bytes) -> bool:
    if content.startswith(b"{"):
        try:
            record = json.loads(content)
        except (ValueError, RecursionError):
            return False
        message = record.get("message") if isinstance(record, dict) else None
        return isinstance(message, str) and message.startswith(token.decode() + " ")
    header, separator, message = content.partition(b": ")
    return bool(separator and b" ERROR " in header and message.startswith(token + b" "))
