"""Bounded output filtering for the local and agent task interpreters."""

from __future__ import annotations

import json
import os
import select
import threading
from dataclasses import replace
from typing import IO, TYPE_CHECKING

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig

if TYPE_CHECKING:
    from etl_craft.execution.processes import ChildSpec


def capture_output(
    source: IO[bytes],
    output: IO[bytes],
    values: tuple[str, ...],
    stop: threading.Event,
    failures: list[OSError],
    finished: threading.Event,
) -> None:
    """Retain enough trailing bytes to mask a credential split between pipe reads."""
    secrets = tuple(sorted({value.encode() for value in values if value}, key=len, reverse=True))
    width = max(map(len, secrets), default=1)
    pending = b""
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
            pending += chunk
            while pending:
                matches = [(pending.find(value), value) for value in secrets if value in pending]
                if matches:
                    index, value = min(matches, key=lambda match: (match[0], -len(match[1])))
                    output.write(pending[:index] + b"[REDACTED]")
                    pending = pending[index + len(value) :]
                else:
                    length = max(0, len(pending) - width + 1)
                    output.write(pending[:length])
                    pending = pending[length:]
                    break
            output.flush()
        for value in secrets:
            pending = pending.replace(value, b"[REDACTED]")
        output.write(pending)
        output.flush()
    except OSError as error:
        # This thread is a process boundary: stop the child and report capture failure.
        failures.append(error)
        stop.set()
    finally:
        source.close()


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
    from etl_craft.handlers.task_secrets import resolve

    return resolve(build_task_context(engine, config, task_run_id))


def with_values(spec: ChildSpec, values: dict[str, str]) -> ChildSpec:
    """Configure the same private pipe for local and agent task processes."""
    if not values:
        return spec
    return replace(
        spec,
        argv=(*spec.argv, "--task-secrets-stdin"),
        input_data=json.dumps(values).encode(),
        redacted_values=tuple(values.values()),
    )
