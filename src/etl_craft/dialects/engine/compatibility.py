"""Conservative SQL checks for Engine migrations after the stable baseline."""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from etl_craft.core.errors import MigrationError


def require_additive_migration(sql: str, dialect: str, name: str) -> None:
    """Only new tables, indexes and nullable columns preserve old binary writes."""
    if re.search(r"^\s*--\s*etl-craft:", sql, re.MULTILINE):
        raise MigrationError(f"{name}: non-additive migration marker; use additive SQL only")
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except ParseError as error:
        raise MigrationError(
            f"{name}: cannot verify additive SQL; rewrite the migration"
        ) from error
    for statement in statements:
        if statement is not None and not _additive(statement):
            raise MigrationError(
                f"{name}: non-additive migration: {statement.sql()}; "
                "after 0.9.0 add only tables, nullable columns or indexes"
            )


def _additive(statement: exp.Expr) -> bool:
    if isinstance(statement, exp.Create):
        return (
            statement.kind in {"TABLE", "INDEX"}
            and not statement.args.get("replace")
            and statement.expression is None
        )
    if not isinstance(statement, exp.Alter) or statement.kind != "TABLE":
        return False
    actions = statement.args.get("actions", [])
    return bool(actions) and all(
        isinstance(action, exp.ColumnDef)
        and isinstance(action.kind, exp.DataType)
        and action.kind.sql().upper() not in {"SERIAL", "SMALLSERIAL", "BIGSERIAL"}
        and all(
            isinstance(constraint.kind, (exp.DefaultColumnConstraint, exp.CommentColumnConstraint))
            or (
                isinstance(constraint.kind, exp.NotNullColumnConstraint)
                and constraint.kind.args.get("allow_null")
            )
            for constraint in action.constraints
        )
        for action in actions
    )
