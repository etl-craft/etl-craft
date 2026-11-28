"""Bounded output filtering for the local and agent task interpreters."""

from __future__ import annotations

import json
import os
import re
import select
import threading
from dataclasses import replace
from typing import IO, TYPE_CHECKING

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.error_anchors import MARKER
from etl_craft.execution.log_positions import LogPositions

if TYPE_CHECKING:
    from etl_craft.execution.processes import ChildSpec


def capture_output(
    source: IO[bytes],
    capture: RedactedOutput,
    stop: threading.Event,
    failures: list[OSError],
    finished: threading.Event,
) -> None:
    """Retain enough trailing bytes for a credential or marker split across pipe reads."""
    try:
        while True:
            ready, _, _ = select.select([source], [], [], 0.1)
            if not ready:
                if finished.is_set():
                    break
                continue
            chunk = os.read(source.fileno(), 16384)
            if not chunk:
                break
            capture.write(chunk)
        capture.write(b"", final=True)
    except OSError as error:
        # This thread is a process boundary: stop the child and report capture failure.
        failures.append(error)
        stop.set()
    finally:
        source.close()


class RedactedOutput:
    """Separate authenticated marker tokens from bytes subject to credential masking."""

    def __init__(self, positions: LogPositions, values: tuple[str, ...], nonce: str | None) -> None:
        """Keep at most one incomplete token or secret between writes."""
        self.positions = positions
        self.secrets = tuple(
            sorted({value.encode() for value in values if value}, key=len, reverse=True)
        )
        self.nonce = b"" if nonce is None else nonce.encode()
        self.marker = (
            re.compile(re.escape(self.nonce) + b"(" + MARKER.pattern + b")") if self.nonce else None
        )
        self.secret_width = max(map(len, self.secrets), default=1)
        self.pending = b""

    def write(self, data: bytes, *, final: bool = False) -> None:
        """Write complete segments and replace validated transport markers with public tokens."""
        self.pending += data
        while self.pending:
            safe = len(self.pending) if final else len(self.pending) - self.secret_width + 1
            if safe <= 0:
                break
            marker = None if self.marker is None else self.marker.search(self.pending)
            if marker is not None and marker.start() < safe:
                self._redact(marker.start(), boundary=True)
                sequence = int(marker[2])
                if sequence < 2**63:
                    self.positions.marker(sequence, marker[1])
                else:
                    self.positions.write(marker[1])
                self.pending = self.pending[len(marker[0]) :]
            else:
                safe = safe if final else min(safe, self._marker_boundary())
                if safe == 0:
                    break
                self._redact(safe, boundary=final)
        self.positions.output.flush()

    def _marker_boundary(self) -> int:
        if not self.nonce:
            return len(self.pending)
        lookback = self.pending[-(len(self.nonce) + 26) :]
        known = lookback.find(self.nonce)
        if known >= 0:
            return len(self.pending) - len(lookback) + known
        for size in range(min(len(self.nonce) - 1, len(lookback)), 0, -1):
            if lookback.endswith(self.nonce[:size]):
                return len(self.pending) - size
        return len(self.pending)

    def _redact(self, safe: int, *, boundary: bool) -> None:
        while safe > 0:
            matches = [
                (self.pending.find(value, 0, safe) if boundary else self.pending.find(value), value)
                for value in self.secrets
            ]
            match = min(
                ((index, value) for index, value in matches if 0 <= index < safe),
                key=lambda item: (item[0], -len(item[1])),
                default=None,
            )
            if match is None:
                self.positions.write(self.pending[:safe])
                self.pending = self.pending[safe:]
                return
            index, value = match
            self.positions.write(self.pending[:index] + b"[REDACTED]")
            consumed = index + len(value)
            self.pending = self.pending[consumed:]
            safe -= consumed


def read_values(stream: IO[str]) -> dict[str, str]:
    """Bound and validate the private pipe without quoting its secret-bearing bytes."""
    from etl_craft.core.errors import PermanentError

    try:
        data = stream.read(1024 * 1024 + 1)
        values = json.loads(data) if len(data) <= 1024 * 1024 else None
        if isinstance(values, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in values.items()
        ):
            return values
    except (ValueError, OSError):
        pass
    raise PermanentError(
        "task credential pipe: expected a string mapping within 1 MiB; "
        "restore the parent process and reduce the declared provider values"
    )


def task_values(engine: Engine, config: ConnectorConfig, task_run_id: int) -> dict[str, str]:
    """Resolve local task names on the parent host before its environment is reduced."""
    from etl_craft.execution.context import build_task_context
    from etl_craft.handlers.task_secrets import resolve, resolve_names

    task = build_task_context(engine, config, task_run_id)
    from etl_craft.core.enums import Handler
    from etl_craft.engine.queries import statement

    if task.handler == Handler.ALERT:
        with engine.connect() as conn:
            channel = conn.execute(
                statement(conn, "alert_local_secrets"), {"task_run_id": task_run_id}
            ).one_or_none()
        if channel is None:
            return {}
        names = tuple(
            dict.fromkeys(n for n in (channel.url_secret, channel.signing_secret) if n is not None)
        )
        return resolve_names(config, names, f"channel {task.task_params['ALERT_CHANNEL']}")
    return resolve(task)


def with_values(spec: ChildSpec, values: dict[str, str]) -> ChildSpec:
    """Configure the same private pipe for local and agent task processes."""
    if not values:
        return replace(spec, track_error_positions=True)
    return replace(
        spec,
        argv=(*spec.argv, "--task-secrets-stdin"),
        input_data=json.dumps(values).encode(),
        redacted_values=tuple(values.values()),
        track_error_positions=True,
    )


def send_input(
    target: IO[bytes],
    data: bytes,
    stop: threading.Event,
    failures: list[OSError],
    finished: threading.Event,
) -> None:
    """Bound pipe feeding so a child that never reads can still be killed on time."""
    offset = 0
    try:
        os.set_blocking(target.fileno(), False)
        while offset < len(data) and not finished.is_set():
            _, ready, _ = select.select([], [target], [], 0.1)
            if ready:
                try:
                    offset += os.write(target.fileno(), data[offset : offset + 16384])
                except BlockingIOError:
                    continue
    except BrokenPipeError:
        pass
    except OSError as error:
        # This thread is a process boundary: cancel the child and report the pipe failure.
        failures.append(error)
        stop.set()
    finally:
        target.close()
