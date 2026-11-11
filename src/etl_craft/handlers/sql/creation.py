"""Create target definitions and publish complete replacements."""

from __future__ import annotations

import logging

from etl_craft.core.enums import SqlAction
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.faults import fault_point
from etl_craft.dialects.warehouse.uploads import writer_expression
from etl_craft.engine.repository.tasks import TargetTask
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.replacement import cleanup, promote
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.tables import (
    AUDIT_COLUMNS,
    add_row_id,
    audit_columns,
    check_column_names,
    create_declared_target,
    create_target_shape,
    create_with_identity,
    refuse_empty,
)

logger = logging.getLogger(__name__)


def create_table(session: Session, action: ActionContext) -> HandlerResult:
    """Replace the target with the SELECT's rows, stamped with the run id."""
    fresh = _create_new_table(session, action)
    if fresh is not None:
        return fresh
    stage = action.build_stage(session)
    identity = session.dialect.identity_in_create
    source = (
        None
        if identity and session.dialect.dml_rowcounts and action.task.allow_empty
        else session.count(f"SELECT COUNT(*) FROM {stage}", step="source rows")
    )
    if source is not None and not action.task.allow_empty:
        refuse_empty(session, source, action.context.task_code)
    writer = writer_expression(action.uploads, "s.UPLOAD_ID")
    actors = f", {writer} AS CREATED_BY, {writer} AS UPDATED_BY" if action.uploads else ""
    select_sql = (
        f"SELECT s.*, CAST({int(action.context.pipeline_run_id)} AS BIGINT) AS PIPELINE_RUN_ID"
        f", CAST({int(action.context.pipeline_id)} AS BIGINT) AS PIPELINE_ID"
        f", CAST({int(action.context.task_run_id)} AS BIGINT) AS TASK_RUN_ID"
        f"{actors} FROM {stage} s"
    )
    columns = (session.column_types(stage) if identity else {}) | dict.fromkeys(
        ("PIPELINE_RUN_ID", "PIPELINE_ID", "TASK_RUN_ID"), "BIGINT"
    )
    if action.uploads:
        columns |= dict.fromkeys(("CREATED_BY", "UPDATED_BY"), "VARCHAR(255)")
    inserted = replace_select(session, select_sql, columns if identity else None)
    source = inserted if source is None else source
    session.clear_hash_version = True
    cleanup(session, stage)
    assert source is not None
    return HandlerResult(source_count=source, target_count=source, insert_count=source)


def replace_select(session: Session, select_sql: str, columns: dict[str, str] | None) -> int | None:
    """Publish a fully shaped SELECT using CREATE_TABLE's rollback or recovery strategy.

    ``columns`` declares every selected column except ROW_ID, or None for inferred SELECT types.
    """
    existing = bool(session.target_columns())
    identity = session.dialect.identity_in_create
    strategy = session.dialect.replace_strategy
    computed = session.dialect.surrogate_key == "computed"
    if identity:
        assert columns is not None
        return _replace_identity(session, columns, select_sql, existing)
    if computed:
        select_sql = (
            "SELECT s.*, CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) AS ROW_ID "
            f"FROM ({select_sql}) s"
        )
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
        if not computed:
            raise SqlGuardError(
                f"{session.target}: safe replacement requires a declared ROW_ID strategy"
            )
        if existing:
            session.dialect.preserve_replacement_properties(session.conn, session.target, candidate)
        promote(session, candidate, existing=existing)
    else:
        comment = (
            session.dialect.replacement_comment(session.conn, session.target) if existing else None
        )
        fault_point("sql.replace.before_publish")
        session.run(f"DROP TABLE IF EXISTS {session.target}", step="drop the old target")
        fault_point("sql.replace.after_clear")
        if columns is not None and not computed:
            create_with_identity(session, columns, session.target)
            session.run(
                f"INSERT INTO {session.target} ({', '.join(columns)}) {select_sql}",
                step="insert the declared replacement rows",
            )
        else:
            session.create_table_as(
                session.target, select_sql, step="create the target from the SELECT"
            )
            if not computed:
                add_row_id(session)
        if comment is not None:
            escaped = comment.replace("'", "''")
            session.run(
                f"COMMENT ON TABLE {session.target} IS '{escaped}'",
                step="preserve the table comment",
            )
        fault_point("sql.replace.after_publish")
    return None


def _replace_identity(
    session: Session, types: dict[str, str], select_sql: str, existing: bool
) -> int | None:
    """Populate a candidate with the target's identity and publish it atomically.

    Returns the rows inserted where the driver reports DML counts. A new target in managed
    storage is published by renaming the candidate; an existing one, or one at an external
    location, by the dialect's replacement DDL.
    """
    candidate = session.scratch("replace", persistent=True)
    names = list(types)
    columns = ", ".join(f"{name} {kind}" for name, kind in types.items())
    renamed = not existing and not any(
        session.params.get(key) for key in ("EXTERNAL_LOCATION", "BASE_LOCATION")
    )
    if renamed:
        create_ddl = session.dialect.identity_table_ddl(candidate, columns, session.params)
        publish_ddl = ""
    else:
        create_ddl, publish_ddl = session.dialect.identity_replacement_ddl(
            session.conn,
            session.target,
            candidate,
            columns,
            session.params,
            existing=existing,
        )
    session.run(create_ddl, step="create the identity replacement")
    result = session.run(
        f"INSERT INTO {candidate} ({', '.join(names)}) {select_sql}",
        step="populate the identity replacement",
    )
    inserted = session.dialect.affected_rows(result) if session.dialect.dml_rowcounts else None
    if renamed:
        promote(session, candidate, existing=False)
        return inserted
    fault_point("sql.replace.before_publish")
    session.run(publish_ddl, step="atomically replace the target")
    cleanup(session, candidate)
    return inserted


def _create_new_table(session: Session, action: ActionContext) -> HandlerResult | None:
    """Create a new transactional table without a replacement stage or key alterations."""
    if (
        session.target_columns()
        or action.staged is not None
        or action.task.watermark is not None
        or action.uploads
    ):
        return None
    if not action.task.allow_empty:
        return None
    if any(session.params.get(key) for key in ("EXTERNAL_LOCATION", "BASE_LOCATION")):
        return None
    business = session.describe_select(action.select_sql)
    if business is None:
        return None
    names = [name for name, _ in business]
    check_column_names(session, names)
    transactional = session.dialect.replace_strategy == "transactional"
    target = session.target if transactional else session.scratch("replace", persistent=True)
    if transactional:
        fault_point("sql.replace.before_publish")
    create_declared_target(session, business, AUDIT_COLUMNS[SqlAction.CREATE_TABLE], target)
    if transactional:
        fault_point("sql.replace.after_clear")
    result = session.run(
        session.dialect.new_table_insert(target, names, action.select_sql),
        action.stamp,
        step="insert the SELECT's rows",
    )
    source = session.dialect.affected_rows(result)
    if transactional:
        fault_point("sql.replace.after_publish")
    else:
        promote(session, target, existing=False)
    session.clear_hash_version = True
    return HandlerResult(source_count=source, target_count=source, insert_count=source)


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
