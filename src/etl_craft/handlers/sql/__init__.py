"""``HANDLER=SQL``: wrap the task's read-only SELECT in one of nine actions on the warehouse.

The task supplies a SELECT, inline in ``SELECT_QUERY`` or as a file under the project's
``sql_scripts/`` in ``SCRIPT_FILE``, and names its ``SQL_ACTION`` and ``TARGET_OBJECT``; the
engine owns every write. The parameters are checked first (``spec``), then the action uses the
warehouse's transaction or publication strategy (``actions``), with every statement logged
(``session``).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from sqlalchemy.engine import Engine

from etl_craft.config.targets import active_catalog
from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActorKind, SqlAction
from etl_craft.core.errors import ConfigurationError, SqlGuardError
from etl_craft.core.faults import fault_point
from etl_craft.core.text import qualify as qualify
from etl_craft.dialects.warehouse import WarehouseDialect
from etl_craft.dialects.warehouse.uploads import writer_parameters
from etl_craft.engine import locks
from etl_craft.engine.repository.offsets import StoredOffset
from etl_craft.engine.task_store import TargetPublication, TaskState, TaskStore
from etl_craft.engine.timestamp_windows import WindowDefinition
from etl_craft.handlers.registry import HandlerResult, TaskContext, task_store
from etl_craft.handlers.sql.actions import ACTIONS
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.protection import (
    Protection,
    ProtectionRequest,
    for_task,
    legacy_names,
    refuse_evidence_target,
    refuse_legacy,
)
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.spec import MERGES as MERGES
from etl_craft.handlers.sql.spec import SqlTask, read_sql_task
from etl_craft.handlers.sql.watermarks import source_pipelines
from etl_craft.warehouse.connection import open_warehouse, task_warehouse_dialect, warehouse_task

logger = logging.getLogger(__name__)


def run(context: TaskContext, engine_db: Engine | TaskStore) -> HandlerResult:
    """Run the SQL task described by ``context`` and return its counts."""
    store = task_store(context, engine_db)
    task = read_sql_task(context)
    config = context.config
    dialect = _checked_dialect(context, task)
    catalog = active_catalog(config)
    logger.info(
        "%s %s from %s on %s",
        task.action,
        f"{catalog}.{task.target_object}",
        task.source,
        dialect.spec.display_name,
    )
    # Keep computed ROW_ID allocation and every target write under the same lock.
    lock = locks.target(task.target_object, catalog)
    with (
        store.hold(lock.key, lock.name, 30),
        warehouse_task(),
        open_warehouse(config, store) as warehouse,
    ):
        state = _read_state(task, context, store)
        task = _watermarked_task(task, context, store, state)
        task = _rule_filtered_task(task, context, state, dialect)
        if context.started_at is None:
            raise SqlGuardError(
                f"{context.pipeline_code}.{context.task_code}: recorded start is NULL; "
                "expected the Engine DB attempt start; start the task through etl-craft run"
            )
        with warehouse.connect() as conn:
            session = Session(
                conn,
                dialect,
                catalog=catalog,
                action=task.action,
                target_object=task.target_object,
                task_run_id=context.task_run_id,
                params=context.task_params,
            )
            session.protection_store = store
            _recover_protection(session, store)
            session.uploads, session.bindings = context.uploads, writer_parameters(context.uploads)
            action = ActionContext(
                task=task,
                context=context,
                store=store,
                user=context.writer,
                now=context.started_at,
                state=state,
                uploads=context.uploads,
            )
            outcome = _apply(session, action)
            conn.commit()
        from etl_craft.handlers.protection_recovery import committed

        committed(store, session.target, session.protection_requests)
        if task.action == SqlAction.SCD1_MERGE:
            fault_point("sql.scd1.after_commit")
        elif task.action == SqlAction.SCD2_MERGE:
            fault_point("sql.scd2.after_commit")
        if isinstance(outcome, SqlGuardError):
            raise outcome
        _publish(session, store)
    return replace(outcome, offset=session.watermark_to) if task.watermark is not None else outcome


def _read_state(task: SqlTask, context: TaskContext, store: TaskStore) -> TaskState | None:
    """Read checkpoint, rule scopes and conflicting writers before executing SQL."""
    from etl_craft.core.rule_flags import parse_scopes
    from etl_craft.handlers.sql.spec import read_select

    raw, _ = read_select(context.config, context.task_params) if task.select_sql else ("", "")
    needed = (
        bool(parse_scopes(raw))
        or task.watermark is not None
        or task.action
        in {SqlAction.SETUP_TABLE, SqlAction.DROP_TABLE, SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}
    )
    state = store.state(task.action) if needed else None
    if task.action in {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}:
        assert state is not None
        if (other := state.merge_conflict) is not None:
            raise SqlGuardError(
                f"{task.target_object}: {task.action} conflicts with an active {other} writer; "
                "give the target one merge action before running"
            )
    return state


def _rule_filtered_task(
    task: SqlTask, context: TaskContext, state: TaskState | None, dialect: WarehouseDialect
) -> SqlTask:
    """Expand recorded keys only after their successful upstream dependency committed."""
    from etl_craft.core.rule_flags import parse_scopes, placeholder
    from etl_craft.dialects.warehouse.rule_flags import key_set
    from etl_craft.handlers.sql.spec import read_select

    if task.select_sql is None:
        return task
    raw, _ = read_select(context.config, context.task_params)
    expanded = task.select_sql
    assert expanded is not None
    for scope in parse_scopes(raw):
        assert state is not None
        keys = state.rule_flags[scope.token]
        logger.info(
            "rule_flags statement scope: task=%s types=%s expanded_key_count=%d",
            scope.task,
            ",".join(scope.types),
            len(keys),
        )
        expanded = expanded.replace(placeholder(scope), key_set(dialect, keys), 1)
    return replace(task, select_sql=expanded)


def _recover_protection(session: Session, store: TaskStore) -> None:
    """Share the catalog read with ordinary mutations before inspecting pending work."""
    from etl_craft.handlers.protection_recovery import recover

    session.prime_target(legacy_names(session))
    refuse_legacy(session)
    recover(session, store)


def _publish(session: Session, store: TaskStore) -> None:
    """Publish changed contracts only after the warehouse commit."""
    if (
        session.publish_hash_version is not None
        or session.clear_hash_version
        or session.publish_view_statement is not None
    ):
        store.publish(
            TargetPublication(
                session.target,
                session.publish_hash_version,
                session.clear_hash_version,
                session.publish_view_statement,
            )
        )


def task_dialect(context: TaskContext) -> WarehouseDialect:
    """Choose the dialect: the warehouse connection and the task's table format.

    The format is the task's ``TABLE_FORMAT`` parameter, else ``Warehouse.Table_format``. Where
    the connection fixes the format (Trino, DuckDB over Iceberg), a task cannot choose another.
    """
    assert context.config.warehouse is not None
    return task_warehouse_dialect(context.config, context.task_params)


def _apply(session: Session, action: ActionContext) -> HandlerResult | SqlGuardError:
    """Apply the action and evidence, retaining quarantine-only failures until commit."""
    task = action.task
    refuse_evidence_target(session)
    try:
        if (
            task.action
            in {
                SqlAction.CREATE_TABLE,
                SqlAction.SETUP_TABLE,
                SqlAction.OVERWRITE_TABLE,
                SqlAction.SCD1_MERGE,
                SqlAction.SCD2_MERGE,
            }
            and session.target_columns()
        ):
            session.check_target_format()
        if action.uploads and task.action in {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}:
            return _uploaded_merge(session, action)
        session.protection = for_task(session, task)
        result = ACTIONS[task.action](session, action)
        if session.protection is not None:
            result = replace(
                result,
                variables={
                    **result.variables,
                    "PROTECTED_ROWS": session.protection.prevented_rows,
                    "PROTECTED_VALUES": session.protection.prevented_values,
                },
            )
        return result
    except SqlGuardError as error:
        if error is not session.failure_to_commit:
            raise
        # The target is untouched; commit what was set aside, then fail.
        return error
    finally:
        session.sweep()


def _checked_dialect(context: TaskContext, task: SqlTask) -> WarehouseDialect:
    """Return the task's warehouse dialect once its storage and upload protection are usable."""
    if context.config.warehouse is None:
        raise ConfigurationError("a SQL task needs a Warehouse section in craft-connector.yml")
    dialect = task_dialect(context)
    problem = dialect.unsupported_storage_problem(
        context.task_params
    ) or dialect.task_storage_problem(context.task_params)
    if problem is not None:
        raise SqlGuardError(problem)
    return dialect


def _uploaded_merge(session: Session, action: ActionContext) -> HandlerResult:
    """Commit each uploader's atomic target mutation before finalizing its hash-only intent."""
    context = action.context
    inputs = context.upload_inputs
    if tuple(u.upload_id for u in inputs) != tuple(u.upload_id for u in action.uploads):
        raise SqlGuardError(
            f"{context.pipeline_code}.{context.task_code}: upload account metadata differs; "
            "expected the run's recorded upload ids and accounts; reload the admitted task"
        )
    guard = Protection(session, action.task)
    guard.acquire()
    full = action.build_stage(session)
    if existing := for_task(session, action.task):
        guard = existing
    else:
        from etl_craft.core.actor import SYSTEM_ACTOR

        guard.enable(ProtectionRequest.create(SYSTEM_ACTOR, "enable upload protection"))
    session.protection = guard
    results = []
    protected_rows = protected_values = 0
    columns = ", ".join(name for name, _ in session.columns(full))
    for i, upload in enumerate(inputs):
        staged = session.scratch("upload")
        staged = session.create_scratch(
            staged,
            f"SELECT {columns} FROM {full} WHERE UPLOAD_ID=:upload_id_{i}",
            step=f"stage upload {upload.upload_id}",
        )
        if i:
            guard = Protection(session, action.task)
            guard.check()
            session.protection = guard
        guard.request = ProtectionRequest(
            Actor(upload.account, upload.actor_kind),
            f"upload {upload.upload_id}",
            "",
            action.now,
            upload.upload_id,
        )
        results.append(
            ACTIONS[action.task.action](
                session,
                replace(
                    action,
                    staged=staged,
                    user=upload.account,
                    respect_protection=upload.actor_kind != ActorKind.USER,
                ),
            )
        )
        protected_rows += guard.prevented_rows
        protected_values += guard.prevented_values
        session.conn.commit()

        from etl_craft.handlers.protection_recovery import committed

        assert session.protection_store is not None
        committed(session.protection_store, session.target, session.protection_requests)
        session.protection_requests.clear()
    guard.prevented_rows, guard.prevented_values = protected_rows, protected_values
    return _uploaded_counts(results, guard)


def _uploaded_counts(results: list[HandlerResult], guard: Protection) -> HandlerResult:
    """Sum per-file changes while reporting the final target size once."""
    counts = {}
    for name in (
        "source_count",
        "insert_count",
        "update_count",
        "delete_count",
        "reject_count",
        "duplicate_count",
    ):
        values = [getattr(result, name) for result in results]
        counts[name] = None if any(value is None for value in values) else sum(values)
    return HandlerResult(
        **counts,
        target_count=results[-1].target_count if results else None,
        variables={
            "PROTECTED_ROWS": guard.prevented_rows,
            "PROTECTED_VALUES": guard.prevented_values,
        },
    )


def _watermarked_task(
    task: SqlTask, context: TaskContext, store: TaskStore, state: TaskState | None
) -> SqlTask:
    """Freeze the run cursor before executing or staging its managed SELECT."""
    if task.watermark is not None:
        assert state is not None
        stored = None if context.backfill else state.offset
        if task.bounded:
            mark = task.watermark.start
            window = store.window(
                WindowDefinition(
                    StoredOffset(mark.datatype, mark.stored()),
                    source_pipelines(context.task_params),
                    context.backfill,
                )
            )
            stored = StoredOffset(
                mark.datatype, window.low.isoformat(), context.task_run_id, window.high
            )
        task = read_sql_task(context, stored)
    return task
