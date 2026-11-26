"""Create target definitions and publish complete replacements."""

from __future__ import annotations

import logging

from etl_craft.core.enums import SqlAction
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.faults import fault_point
from etl_craft.dialects.warehouse.row_ids import row_number
from etl_craft.dialects.warehouse.uploads import writer_expression
from etl_craft.engine.repository.tasks import TargetTask
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.replacement import cleanup, promote
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.tables import (
    AUDIT_COLUMNS,
    audit_columns,
    check_column_names,
    create_declared_target,
    create_target_shape,
    key_row_id,
    refuse_empty,
)

logger = logging.getLogger(__name__)


def create_table(session: Session, action: ActionContext) -> HandlerResult:
    """Replace the target with the SELECT's rows, stamped with the run id."""
    stage = action.build_stage(session)
    source = session.count(f"SELECT COUNT(*) FROM {stage}", step="source rows")
    if not action.task.allow_empty:
        refuse_empty(session, source, action.context.task_code)
    writer = writer_expression(action.uploads, "s.UPLOAD_ID")
    actors = f", {writer} AS CREATED_BY, {writer} AS UPDATED_BY" if action.uploads else ""
    select_sql = (
        f"SELECT s.*, CAST({int(action.context.pipeline_run_id)} AS BIGINT) AS PIPELINE_RUN_ID"
        f", CAST({int(action.context.pipeline_id)} AS BIGINT) AS PIPELINE_ID"
        f", CAST({int(action.context.task_run_id)} AS BIGINT) AS TASK_RUN_ID"
        f"{actors} FROM {stage} s"
    )
    replace_select(session, select_sql, source)
    session.clear_hash_version = True
    cleanup(session, stage)
    return HandlerResult(source_count=source, target_count=source, insert_count=source)


def replace_select(session: Session, select_sql: str, count: int) -> None:
    """Publish a fully shaped SELECT of ``count`` rows, numbered, as the dialect replaces tables."""
    target_columns = session.target_columns()
    existing = bool(target_columns)
    has_ids = any(name.lower() == "row_id" for name, _ in target_columns)
    strategy = session.dialect.replace_strategy
    base = session.row_id_base(count, existing=has_ids)
    select_sql = f"SELECT s.*, {row_number(base)} AS ROW_ID FROM ({select_sql}) s"
    if strategy == "create_or_replace":
        ddl = session.dialect.replacement_ddl(
            session.conn, session.target, select_sql, session.params, existing=existing
        )
        fault_point("sql.replace.before_publish")
        session.run(ddl, step="atomically replace the target")
    elif strategy == "copy_and_restore":
        if existing and any(session.params.get(k) for k in ("EXTERNAL_LOCATION", "BASE_LOCATION")):
            raise SqlGuardError(
                f"{session.target}: cannot safely stage replacement at its existing storage path; "
                "use OVERWRITE_TABLE to keep the table definition"
            )
        candidate = session.scratch("replace", persistent=True)
        session.create_table_as(candidate, select_sql, step="prepare the complete replacement")
        if existing:
            session.dialect.preserve_replacement_properties(session.conn, session.target, candidate)
        promote(session, candidate, existing=existing)
    else:
        _publish_by_drop(session, select_sql, existing)


def _publish_by_drop(session: Session, select_sql: str, existing: bool) -> None:
    """Publish transactional warehouse DDL with the old target comment."""
    comment = (
        session.dialect.replacement_comment(session.conn, session.target) if existing else None
    )
    fault_point("sql.replace.before_publish")
    session.run(f"DROP TABLE IF EXISTS {session.target}", step="drop the old target")
    fault_point("sql.replace.after_clear")
    session.create_table_as(session.target, select_sql, step="create the target from the SELECT")
    key_row_id(session, session.target)
    if comment is not None:
        escaped = comment.replace("'", "''")
        session.run(
            f"COMMENT ON TABLE {session.target} IS '{escaped}'",
            step="preserve the table comment",
        )
    fault_point("sql.replace.after_publish")


def setup_table(session: Session, action: ActionContext) -> HandlerResult:
    """Create the target, empty, when it does not exist; leave an existing one alone.

    Its columns are the SELECT's, then ``PIPELINE_RUN_ID``, the audit columns of the action
    that writes it and ``ROW_ID``. That action is ``SETUP_FOR`` when set, else the one the
    pipeline's other tasks on the target write with.
    """
    if session.target_columns():
        logger.info("%s exists; SETUP_TABLE leaves it as it is", session.target)
        return HandlerResult(source_count=0, target_count=0, insert_count=0)
    assert action.state is not None
    others = list(action.state.peers)
    writer = writer_action(action.task.setup_for, others, action.task.target_object)
    business = None if action.staged is not None else session.describe_select(action.select_sql)
    if business is not None:
        check_column_names(session, [name for name, _ in business])
        create_declared_target(session, business, audit_columns(session, writer))
    else:
        stage = action.build_stage(session, empty=True)
        create_target_shape(session, stage, audit_columns(session, writer))
        session.drop(stage)
    if writer in {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}:
        session.publish_hash_version = 2
    logger.info("created %s with the audit columns of %s", session.target, writer)
    return HandlerResult(source_count=0, target_count=0, insert_count=0)


def writer_action(setup_for: str | None, others: list[TargetTask], target: str) -> str:
    """Return the writer whose audit columns a SETUP_TABLE target gets.

    ``others`` are the pipeline's other tasks on the target.
    """
    writers = [task for task in others if task.sql_action in AUDIT_COLUMNS]
    found = sorted({task.sql_action for task in writers})
    listed = ", ".join(f"{task.task_code} ({task.sql_action})" for task in writers)
    merges = {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}
    if merges.issubset(set(found) | {setup_for}):
        raise SqlGuardError(
            f"{target}: SCD1_MERGE and SCD2_MERGE have different row lifecycles; "
            "give the target one merge action"
        )
    if setup_for is not None:
        clashing = [a for a in found if AUDIT_COLUMNS[a] != AUDIT_COLUMNS[setup_for]]
        if clashing:
            raise SqlGuardError(
                f"SETUP_FOR={setup_for}, but tasks in this pipeline write {target} as {listed}, "
                "which need other audit columns"
            )
        return setup_for
    audit_sets = {AUDIT_COLUMNS[a] for a in found}
    if len(audit_sets) > 1:
        raise SqlGuardError(
            f"tasks in this pipeline write {target} with actions that need different audit "
            f"columns ({listed}); a table has one set, so give it one writing action, or set "
            "SETUP_FOR to the one it is for"
        )
    if not found:
        raise SqlGuardError(
            f"no task in this pipeline writes {target}, so SETUP_TABLE cannot tell which audit "
            "columns it needs; set SETUP_FOR to the action that writes it: "
            f"{', '.join(AUDIT_COLUMNS)}"
        )
    return found[0]
