"""Validation decisions on files an event wait admitted: their identity, acceptance and gating.

A pipeline opts in by naming the wait in a FILE_VALIDATION task's ``SOURCE_EVENT``. Files that
wait admits in a run then reach later tasks only once a successful validation accepted them, and
only with the bytes (SHA-256 and size) the first validation read.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Connection

from etl_craft.core.definitions import Definition
from etl_craft.core.enums import Handler, YesNo
from etl_craft.core.errors import HandlerError, PermissionDeniedError
from etl_craft.engine.queries import statement

SOURCE_EVENT = "SOURCE_EVENT"
ACCEPTED, REFUSED = "ACCEPTED", "REFUSED"


@dataclass(frozen=True)
class AdmittedFile:
    """One file the wait admitted in this run, with the digest its first validation recorded."""

    wait_task_id: int
    path: str
    sha256: str | None = None
    size_bytes: int | None = None


def gated_waits(definition: Definition, pipeline_id: int) -> dict[int, str]:
    """Map each wait task id to its code when an active validation task names it."""
    tasks = {
        int(str(t["task_id"])): t
        for t in definition.rows.get("CFG_TASKS", ())
        if t["pipeline_id"] == pipeline_id and t["active_flag"] == YesNo.YES
    }
    named = {
        str(p["parameter_value"]).strip()
        for p in definition.rows.get("CFG_TASK_PARAMETERS", ())
        if p["parameter_name"] == SOURCE_EVENT
        and int(str(p["task_id"])) in tasks
        and tasks[int(str(p["task_id"]))]["handler"] == Handler.FILE_VALIDATION
    }
    return {task_id: str(t["task_code"]) for task_id, t in tasks.items() if t["task_code"] in named}


def admitted(
    conn: Connection, run_id: int, pipeline_id: int, wait_code: str
) -> tuple[AdmittedFile, ...]:
    """List the files the named wait admitted in this exact run, with any recorded identity."""
    files = []
    for row in conn.execute(
        statement(conn, "event_file_candidates"),
        {"run_id": run_id, "pipeline_id": pipeline_id, "wait_code": wait_code},
    ):
        first = conn.execute(
            statement(conn, "event_file_first_decision"),
            {"task_id": row.wait_task_id, "file_path": row.file_path},
        ).one_or_none()
        files.append(
            AdmittedFile(
                row.wait_task_id,
                row.file_path,
                None if first is None else first.sha256,
                None if first is None else first.size_bytes,
            )
        )
    return tuple(files)


@dataclass(frozen=True)
class ValidationScope:
    """The run, pipeline, wait and validation task run a decision is recorded under."""

    run_id: int
    pipeline_id: int
    wait_code: str
    task_run_id: int


@dataclass(frozen=True)
class Decision:
    """One file's outcome: the digest it was read at, and the reason it was refused if it was."""

    path: str
    digest: tuple[str, int]
    reason: str | None = None


def record(conn: Connection, scope: ValidationScope, decision: Decision) -> None:
    """Record one decision, only for a file this run's wait admitted."""
    files = admitted(conn, scope.run_id, scope.pipeline_id, scope.wait_code)
    match = next((f for f in files if f.path == decision.path), None)
    if match is None:
        raise PermissionDeniedError(
            f"event file {decision.path!r}, run {scope.run_id}: not admitted by "
            f"{scope.wait_code} in this run; expected a file recorded by that wait under "
            "this run; decide only its files"
        )
    conn.execute(
        statement(conn, "event_file_decide"),
        {
            "task_id": match.wait_task_id,
            "file_path": decision.path,
            "validation_task_run_id": scope.task_run_id,
            "sha256": decision.digest[0],
            "size_bytes": decision.digest[1],
            "status": ACCEPTED if decision.reason is None else REFUSED,
            "reason": decision.reason,
        },
    )


def require_source_event(
    conn: Connection, definition: Definition | None, task_id: int, wait_code: str
) -> None:
    """Let only a FILE_VALIDATION task that names this wait read or decide its files."""
    from etl_craft.core.definitions import using
    from etl_craft.engine.repository.tasks import (
        fetch_task_execution_detail,
        fetch_task_parameters,
    )

    with using(definition):
        handler = fetch_task_execution_detail(conn, task_id).handler
        named = fetch_task_parameters(conn, task_id).get(SOURCE_EVENT)
    if handler != Handler.FILE_VALIDATION or named != wait_code:
        raise HandlerError(
            f"task {task_id}: handler={handler}, {SOURCE_EVENT}={named!r}; expected a "
            f"FILE_VALIDATION task with {SOURCE_EVENT}={wait_code!r}; decide only the files "
            "of the wait this task names"
        )


def digest_of(path: str) -> tuple[str, int]:
    """Hash a regular file in bounded chunks; a missing or linked path is a refusal."""
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise HandlerError(
            f"event file {path!r}: missing or not a regular file; expected the file the wait "
            "admitted; restore it, or deliver the file again under a new name"
        )
    digest, size = hashlib.sha256(), 0
    with target.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def visible_files(
    conn: Connection, definition: Definition, run_id: int, pipeline_id: int, files: tuple[str, ...]
) -> tuple[tuple[str, ...], dict[str, tuple[str, int]]]:
    """Hide gated files until accepted; return what is visible and the digests to verify."""
    waits = gated_waits(definition, pipeline_id)
    if not waits:
        return files, {}
    gated: set[str] = set()
    for code in waits.values():
        gated |= {f.path for f in admitted(conn, run_id, pipeline_id, code)}
    latest = {
        (row.wait_task_id, row.file_path): row
        for row in conn.execute(statement(conn, "event_file_decisions"), {"run_id": run_id})
    }
    accepted = {
        path: (row.sha256, row.size_bytes)
        for (_, path), row in latest.items()
        if row.status == ACCEPTED
    }
    return tuple(p for p in files if p not in gated or p in accepted), {
        p: d for p, d in accepted.items() if p in files
    }


def verify_unchanged(accepted: dict[str, tuple[str, int]]) -> None:
    """Refuse any accepted file whose bytes differ from what its validation read."""
    for path, (sha, size) in accepted.items():
        found = digest_of(path)
        if found != (sha, size):
            raise HandlerError(
                f"event file {path!r}: SHA-256={found[0]}, size={found[1]}; expected "
                f"SHA-256={sha}, size={size} as validated; the file changed after FILE_VALIDATION "
                "accepted it; deliver it again under a new name so it is validated again"
            )
