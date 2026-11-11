"""The nine SQL actions. Each wraps the task's SELECT in the writes it stands for.

- ``CREATE_TABLE`` replaces the target from the staged SELECT with rollback or recovery.
- ``SETUP_TABLE`` creates the target, empty, from the SELECT's shape plus the audit columns of
  the action that writes it, when it does not exist yet; an existing target is left alone.
- ``OVERWRITE_TABLE`` replaces the rows with atomic publication or row recovery.
- ``APPEND_TABLE`` inserts the SELECT's rows, without comparing the shapes.
- ``SCD1_MERGE`` updates changed rows in place by merge key and inserts new keys.
- ``SCD2_MERGE`` closes the active version of a changed key (``ACTIVE_FLAG='N'``) and inserts a
  new one.

  In both merges a key soft-deleted by ``DELETE_ROWS`` that the SELECT returns again comes back
  (``DELETE_FLAG='N'``), changed or not. A NULL in a merge key column fails the task.
- ``DROP_TABLE`` drops the target if it exists, once this pipeline's ``CREATE_TABLE`` task for
  it has succeeded in the run.
- ``DELETE_ROWS`` hard deletes matching keys, or sets ``DELETE_FLAG='Y'`` and
  ``ACTIVE_FLAG='N'`` on matching current live rows; closed history is left unchanged.

Only ``CREATE_TABLE`` and ``SETUP_TABLE`` create tables; every other action fails, naming the
remedy, when its target does not exist.

Each reports the counts it can know: source rows, target rows after the write, and the rows
inserted, updated or deleted.

A row counts as changed when its ``HASH_KEY``, an MD5 over ``MERGE_COMPARE_COLUMNS``, differs.
Merge updates join the deduplicated stage using the warehouse's UPDATE FROM or matched MERGE
strategy. SCD2 publishes closures and successors in one MERGE where supported, otherwise in
one transaction.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from etl_craft.core.actor import Actor
from etl_craft.core.counts import Counts
from etl_craft.core.enums import ActorKind, RunStatus, SqlAction
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.faults import fault_point
from etl_craft.core.protection import PROTECTION_COLUMNS
from etl_craft.core.text import sha256_hex
from etl_craft.core.uploads import UploadWriter
from etl_craft.dialects.warehouse.metadata import projection_names
from etl_craft.dialects.warehouse.uploads import actor_parts, writer_expression
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.creation import create_table, setup_table
from etl_craft.handlers.sql.deletes import delete_rows
from etl_craft.handlers.sql.protection import ProtectionRequest
from etl_craft.handlers.sql.protection_columns import (
    baseline,
    business_columns,
    fingerprint,
    metadata_result,
)
from etl_craft.handlers.sql.rejects import screen
from etl_craft.handlers.sql.replacement import cleanup, recover_overwrite
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.tables import (
    IDENTITY_COLUMNS,
    add_hash_key,
    check_identity_types,
    check_or_evolve,
    check_stage_columns,
    check_target_audit,
    dedupe,
    refuse_empty,
    refuse_null_keys,
    require_target,
)
from etl_craft.handlers.sql.upload_controls import boolean_problem

logger = logging.getLogger(__name__)


Action = Callable[[Session, ActionContext], HandlerResult]


def _overwrite_source_rows(session: Session, action: ActionContext, stage: str) -> int | None:
    """Count the staged rows when a limit, the dialect or ``ALLOW_EMPTY=false`` needs them."""
    task = action.task
    if task.reject_limit is None and session.dialect.dml_rowcounts and task.allow_empty:
        return None
    source = session.count(f"SELECT COUNT(*) FROM {stage}", step="source rows")
    if not task.allow_empty:
        refuse_empty(session, source, action.context.task_code)
    return source


def overwrite_table(session: Session, action: ActionContext) -> HandlerResult:
    """Empty the target and insert the SELECT's rows."""
    stage = action.build_stage(session)
    source = _overwrite_source_rows(session, action, stage)
    stage, rejected = (
        screen(session, stage, action.task, source, action.stamp)
        if source is not None
        else (stage, None)
    )
    strategy = session.dialect.replace_strategy
    check_or_evolve(
        session, stage, SqlAction.OVERWRITE_TABLE, schema_evolution=action.task.schema_evolution
    )
    columns = ", ".join(name for name, _ in session.columns(stage))
    actor_columns, actor_values = actor_parts(
        action.uploads, "UPLOAD_ID", (name for name, _ in session.target_columns())
    )
    computed = not session.row_id_generated()
    row_id_columns = ", ROW_ID" if computed else ""
    row_id_values = ", CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT)" if computed else ""
    select_sql = (
        f"SELECT {columns}, :pipeline_run_id, :pipeline_id, :task_run_id, :now"
        f"{actor_values}{row_id_values} "
        f"FROM {stage}"
    )
    written_columns = (
        f"{columns}, PIPELINE_RUN_ID, PIPELINE_ID, TASK_RUN_ID, UPDATE_DATE"
        f"{actor_columns}{row_id_columns}"
    )
    if strategy == "create_or_replace":
        ddl = _overwrite_ddl(session, action, stage, written_columns, select_sql)
        fault_point("sql.replace.before_publish")
        result = session.run(ddl, action.stamp, step="atomically overwrite the target")
        if source is None:
            source = session.dialect.affected_rows(result)
    else:
        guard = (
            recover_overwrite(session)
            if strategy == "copy_and_restore"
            else contextlib.nullcontext()
        )
        with guard:
            fault_point("sql.replace.before_publish")
            session.run(f"TRUNCATE TABLE {session.target}", step="empty the target")
            fault_point("sql.replace.after_clear")
            result = session.run(
                f"INSERT INTO {session.target} ({written_columns}) {select_sql}",
                action.stamp,
                step="insert the SELECT's rows",
            )
            if source is None:
                source = session.dialect.affected_rows(result)
            fault_point("sql.replace.after_publish")
    written = source - (rejected or 0)
    cleanup(session, stage)
    return HandlerResult(
        source_count=source, target_count=written, insert_count=written, reject_count=rejected
    )


def _overwrite_ddl(
    session: Session, action: ActionContext, stage: str, written_columns: str, select_sql: str
) -> str:
    """Render a replacement against the existing target's exact physical types."""
    writer = writer_expression(action.uploads, "UPLOAD_ID")
    if session.dialect.overwrite_uses_ctas:
        names = [name for name, _ in session.target_columns()]
        types = session.column_types(session.target)
        managed = {
            "pipeline_run_id": "CAST(:pipeline_run_id AS BIGINT) AS PIPELINE_RUN_ID",
            "task_run_id": "CAST(:task_run_id AS BIGINT) AS TASK_RUN_ID",
            "pipeline_id": "CAST(:pipeline_id AS BIGINT) AS PIPELINE_ID",
            "update_date": f"CAST(:now AS {types['update_date']}) AS UPDATE_DATE",
            "row_id": "CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) AS ROW_ID",
        }
        if action.uploads:
            managed.update(
                **{
                    name: f"{writer} AS {name.upper()}"
                    for name in ("created_by", "updated_by")
                    if name in types
                }
            )
        expressions = [
            managed.get(name.lower(), f"CAST({name} AS {types[name.lower()]}) AS {name}")
            for name in names
        ]
        ddl = session.dialect.replacement_ddl(
            session.conn,
            session.target,
            f"SELECT {', '.join(expressions)} FROM {stage}",
            {},
            existing=True,
        )
    else:
        ddl = session.dialect.overwrite_statement(session.target, written_columns, select_sql)
    return ddl


def append_table(session: Session, action: ActionContext) -> HandlerResult:
    """Replace this task run's appended batch, retaining rows from other loads.

    TASK_RUN_ID makes retries converge after an insert committed without its task outcome, so a
    target without it is refused before anything is staged, naming the command that adds it.
    """
    present = {name.lower() for name, _ in require_target(session)}
    if "task_run_id" not in present:
        raise SqlGuardError(
            f"{session.target} has no TASK_RUN_ID column, so retrying an append could duplicate "
            "rows; add it with `etl-craft upgrade-targets --action APPEND_TABLE --target "
            f"{session.target_object}`"
        )
    check_identity_types(session, tuple(c for c in IDENTITY_COLUMNS if c.lower() in present))
    stage = action.build_stage(session)
    source = (
        session.count(f"SELECT COUNT(*) FROM {stage}", step="source rows")
        if action.task.reject_limit is not None or not session.dialect.dml_rowcounts
        else None
    )
    stage, rejected = (
        screen(session, stage, action.task, source, action.stamp)
        if source is not None
        else (stage, None)
    )
    session.run(
        f"DELETE FROM {session.target} WHERE TASK_RUN_ID = :task_run_id",
        {"task_run_id": action.context.task_run_id},
        step="clear this task run's previous append",
    )
    fault_point("sql.append.after_delete")
    columns = ", ".join(name for name, _ in session.columns(stage))
    row_id_columns, row_id_values = session.row_id_insert_parts()
    actor_columns, actor_values = actor_parts(
        action.uploads, "UPLOAD_ID", (name for name, _ in session.target_columns())
    )
    pipeline_column = ", PIPELINE_ID" if "pipeline_id" in present else ""
    pipeline_value = ", :pipeline_id" if pipeline_column else ""
    result = session.run(
        f"INSERT INTO {session.target} "
        f"({columns}, PIPELINE_RUN_ID, CREATE_DATE, TASK_RUN_ID"
        f"{pipeline_column}{actor_columns}{row_id_columns}) "
        f"SELECT {columns}, :pipeline_run_id, :now, :task_run_id"
        f"{pipeline_value}{actor_values}{row_id_values} "
        f"FROM {stage}",
        action.stamp,
        step="append the SELECT's rows",
    )
    if source is None:
        source = session.dialect.affected_rows(result)
    fault_point("sql.append.after_insert")
    session.drop(stage)
    target_count = session.count(f"SELECT COUNT(*) FROM {session.target}", step="target rows")
    return HandlerResult(
        source_count=source,
        target_count=target_count,
        insert_count=source - (rejected or 0),
        reject_count=rejected,
    )


def _merge_stage(
    session: Session, action: ActionContext, kind: SqlAction
) -> tuple[str, Counts, int | None]:
    """Return the checked, hashed stage, input counts and optional new-key count."""
    task = action.task
    check_target_audit(session, kind)
    version = action.store.target(session.target).hash_version
    if version != 2:
        raise SqlGuardError(
            f"{session.target} has hash version {version or 'unknown'}; "
            f"run `etl-craft rehash --target {session.target_object}` before merging"
        )
    hashed = not (
        action.staged
        or task.reject_limit is not None
        or task.schema_evolution
        or task.watermark is not None
        or task.dedupe_order
        or session.protection is not None
        or action.uploads
    )
    hashed = (
        hashed
        and projection_names(
            action.select_sql, session.dialect.sqlglot_dialect, session.dialect.identifier_case
        )
        is not None
    )
    if hashed:
        stage = session.scratch("stage")
        session.select_columns(stage, action.select_sql)
        check_stage_columns(session, stage)
        check_or_evolve(session, stage, kind, schema_evolution=False)
        stage = session.create_hashed_stage(stage, action.select_sql, task.merge_compare_columns)
    else:
        stage = action.build_stage(session)
    count_target = session.target if hashed and kind == SqlAction.SCD1_MERGE else None
    source, rejected = None, None
    if task.reject_limit is not None:
        source = session.count(f"SELECT COUNT(*) FROM {stage}", step="source rows")
        stage, rejected = screen(session, stage, task, source, action.stamp)
        count_target = None
    locked = any(c.lower() == "locked" for c, _ in session.columns(stage))
    counts = session.run(
        session.dialect.key_counts(stage, task.merge_key, count_target, locked=locked),
        step="NULL merge keys",
    ).one()
    source = int(counts.source_rows) if source is None else source
    if locked and (
        problem := boolean_problem(
            f"{action.context.pipeline_code}.{action.context.task_code}", str(counts.locked_type)
        )
    ):
        raise SqlGuardError(problem)
    refuse_null_keys(session, stage, task.merge_key, int(counts.null_keys))
    stage = dedupe(session, stage, task.merge_key, task.dedupe_order, int(counts.duplicate_keys))
    check_or_evolve(session, stage, kind, schema_evolution=task.schema_evolution)
    if session.protection is not None and action.respect_protection:
        stage = session.protection.stage(stage)
    if not hashed:
        add_hash_key(session, stage, task.merge_compare_columns)
    if session.protection is not None:
        request = session.protection.request or ProtectionRequest.create(
            Actor(action.user, ActorKind.SYSTEM), f"ETL {task.action}"
        )
        condition = edit_condition(
            action,
            business_columns(tuple(c for c, _ in session.columns(stage))),
            "t.HASH_KEY IS DISTINCT FROM s.HASH_KEY OR t.DELETE_FLAG='Y'",
        )
        stage = session.protection.prepare(stage, request, condition)
    session.prepare_update_stage(stage, task.merge_key)
    input_counts = Counts(
        source_count=source,
        reject_count=rejected,
        duplicate_count=int(counts.duplicate_rows) if task.dedupe_order else None,
    )
    return stage, input_counts, int(counts.new_keys) if count_target else None


def scd1_merge(session: Session, action: ActionContext) -> HandlerResult:
    """Update changed rows in place by merge key and insert new keys.

    With ``PRESERVE_TARGET``, a NULL in the SELECT keeps the target's value, and the hash is
    taken over the values actually kept.
    """
    task = action.task
    stage, input_counts, new = _merge_stage(session, action, SqlAction.SCD1_MERGE)
    if metadata_only := metadata_result(session, stage, input_counts):
        return metadata_only
    stage_columns = [
        name
        for name, _ in session.columns(stage)
        if name.upper() not in PROTECTION_COLUMNS and name.lower() != "locked"
    ]
    assignments, condition = _scd1_update(session, action, stage_columns)
    target = session.target
    key_match = _key_match(task.merge_key)
    generated = session.row_id_generated()
    merge_source = stage if generated else _numbered_merge_source(session, stage, task.merge_key)
    if session.dialect.supports_insert_merge(session.conn):
        if new is None:
            new = session.count(
                f"SELECT COUNT(*) FROM {stage} s WHERE NOT EXISTS "
                f"(SELECT 1 FROM {target} t WHERE {key_match})",
                step="new rows",
            )
        insert = _merge_insert_parts(
            session,
            stage_columns,
            None if generated else (", ROW_ID", ", s.ROW_ID"),
            uploads=action.uploads,
        )
        result = session.run(
            session.dialect.update_from_stage(
                target, merge_source, task.merge_key, assignments, condition, insert
            ),
            action.stamp,
            step="merge changed and new rows",
        )
        insert_count = new
        update_count = session.dialect.affected_rows(result) - new
        fault_point("sql.scd1.after_update")
    else:
        update_count = session.mutate(
            session.dialect.update_from_stage(
                target, stage, task.merge_key, assignments, condition
            ),
            action.stamp,
            count_sql=f"SELECT COUNT(*) FROM {target} t JOIN {stage} s ON {key_match} "
            f"WHERE {condition}",
            step="update changed rows",
        )
        fault_point("sql.scd1.after_update")

        new_keys = f"NOT EXISTS (SELECT 1 FROM {target} t WHERE {key_match})"
        insert_count = _insert_merge_rows(
            session,
            action,
            stage_columns,
            f"FROM {stage} s WHERE {new_keys}",
            step="insert new rows",
        )
    if session.protection is not None:
        update_count = session.protection.mutating_rows - insert_count
    fault_point("sql.scd1.after_insert")
    session.drop(stage)
    target_count = session.count(f"SELECT COUNT(*) FROM {target}", step="target rows")
    return HandlerResult(
        source_count=input_counts.source_count,
        target_count=target_count,
        insert_count=insert_count,
        update_count=update_count,
        reject_count=input_counts.reject_count,
        duplicate_count=input_counts.duplicate_count,
    )


def _scd1_update(
    session: Session, action: ActionContext, stage_columns: list[str]
) -> tuple[dict[str, str], str]:
    """Compare and stamp changed rows, including restored and preserved target values."""
    task = action.task
    keys = {key.lower() for key in task.merge_key}
    non_key = [column for column in stage_columns if column.lower() not in keys]

    def kept_hash(alias: str) -> str:
        return session.hash(
            [f"COALESCE(s.{c}, {alias}.{c})" for c in task.merge_compare_columns],
            task.merge_compare_columns,
        )

    compared = kept_hash("t") if task.preserve_target else "s.HASH_KEY"
    condition = f"(t.HASH_KEY IS DISTINCT FROM {compared} OR t.DELETE_FLAG = 'Y')"
    condition = edit_condition(action, business_columns(tuple(non_key)), condition)
    assignments = {}
    for column in non_key:
        value = f"s.{column}"
        if task.preserve_target:
            value = (
                kept_hash("t") if column.lower() == "hash_key" else f"COALESCE({value}, t.{column})"
            )
        assignments[column] = value
    assignments.update(
        PIPELINE_RUN_ID=":pipeline_run_id",
        TASK_RUN_ID=":task_run_id",
        PIPELINE_ID=":pipeline_id",
        UPDATE_DATE=":now",
        UPDATED_BY=writer_expression(action.uploads, "s.UPLOAD_ID"),
        DELETE_FLAG="'N'",
        ACTIVE_FLAG="'Y'",
    )
    if action.uploads:
        assignments["CREATED_BY"] = writer_expression(action.uploads, "s.UPLOAD_ID")
    business = business_columns(stage_columns)
    baseline(session, task, business)
    assignments.update(_protection_assignments(session, business, preserve=task.preserve_target))
    if session.protection is not None and session.protection.request_id is not None:
        session.bindings["protection_request_id"] = session.protection.request_id
        condition = f"({condition} OR s.ETL_PROTECTION_REQUEST_ID=:protection_request_id)"
    return assignments, condition


def _protection_assignments(
    session: Session, columns: tuple[str, ...], *, preserve: bool = False
) -> dict[str, str]:
    if session.protection is not None:
        return {name: f"s.{name}" for name in PROTECTION_COLUMNS}
    return {
        "ETL_PROTECTION": ":protection_baseline",
        "ETL_ROW_FINGERPRINT": fingerprint(
            session, columns, "s", ":protection_baseline", preserve=preserve
        ),
        "ETL_PROTECTION_REQUEST_ID": "NULL",
    }


def _numbered_merge_source(session: Session, stage: str, keys: tuple[str, ...]) -> str:
    """Use the existing target generator contract in an atomic merge source."""
    from etl_craft.dialects.warehouse.merges import keyed_source

    return keyed_source(session.target, stage, keys, session.row_id_base())


def scd2_merge(session: Session, action: ActionContext) -> HandlerResult:
    """Close the active version of each changed key and insert a new active version.

    A key with no active version, new or left without one by an interrupted earlier run, gets
    one inserted, so a rerun converges.
    """
    stage, input_counts, _ = _merge_stage(session, action, SqlAction.SCD2_MERGE)
    if metadata_only := metadata_result(session, stage, input_counts):
        return metadata_only
    stage_columns = [
        name
        for name, _ in session.columns(stage)
        if name.upper() not in PROTECTION_COLUMNS and name.lower() != "locked"
    ]
    target = session.target

    baseline(session, action.task, business_columns(stage_columns))
    condition = "t.HASH_KEY IS DISTINCT FROM s.HASH_KEY OR t.DELETE_FLAG = 'Y'"
    condition = edit_condition(action, business_columns(tuple(stage_columns)), condition)
    if session.dialect.supports_insert_merge(session.conn):
        closed, inserted = _merge_versions(session, action, stage, stage_columns, condition)
    else:
        closed, inserted = _separate_versions(session, action, stage, stage_columns, condition)
    fault_point("sql.scd2.after_versions")
    fault_point("sql.scd2.after_insert")
    session.drop(stage)
    target_count = session.count(f"SELECT COUNT(*) FROM {target}", step="target rows")
    return HandlerResult(
        source_count=input_counts.source_count,
        target_count=target_count,
        insert_count=inserted,
        update_count=closed,
        reject_count=input_counts.reject_count,
        duplicate_count=input_counts.duplicate_count,
    )


def _version_assignments(action: ActionContext) -> dict[str, str]:
    return {
        "ACTIVE_FLAG": "'N'",
        "UPDATE_DATE": ":now",
        "UPDATED_BY": writer_expression(action.uploads, "s.UPLOAD_ID"),
        **(
            {"CREATED_BY": writer_expression(action.uploads, "s.UPLOAD_ID")}
            if action.uploads
            else {}
        ),
        "PIPELINE_RUN_ID": ":pipeline_run_id",
        "TASK_RUN_ID": ":task_run_id",
        "PIPELINE_ID": ":pipeline_id",
        "ETL_PROTECTION_REQUEST_ID": ":protection_request_id",
    }


def _merge_versions(
    session: Session, action: ActionContext, stage: str, columns: list[str], condition: str
) -> tuple[int, int]:
    from etl_craft.dialects.warehouse.merges import VersionMerge, numbered_source

    metadata = None
    if session.protection is not None and session.protection.request_id is not None:
        metadata = {c: f"s.{c}" for c in PROTECTION_COLUMNS}
    merge = VersionMerge(
        session.target,
        stage,
        action.task.merge_key,
        tuple(columns),
        condition,
        "s.ETL_PROTECTION_REQUEST_ID=:protection_request_id" if metadata is not None else None,
    )
    session.bindings["protection_request_id"] = (
        session.protection.request_id if session.protection else None
    )
    counts = session.run(merge.counts(), step="count version changes").one()
    source = merge.source()
    row_ids = None
    if not session.row_id_generated():
        _, values = session.row_id_insert_parts()
        source = numbered_source(source, values.removeprefix(", "), merge.allocated)
        row_ids = (", ROW_ID", f", s.{merge.allocated}")
    insert = _merge_insert_parts(session, columns, row_ids, uploads=action.uploads)
    session.run(
        merge.statement(source, _version_assignments(action), insert, metadata),
        action.stamp,
        step="merge closed and new versions",
    )
    fault_point("sql.scd2.after_close")
    return int(counts.closed), int(counts.inserted)


def _separate_versions(
    session: Session, action: ActionContext, stage: str, columns: list[str], condition: str
) -> tuple[int, int]:
    target = session.target
    session.bindings["protection_request_id"] = (
        session.protection.request_id if session.protection else None
    )
    key_match = _key_match(action.task.merge_key)
    guard = session.protection
    if guard is not None and guard.request_id is not None:
        from etl_craft.dialects.warehouse.merges import VersionMerge

        merge = VersionMerge(
            target,
            stage,
            action.task.merge_key,
            tuple(columns),
            condition,
            "s.ETL_PROTECTION_REQUEST_ID=:protection_request_id",
        )
        result = session.run(
            merge.fallback(_version_assignments(action), {c: f"s.{c}" for c in PROTECTION_COLUMNS}),
            action.stamp,
            step="close versions and update current locks",
        )
        closed = sum(bool(value) for value in result.scalars())
    else:
        closed = session.mutate(
            session.dialect.update_from_stage(
                target,
                stage,
                action.task.merge_key,
                _version_assignments(action),
                f"t.ACTIVE_FLAG = 'Y' AND ({condition})",
            ),
            action.stamp,
            count_sql=f"SELECT COUNT(*) FROM {target} t JOIN {stage} s ON {key_match} "
            f"WHERE t.ACTIVE_FLAG = 'Y' AND ({condition})",
            step="close the active version of changed keys",
        )
    fault_point("sql.scd2.after_close")

    no_active = f"NOT EXISTS (SELECT 1 FROM {target} t WHERE {key_match} AND t.ACTIVE_FLAG = 'Y')"
    inserted = _insert_merge_rows(
        session, action, columns, f"FROM {stage} s WHERE {no_active}", step="insert new keys"
    )
    return closed, inserted


def _insert_merge_rows(
    session: Session, action: ActionContext, columns: list[str], body: str, *, step: str
) -> int:
    names, values = _merge_insert_parts(session, columns, uploads=action.uploads)
    return session.mutate(
        f"INSERT INTO {session.target} ({names}) SELECT {values} {body}",
        action.stamp,
        count_sql=f"SELECT COUNT(*) {body}",
        step=step,
    )


def _merge_insert_parts(
    session: Session,
    columns: list[str],
    row_ids: tuple[str, str] | None = None,
    *,
    uploads: tuple[UploadWriter, ...] = (),
) -> tuple[str, str]:
    """Share inserted business and audit values between INSERT and MERGE."""
    row_id_columns, row_id_values = session.row_id_insert_parts() if row_ids is None else row_ids
    writer = writer_expression(uploads, "s.UPLOAD_ID")
    business = business_columns(columns)
    if session.protection is not None:
        metadata = ", s.ETL_PROTECTION, s.ETL_ROW_FINGERPRINT, s.ETL_PROTECTION_REQUEST_ID"
    else:
        session.bindings.setdefault("protection_baseline", "")
        hashed = fingerprint(session, business, "s", ":protection_baseline")
        metadata = f", :protection_baseline, {hashed}, NULL"
    return (
        f"{', '.join(columns)}, PIPELINE_RUN_ID, PIPELINE_ID, TASK_RUN_ID, "
        "CREATE_DATE, CREATED_BY, UPDATE_DATE, UPDATED_BY, DELETE_FLAG, "
        f"ACTIVE_FLAG{row_id_columns}, {', '.join(PROTECTION_COLUMNS)}",
        f"{', '.join(f's.{column}' for column in columns)}, :pipeline_run_id, :pipeline_id, "
        f":task_run_id, :now, {writer}, :now, {writer}, 'N', 'Y'{row_id_values}{metadata}",
    )


def drop_table(session: Session, action: ActionContext) -> HandlerResult:
    """Drop the target if it exists, only once this pipeline's CREATE_TABLE task ran this run.

    A target already gone is not an error: the drop has nothing left to do.
    """
    context = action.context
    target_object = action.task.target_object
    assert action.state is not None
    state = action.state
    creator = next(
        (task for task in state.peers if task.sql_action == SqlAction.CREATE_TABLE), None
    )
    status = state.peer_statuses.get(str(creator.task_id)) if creator is not None else None
    if creator is None:
        raise SqlGuardError(
            f"DROP_TABLE refused for {target_object}: no other active task in this pipeline "
            "creates it with SQL_ACTION=CREATE_TABLE, and DROP_TABLE removes only tables its "
            "own pipeline creates"
        )
    if status != RunStatus.SUCCESS:
        raise SqlGuardError(
            f"DROP_TABLE refused for {target_object}: the task that creates it "
            f"({creator.task_code}) is {status or 'not run'} under pipeline_run_id="
            f"{context.pipeline_run_id}, not SUCCESS; make the drop depend on it"
        )
    if session.target_relation_type() is None:
        logger.info("%s does not exist; nothing to drop", session.target)
        return HandlerResult()
    session.clear_hash_version = True
    session.run(f"DROP TABLE {session.target}", step="drop the target")
    return HandlerResult()


def create_view(session: Session, action: ActionContext) -> HandlerResult:
    """Create the target as a view over the SELECT, or replace it when its statement changed.

    A view still made by the statement this task would run is left as it is, so its locks,
    grants and policies are not touched. A table is never replaced, and nothing is counted.
    """
    kind = session.target_relation_type()
    if kind is not None and kind != "VIEW":
        raise SqlGuardError(
            f"CREATE_VIEW {session.target}: a {kind.lower()} of that name exists, and "
            "CREATE_VIEW replaces only views; choose another TARGET_OBJECT or drop the table"
        )
    secure = action.task.secure_view
    # The replace form names the definition: Databricks words only a new view differently.
    wanted = sha256_hex(
        session.dialect.view_ddl(
            session.target, action.select_sql, secure=secure, exists=True
        ).encode()
    )
    if kind == "VIEW" and action.store.target(session.target).view_statement == wanted:
        logger.info("%s already holds this statement; view kept", session.target)
        return HandlerResult()
    ddl = session.dialect.view_ddl(
        session.target, action.select_sql, secure=secure, exists=kind == "VIEW"
    )
    session.run(ddl, step="create or replace the view")
    session.publish_view_statement = wanted
    return HandlerResult()


ACTIONS: dict[SqlAction, Action] = {
    SqlAction.CREATE_TABLE: create_table,
    SqlAction.SETUP_TABLE: setup_table,
    SqlAction.OVERWRITE_TABLE: overwrite_table,
    SqlAction.APPEND_TABLE: append_table,
    SqlAction.SCD1_MERGE: scd1_merge,
    SqlAction.SCD2_MERGE: scd2_merge,
    SqlAction.DROP_TABLE: drop_table,
    SqlAction.DELETE_ROWS: delete_rows,
    SqlAction.CREATE_VIEW: create_view,
}


def _key_match(keys: tuple[str, ...], target: str = "t", source: str = "s") -> str:
    return " AND ".join(f"{target}.{key} = {source}.{key}" for key in keys)


def edit_condition(action: ActionContext, columns: tuple[str, ...], condition: str) -> str:
    """Deliberate edits also compare columns outside the ETL change-detection contract."""
    if action.staged is None:
        return condition
    changes = " OR ".join(f"t.{c} IS DISTINCT FROM s.{c}" for c in columns)
    return f"({condition} OR {changes})"
