"""Bound values and registered auxiliary objects, never target business-row writes."""

from datetime import datetime

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import Connection

from etl_craft.dialects.warehouse.base import WarehouseDialect


def rejects_statement(
    table: str, cutoff: datetime, pipelines: list[int], *, delete: bool
) -> TextClause:
    """Restrict old reject rows to the selected project's stable pipeline identities."""
    verb = "DELETE" if delete else "SELECT COUNT(*) AS count"
    return text(
        f"{verb} FROM {table} WHERE CREATE_DATE<:cutoff AND PIPELINE_ID IN :pipelines"
    ).bindparams(bindparam("pipelines", expanding=True), cutoff=cutoff, pipelines=pipelines)


def relation_kind(dialect: WarehouseDialect, conn: Connection, table: str) -> str | None:
    """Read an existing relation kind through its dialect's catalog query."""
    query, params = dialect.relation_type_query(table)
    return conn.execute(text(query), params).scalar_one_or_none()


def reject_breakdown_statement(table: str) -> TextClause:
    """Group only rejection reasons, scoped to the exact run and task."""
    return text(
        f"SELECT REJECT_REASON AS reason, COUNT(*) AS count FROM {table} "
        "WHERE PIPELINE_ID = :pipeline_id AND PIPELINE_RUN_ID = :run_id "
        "AND TASK_RUN_ID = :task_run_id GROUP BY REJECT_REASON ORDER BY REJECT_REASON"
    )
