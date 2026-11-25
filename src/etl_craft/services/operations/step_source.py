"""Read only source chosen by the selected task's deployed metadata."""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.engine import Connection

from etl_craft.config.resolve import profile_secret
from etl_craft.core.definitions import Definition, using
from etl_craft.core.enums import Handler
from etl_craft.core.errors import EtlCraftError, ResourceNotFoundError, RunStateError
from etl_craft.core.redaction import mask_log, registering
from etl_craft.core.task_secrets import declared
from etl_craft.core.text import mask_arguments
from etl_craft.engine.bundles import Bundle
from etl_craft.engine.project_files import safe_path
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.tasks import fetch_task_execution_detail, fetch_task_parameters
from etl_craft.handlers.task_secrets import resolve_names
from etl_craft.services.operations.bundles import project_config_from_content
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import StepSource

SOURCE_LIMIT = 256 * 1024


@dataclass(frozen=True)
class _SourceIdentity:
    version: str
    bundle_id: str | None
    label: str


def read_source(
    conn: Connection, ctx: OperationContext, run_id: int, task: str, task_id: int
) -> StepSource:
    """Use deployed parameters before applying any run-specific input overrides."""
    row = conn.execute(statement(conn, "run_definition"), {"run_id": run_id}).one()
    definition = Definition.read(row.snapshot, run_id, row.bundle_id)
    with using(definition):
        handler = fetch_task_execution_detail(conn, task_id).handler
        params = fetch_task_parameters(conn, task_id)
    version = row.version or row.bundle_id or "unversioned"
    label = f"run {run_id}, task {task!r}, version {version}"
    name = (params.get("SCRIPT_FILE") or "").strip()
    if handler not in {Handler.PYTHON, Handler.SQL, Handler.SQL_SCRIPT}:
        return StepSource(version, None, None, None)
    if not name:
        inline = params.get("SELECT_QUERY") if handler == Handler.SQL else None
        if inline is not None and row.bundle_id is not None:
            bundle = Bundle.load(conn, row.bundle_id)
            with registering(*_source_secrets(ctx, bundle, (), label)):
                return _display(version, None, inline, label)
        return _display(version, None, inline, label)
    return _file_source(conn, ctx, handler, params, _SourceIdentity(version, row.bundle_id, label))


def _file_source(
    conn: Connection,
    ctx: OperationContext,
    handler: str,
    params: Mapping[str, str],
    source: _SourceIdentity,
) -> StepSource:
    label, version = source.label, source.version
    name = params["SCRIPT_FILE"].strip()
    folder, suffix = (
        ("python_scripts", ".py") if handler == Handler.PYTHON else ("sql_scripts", ".sql")
    )
    try:
        path = safe_path(name)
    except EtlCraftError:
        raise RunStateError(
            f"{label}: SCRIPT_FILE={mask_log(name)!r}; expected a relative file in {folder}/; "
            "inspect the admitted definition"
        ) from None
    if path.parts[0] != folder or path.suffix != suffix:
        raise RunStateError(
            f"{label}: SCRIPT_FILE={name!r}; expected a {suffix} file in {folder}/; "
            "inspect the admitted definition"
        )
    try:
        if source.bundle_id is None:
            raise ResourceNotFoundError("missing pinned bundle")
        bundle = Bundle.load(conn, source.bundle_id)
        data = bundle.read(ctx.config, name)
    except (OSError, EtlCraftError):
        raise ResourceNotFoundError(
            f"{label}: expected deployed file {name!r} in pinned bundle {source.bundle_id!r}; "
            "restore that bundle and file from backup"
        ) from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RunStateError(
            f"{label}, file {name!r}: expected UTF-8 source; republish UTF-8 text"
        ) from None
    names = declared(params, label) if handler == Handler.PYTHON else ()
    if names or handler in {Handler.SQL, Handler.SQL_SCRIPT}:
        with registering(*_source_secrets(ctx, bundle, names, label)):
            return _display(version, name, text, label)
    return _display(version, name, text, label)


def _source_secrets(
    ctx: OperationContext,
    bundle: Bundle,
    names: tuple[str, ...],
    label: str,
) -> tuple[str, ...]:
    config = project_config_from_content(
        ctx, {"craft-connector.yml": bundle.read(ctx.config, "craft-connector.yml")}
    )
    warehouse = config.warehouse
    password = profile_secret(config, warehouse) if warehouse is not None else ""
    return (password, *resolve_names(config, names, label).values())


def _display(version: str, file: str | None, text: str | None, label: str) -> StepSource:
    if text is None:
        return StepSource(version, file, None, None)
    if any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
        raise RunStateError(
            f"{label}, source {file or 'SELECT_QUERY'!r}: found binary content; "
            "republish UTF-8 text"
        )
    masked = re.sub(
        r"\S+",
        lambda token: (
            str(mask_arguments({"message": token[0]})["message"]) if "://" in token[0] else token[0]
        ),
        mask_log(text),
    ).encode()
    if len(masked) <= SOURCE_LIMIT:
        return StepSource(version, mask_log(file) if file else None, masked.decode(), None)
    preview = masked[:SOURCE_LIMIT].decode(errors="ignore")
    return StepSource(version, mask_log(file) if file else None, preview, len(preview.encode()))
