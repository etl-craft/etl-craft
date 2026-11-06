"""Stewardable graph and managed-write checks shared by validate and refresh."""

from collections.abc import Sequence

from sqlalchemy.engine import Connection

from etl_craft.core.enums import DependencyType, Handler, SqlAction, YesNo
from etl_craft.dialects.engine import for_engine
from etl_craft.dialects.query_analysis import output_columns
from etl_craft.engine.protection_events import target_identity
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.source_columns import fetch_source_columns
from etl_craft.engine.repository.validation import ActiveTask, DependencyEdge
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.sql import task_dialect
from etl_craft.handlers.sql.protection_columns import type_problems
from etl_craft.handlers.sql.spec import MERGES, WRITERS, SqlTask


def _stewardship_schema(conn: Connection) -> bool:
    """Whether the Engine DB has stewardship; before its migration no pipeline is stewardable."""
    return for_engine(conn).has_table(conn, "AUD_UPLOADS")


def graph_problems(
    conn: Connection, pipeline_id: int, tasks: Sequence[ActiveTask], edges: Sequence[DependencyEdge]
) -> list[tuple[str, str]]:
    """Require HAS_DATA after validation, and one validation task where uploads arrive."""
    if not _stewardship_schema(conn):
        return []
    validators = {
        task.task_code
        for task in tasks
        if task.pipeline_id == pipeline_id and task.handler == Handler.FILE_VALIDATION
    }
    problems = [
        (
            f"{edge.pipeline_code}.{edge.task_code}",
            f"depends on FILE_VALIDATION task {edge.depends_on_task_code} with "
            f"{edge.dependency_type}; expected HAS_DATA, so a run with no accepted files skips "
            "it; change the dependency to HAS_DATA",
        )
        for edge in edges
        if edge.depends_on_pipeline_id == pipeline_id
        and edge.depends_on_handler == Handler.FILE_VALIDATION
        and edge.dependency_type == DependencyType.SUCCESS
    ]
    row = conn.execute(statement(conn, "stewardship_pipeline"), {"pipeline_id": pipeline_id}).one()
    if row.stewardable_flag == YesNo.YES and len(validators) != 1:
        problems.append(
            (
                row.pipeline_code,
                f"FILE_VALIDATION tasks={len(validators)} on a pipeline that takes uploads; "
                "expected exactly one to accept uploaded files; add one validation task",
            )
        )
    return problems


def _source_event_problems(conn: Connection, context: TaskContext, wait_code: str) -> list[str]:
    """Require SOURCE_EVENT to name this pipeline's file wait, which validation depends on."""
    where = f"{context.pipeline_code}.{context.task_code}"
    row = conn.execute(
        statement(conn, "validation_source_event"),
        {"pipeline_id": context.pipeline_id, "task_id": context.task_id, "wait_code": wait_code},
    ).one_or_none()
    if row is None or row.handler != Handler.EVENT_WAIT or not row.event_file:
        return [
            f"{where}: SOURCE_EVENT={wait_code!r}; expected an active EVENT_WAIT task of this "
            "pipeline that sets EVENT_FILE; name that file wait, or remove SOURCE_EVENT"
        ]
    if not row.waits_on:
        return [
            f"{where}: SOURCE_EVENT={wait_code!r} without a SUCCESS dependency on it; expected "
            f"{where} to depend on {wait_code} with SUCCESS so its files exist when "
            "validated; add that dependency"
        ]
    return []


def validation_problems(conn: Connection, context: TaskContext) -> list[str]:
    """Refuse a validator whose files cannot arrive, and an upload-only one nobody can feed."""
    from etl_craft.handlers.file_validation import require_uploads, source_event

    if (wait_code := source_event(context)) is not None:
        return _source_event_problems(conn, context, wait_code)
    if not require_uploads(context):
        return []
    row = conn.execute(
        statement(conn, "stewardship_pipeline"), {"pipeline_id": context.pipeline_id}
    ).one()
    if row.stewardable_flag != YesNo.YES:
        return [
            f"{context.pipeline_code}.{context.task_code}: REQUIRE_UPLOADS=Y with "
            f"STEWARDABLE_FLAG={row.stewardable_flag}; expected STEWARDABLE_FLAG=Y; "
            "remedy: enable uploads for this pipeline or set REQUIRE_UPLOADS=N"
        ]
    return []


def sql_problems(conn: Connection, context: TaskContext, spec: SqlTask) -> list[str]:
    """Refuse unsupported protection and writes that lose their file identity."""
    if not _stewardship_schema(conn):
        return []
    pipeline = conn.execute(
        statement(conn, "stewardship_pipeline"), {"pipeline_id": context.pipeline_id}
    ).one()
    definitions = fetch_source_columns(conn) if spec.action in MERGES else []
    from etl_craft.services.upload_columns import problems as control_problems

    problems = control_problems(context, spec, definitions) if spec.action in MERGES else []
    if pipeline.stewardable_flag != YesNo.YES:
        return problems
    dialect = task_dialect(context)
    where = f"{context.pipeline_code}.{context.task_code}, target {spec.target_object}"
    if spec.action in MERGES:
        target = target_identity(context.config, spec.target_object)[0]
        types = {
            column.column_name.lower(): column.data_type
            for column in definitions
            if target_identity(context.config, column.table_name)[0] == target
        }
        problems.extend(type_problems(dialect, spec.target_object, types))
    if spec.action in WRITERS | {SqlAction.DELETE_ROWS}:
        names = output_columns(spec.select_sql or "", dialect=dialect.sqlglot_dialect)
        if names is None or "upload_id" not in {name.lower() for name in names}:
            problems.append(
                f"{where}: SELECT output has no explicit UPLOAD_ID; expected the "
                "accepted file's id on every written row; SELECT UPLOAD_ID explicitly"
            )
    if spec.action in MERGES and (spec.dedupe_order or "").strip().upper() not in {
        "UPLOAD_ID",
        "UPLOAD_ID ASC",
    }:
        problems.append(
            f"{where}: MERGE_DEDUPE_ORDER={spec.dedupe_order!r}; expected UPLOAD_ID "
            "ASC, newest upload last; set MERGE_DEDUPE_ORDER=UPLOAD_ID ASC"
        )
    return problems
