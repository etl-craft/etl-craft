"""Repository definitions of external and script-landed table columns."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlglot import exp
from sqlglot.errors import SqlglotError

from etl_craft.core.text import is_safe_identifier, is_safe_object_ref
from etl_craft.dialects.engine import for_engine
from etl_craft.engine.queries import statement


@dataclass(frozen=True)
class SourceColumn:
    """One active source column in its declared order."""

    table_name: str
    column_name: str
    data_type: str
    column_position: int
    is_nullable: str | None = None
    object_kind: str | None = None


def fetch_source_columns(conn: Connection) -> list[SourceColumn]:
    """Read source definitions without connecting to the warehouse."""
    if not for_engine(conn).has_table(conn, "CFG_COLUMNS"):
        return [
            SourceColumn(*row)
            for row in conn.execute(
                text(
                    "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, "
                    "DATA_TYPE AS data_type, "
                    "COLUMN_POSITION AS column_position FROM CFG_SOURCE_COLUMNS "
                    "WHERE ACTIVE_FLAG='Y' ORDER BY lower(TABLE_NAME), COLUMN_POSITION"
                )
            )
        ]
    return [
        SourceColumn(
            ".".join(
                part
                for part in (row.catalog_name, row.schema_name, row.object_name)
                if part is not None
            ),
            row.column_name,
            row.data_type,
            row.column_position,
            row.is_nullable,
            row.object_kind,
        )
        for row in conn.execute(statement(conn, "source_columns"))
    ]


def definition_problem(column: SourceColumn, dialect: str | None) -> str | None:
    """Check definitions from either CSV files or project migrations."""
    if not is_safe_object_ref(column.table_name):
        return (
            f"TABLE_NAME={column.table_name!r}: expected schema.table or "
            f"database.schema.table; correct the source definition"
        )
    if not is_safe_identifier(column.column_name):
        return (
            f"COLUMN_NAME={column.column_name!r}: expected an unquoted SQL identifier; "
            f"correct the source definition"
        )
    try:
        kind = exp.DataType.build(column.data_type, dialect=dialect)
        if kind.this == exp.DataType.Type.UNKNOWN:
            return (
                f"DATA_TYPE={column.data_type!r}: expected a known SQL type; "
                "correct the source definition"
            )
    except (SqlglotError, ValueError) as error:
        return (
            f"DATA_TYPE={column.data_type!r}: expected a SQL type for "
            f"{dialect or 'the warehouse'} ({error}); correct the source definition"
        )
    return None
