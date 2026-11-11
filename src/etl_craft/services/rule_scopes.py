"""Validate SQL rule scopes through the same admitted contract as execution."""

from sqlalchemy.engine import Connection

from etl_craft.core.rule_flags import parse_scopes
from etl_craft.engine.rule_scopes import rules
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.sql.spec import SqlTask, read_select


def validate_scopes(conn: Connection, context: TaskContext, spec: SqlTask) -> None:
    """Refuse missing SUCCESS dependencies before any SQL task can be published."""
    if spec.select_sql is not None:
        raw, _ = read_select(context.config, context.task_params)
        for scope in parse_scopes(raw):
            rules(conn, context.task_id, scope)
