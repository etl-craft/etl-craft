"""Keyed hard/soft deletion with the same target lock and write-ahead event service."""

from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.errors import SqlGuardError
from etl_craft.dialects.warehouse.merges import delete_merge, matched_merge
from etl_craft.dialects.warehouse.uploads import writer_expression
from etl_craft.handlers.protection_delete import intent
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.tables import (
    check_identity_types,
    check_update_precision,
    refuse_null_keys,
    require_target,
)


def key_match(keys: tuple[str, ...], target: str = "t") -> str:
    """Use every component of the admitted stable business identity."""
    return " AND ".join(f"{target}.{c}=s.{c}" for c in keys)


def delete_rows(session: Session, action: ActionContext) -> HandlerResult:
    """Delete matching business keys, retaining all current protection semantics."""
    task = action.task
    stage = action.build_stage(session)
    counts = session.run(
        session.dialect.key_counts(stage, task.merge_key), step="NULL merge keys"
    ).one()
    source = int(counts.source_rows)
    require_target(session)
    refuse_null_keys(session, stage, task.merge_key, int(counts.null_keys))
    if not task.hard_delete:
        _check_soft(session)
    if session.protection is not None:
        stage = session.protection.stage(stage, delete=True)
    match = key_match(task.merge_key)
    live = "" if task.hard_delete else " AND t.ACTIVE_FLAG='Y' AND t.DELETE_FLAG='N'"
    count_sql = (
        f"SELECT COUNT(*) FROM {session.target} t WHERE "
        f"EXISTS (SELECT 1 FROM {stage} s WHERE {match}){live}"
    )
    count = (
        _hard(session, action, stage, count_sql)
        if task.hard_delete
        else _soft(session, action, stage, count_sql)
    )
    session.drop(stage)
    return HandlerResult(source_count=source, delete_count=count)


def _check_soft(session: Session) -> None:
    have = {name.lower() for name, _ in session.target_columns()}
    missing = [
        c
        for c in (
            "PIPELINE_RUN_ID",
            "PIPELINE_ID",
            "TASK_RUN_ID",
            "DELETE_FLAG",
            "ACTIVE_FLAG",
            "UPDATE_DATE",
            "UPDATED_BY",
        )
        if c.lower() not in have
    ]
    if missing:
        raise SqlGuardError(
            f"{session.target} lacks {', '.join(missing)}, which "
            "a soft DELETE_ROWS sets; run a SETUP_TABLE task "
            "for it, add the columns, or set HARD_DELETE=true"
        )
    check_identity_types(session)
    check_update_precision(session)


def _intent(
    session: Session, action: ActionContext, stage: str, kind: ProtectionKind, live: str = ""
) -> str | None:
    keys = action.task.merge_key
    if session.protection_active is False:
        return None
    if "etl_protection" not in {c.lower() for c, _ in session.target_columns()}:
        return None
    physical = {c.lower(): c for c, _ in session.target_columns()}
    hashed = session.hash([f"t.{c}" for c in keys], keys)
    return intent(
        session,
        tuple(physical[c.lower()] for c in keys),
        kind,
        f"SELECT DISTINCT {hashed} AS key_hash FROM {session.target} "
        f"t WHERE EXISTS (SELECT 1 FROM {stage} s WHERE "
        f"{key_match(keys)}){live} AND t.ETL_PROTECTION IS NOT NULL",
    )


def _hard(session: Session, action: ActionContext, stage: str, count_sql: str) -> int:
    task = action.task
    _intent(session, action, stage, ProtectionKind.HARD_DELETE)
    source = f"(SELECT DISTINCT {', '.join(task.merge_key)} FROM {stage})"
    mutation, qualifier = session.mutation_target()
    sql = (
        delete_merge(session.target, source, task.merge_key)
        if session.dialect.supports_insert_merge(session.conn)
        else f"DELETE FROM {mutation} WHERE EXISTS (SELECT 1 "
        f"FROM {stage} s WHERE {key_match(task.merge_key, qualifier)})"
    )
    return session.mutate(sql, {}, count_sql=count_sql, step="delete the rows")


def _soft(session: Session, action: ActionContext, stage: str, count_sql: str) -> int:
    task = action.task
    request = None
    if session.protection is not None:
        request = _intent(
            session,
            action,
            stage,
            ProtectionKind.SOFT_DELETE,
            " AND t.ACTIVE_FLAG='Y' AND t.DELETE_FLAG='N'",
        )
    columns = ", ".join(task.merge_key)
    extra = (
        ", MAX(UPLOAD_ID) AS UPLOAD_ID"
        if action.uploads and "upload_id" not in {c.lower() for c in task.merge_key}
        else ""
    )
    source = f"(SELECT {columns}{extra} FROM {stage} GROUP BY {columns})"
    writer = writer_expression(action.uploads, "s.UPLOAD_ID")
    assignments = {
        "DELETE_FLAG": "'Y'",
        "ACTIVE_FLAG": "'N'",
        "UPDATE_DATE": ":now",
        "PIPELINE_RUN_ID": ":pipeline_run_id",
        "PIPELINE_ID": ":pipeline_id",
        "TASK_RUN_ID": ":task_run_id",
        "UPDATED_BY": writer,
    }
    if action.uploads:
        assignments.update(UPLOAD_ID="s.UPLOAD_ID", CREATED_BY=writer)
    if request is not None:
        assignments["ETL_PROTECTION_REQUEST_ID"] = ":protection_request_id"
    condition = "t.ACTIVE_FLAG='Y' AND t.DELETE_FLAG='N'"
    sql = (
        matched_merge(session.target, source, assignments, task.merge_key)
        if session.dialect.supports_insert_merge(session.conn)
        else session.dialect.update_from_stage(
            session.target, source, task.merge_key, assignments, condition
        )
    )
    # The source must exclude already-deleted physical versions on MERGE-capable providers.
    if session.dialect.supports_insert_merge(session.conn):
        sql = sql.replace("WHEN MATCHED THEN", f"WHEN MATCHED AND ({condition}) THEN")
    return session.mutate(
        sql,
        {**action.stamp, "protection_request_id": request},
        count_sql=count_sql,
        step="flag the rows deleted",
    )
