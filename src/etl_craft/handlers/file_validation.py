"""Validate each admitted upload independently before any downstream load can start."""

import codecs
import logging
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

from sqlalchemy.engine import Engine

from etl_craft.config.project import project_file
from etl_craft.core.enums import YesNo
from etl_craft.core.enums_uploads import UploadFormat
from etl_craft.core.errors import HandlerError, PermanentError
from etl_craft.core.upload_reader import UploadReader, check_file
from etl_craft.core.uploads import SourceFile
from etl_craft.engine.event_files import SOURCE_EVENT, digest_of
from etl_craft.engine.task_store import TaskStore
from etl_craft.handlers.python_scripts import (
    load_script,
    parse_input_params,
    script_definition_problem,
)
from etl_craft.handlers.registry import HandlerResult, TaskContext, task_store
from etl_craft.handlers.sql.spec import parse_flag
from etl_craft.scripting import ValidationTask

PARAMETERS = frozenset(
    {
        "SCRIPT_FILE",
        "FILE_FORMAT",
        "SHEET_NAME",
        "ENCODING",
        "MAX_FILE_MB",
        "INPUT_PARAMS",
        "REQUIRE_UPLOADS",
        SOURCE_EVENT,
    }
)
logger = logging.getLogger(__name__)


def require_uploads(context: TaskContext) -> bool:
    """Normalize the explicit Y/N setting before using the shared boolean parser."""
    name = "REQUIRE_UPLOADS"
    written = context.task_params.get(name, YesNo.NO).strip().upper()
    values: dict[str, str] = {YesNo.YES: "true", YesNo.NO: "false"}
    if written not in values:
        raise HandlerError(
            f"{context.pipeline_code}.{context.task_code}: {name}={written!r}; "
            "expected Y or N; remedy: set REQUIRE_UPLOADS=Y or omit it for N"
        )
    return parse_flag({name: values[written]}, name)


def source_event(context: TaskContext) -> str | None:
    """Name the wait whose admitted files this task validates; None means uploaded files."""
    written = context.task_params.get(SOURCE_EVENT)
    if written is None:
        return None
    name = written.strip()
    if not name:
        raise HandlerError(
            f"{context.pipeline_code}.{context.task_code}: {SOURCE_EVENT}={written!r}; expected "
            "the code of an EVENT_WAIT task in this pipeline; set it, or remove the parameter"
        )
    return name


def settings(context: TaskContext) -> tuple[str, UploadFormat, int]:
    """Check formats and the pipeline ceiling against the project's blanket limit."""
    where = f"{context.pipeline_code}.{context.task_code}"
    params = context.task_params
    require_uploads(context)
    file_format = params.get("FILE_FORMAT", "").strip().upper()
    if file_format not in set(UploadFormat):
        raise HandlerError(
            f"{where}: FILE_FORMAT={file_format!r}; expected CSV, TXT or XLSX; "
            "correct the validation task and upload a corrected file"
        )
    maximum = params.get("MAX_FILE_MB") or str(context.config.uploads.max_file_mb)
    try:
        value = Decimal(maximum)
        valid = value.is_finite() and 0 < value <= context.config.uploads.max_file_mb
    except InvalidOperation:
        valid = False
    if not valid:
        raise HandlerError(
            f"{where}: MAX_FILE_MB={maximum!r}; expected a positive value at most "
            f"{context.config.uploads.max_file_mb}; correct MAX_FILE_MB and upload a corrected file"
        )
    name = params.get("SCRIPT_FILE", "")
    path = project_file(
        context.config.project_dir / "validation_scripts", name, setting="SCRIPT_FILE", suffix=".py"
    )
    if problem := script_definition_problem(path, name, "validate"):
        raise HandlerError(
            f"{where}: {problem}; fix validate(task) before uploading a corrected file"
        )
    parse_input_params(params.get("INPUT_PARAMS"))
    try:
        codecs.lookup(params.get("ENCODING") or "utf-8")
    except LookupError as error:
        raise HandlerError(
            f"{where}: ENCODING={params.get('ENCODING')!r}; expected a supported text "
            "encoding; set ENCODING=utf-8 or the file's actual encoding"
        ) from error
    return name, UploadFormat(file_format), int(value * 1024 * 1024)


def run(context: TaskContext, backend: Engine | TaskStore) -> HandlerResult:
    """Record each refusal and let only the files accepted by the script proceed."""
    name, file_format, maximum = settings(context)
    if (wait_code := source_event(context)) is not None:
        return _run_event_files(context, backend, wait_code, name, file_format, maximum)
    path = project_file(
        context.config.project_dir / "validation_scripts", name, setting="SCRIPT_FILE", suffix=".py"
    )
    entry = None
    store = task_store(context, backend)
    uploads = store.upload_files()
    if not uploads and require_uploads(context):
        raise PermanentError(
            f"{context.pipeline_code}.{context.task_code}: no uploaded files in this run; "
            "expected at least one upload because REQUIRE_UPLOADS=Y; "
            "start the run from an upload in the UI or with `etl-craft upload "
            f"--pipeline-code {context.pipeline_code} <file>`"
        )
    accepted = 0
    for upload in uploads:
        try:
            check_file(upload, file_format, maximum, context.task_params.get("ENCODING") or "utf-8")
            if entry is None:
                entry = load_script(path, name, "validate")
            reader = UploadReader(
                upload,
                file_format,
                context.task_params.get("ENCODING") or "utf-8",
                context.task_params.get("SHEET_NAME") or "",
            )
            task = ValidationTask(
                upload,
                reader,
                MappingProxyType(dict(context.task_params)),
                parse_input_params(context.task_params.get("INPUT_PARAMS")),
                logger,
            )
            result = _validate(entry, task)
        except HandlerError as error:
            # Each file is a validation boundary: record its failure and retain the other files.
            reason = f"upload {upload.upload_id} {upload.file_name!r}: {error}"
            store.validation_result(upload.upload_id, reason)
            logger.exception("%s", reason)
        else:
            if result is not None:
                problem = (
                    f"{context.pipeline_code}.{context.task_code}: {name} returned "
                    f"{type(result).__name__}; expected None; fix validate(task) and upload "
                    "a corrected file"
                )
                store.validation_result(upload.upload_id, problem)
                raise HandlerError(problem)
            store.validation_result(upload.upload_id, None)
            accepted += 1
    if uploads and not accepted:
        raise HandlerError(
            f"{context.pipeline_code}.{context.task_code}: accepted 0 of {len(uploads)} uploads; "
            "expected at least one file accepted by FILE_VALIDATION; no data was loaded; "
            "upload a corrected file"
        )
    if not uploads:
        logger.info("no uploaded files in this run; 0 files validated")
    # The accepted files are what this task hands on: HAS_DATA dependents skip when there are none.
    return HandlerResult(
        source_count=len(uploads), target_count=accepted, reject_count=len(uploads) - accepted
    )


def _validate(entry: Callable[..., object], task: ValidationTask) -> object:
    try:
        return entry(task)
    except Exception as error:
        # Team script boundary: retain the failure's text as this file's refusal.
        raise HandlerError(str(error)) from error


def _run_event_files(
    context: TaskContext,
    backend: Engine | TaskStore,
    wait_code: str,
    name: str,
    file_format: UploadFormat,
    maximum: int,
) -> HandlerResult:
    """Validate the files the named wait admitted in this run; record each file's decision."""
    where = f"{context.pipeline_code}.{context.task_code}"
    path = project_file(
        context.config.project_dir / "validation_scripts", name, setting="SCRIPT_FILE", suffix=".py"
    )
    store = task_store(context, backend)
    admitted = store.event_file_candidates(wait_code)
    if not admitted and require_uploads(context):
        raise PermanentError(
            f"{where}: no files admitted by {wait_code} in this run; expected at least one "
            "file because REQUIRE_UPLOADS=Y; deliver the file the wait watches for"
        )
    entry = None
    accepted = 0
    for file in admitted:
        reason = None
        digest = ("", 0)
        try:
            digest = digest_of(file.path)
            if file.sha256 is not None and (file.sha256, file.size_bytes) != digest:
                raise HandlerError(
                    f"event file {file.path!r}: SHA-256={digest[0]}, size={digest[1]}; expected "
                    f"SHA-256={file.sha256}, size={file.size_bytes} as first validated; the "
                    f"file changed after {wait_code} admitted it; deliver the corrected file "
                    "under a new name"
                )
            source = SourceFile(Path(file.path), digest[1], digest[0])
            check_file(source, file_format, maximum, context.task_params.get("ENCODING") or "utf-8")
            if entry is None:
                entry = load_script(path, name, "validate")
            task = ValidationTask(
                source,
                UploadReader(
                    source,
                    file_format,
                    context.task_params.get("ENCODING") or "utf-8",
                    context.task_params.get("SHEET_NAME") or "",
                ),
                MappingProxyType(dict(context.task_params)),
                parse_input_params(context.task_params.get("INPUT_PARAMS")),
                logger,
            )
            result = _validate(entry, task)
            if result is not None:
                raise HandlerError(
                    f"{where}: {name} returned {type(result).__name__}; expected None; "
                    "fix validate(task)"
                )
        except HandlerError as error:
            # Each file is a validation boundary: record its refusal and keep the other files.
            reason = f"event file {file.path!r}: {error}"
            logger.exception("%s", reason)
        if reason is None:
            accepted += 1
        if digest != ("", 0) or reason is None:
            store.event_file_result(wait_code, file.path, digest, reason)
    if admitted and not accepted:
        raise HandlerError(
            f"{where}: accepted 0 of {len(admitted)} files from {wait_code}; expected at least "
            "one file accepted by FILE_VALIDATION; no data was loaded; deliver corrected files"
        )
    if not admitted:
        logger.info("no files admitted by %s in this run; 0 files validated", wait_code)
    return HandlerResult(
        source_count=len(admitted), target_count=accepted, reject_count=len(admitted) - accepted
    )
