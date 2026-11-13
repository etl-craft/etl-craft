"""Columns the engine adds to the tables it writes, as lineage sees them.

A table the engine creates holds the SELECT's columns, then ``PIPELINE_RUN_ID``, the audit
columns of its writing action and ``ROW_ID``. Lineage knows them only when a SELECT names one.
"""

from collections.abc import Iterable, Mapping

from sqlglot import exp

from etl_craft.core.enums import SqlAction
from etl_craft.handlers.sql.session import ROW_ID_COLUMN
from etl_craft.handlers.sql.tables import AUDIT_COLUMNS


def table_key(name: str, catalog: str | None) -> str:
    """Return a table's name as lineage compares it: lower case, without the active database."""
    names = [part.lower() for part in name.split(".") if part]
    if len(names) == 3 and catalog and names[0] == catalog.lower():
        names = names[1:]
    return ".".join(names)


def engine_columns(
    tasks: Iterable[tuple[object, Mapping[str, str]]], catalog: str | None
) -> dict[str, tuple[str, ...]]:
    """Return the columns the engine adds to each table a managed SQL task writes.

    A table the engine creates holds the SELECT's columns, then ``PIPELINE_RUN_ID``, the audit
    columns of its writing action (``SETUP_FOR`` for ``SETUP_TABLE``) and ``ROW_ID``.
    """
    owned: dict[str, tuple[str, ...]] = {}
    for _, params in tasks:
        action = (params.get("SQL_ACTION") or "").upper()
        if action == SqlAction.SETUP_TABLE:
            action = (params.get("SETUP_FOR") or "").upper()
        target = (params.get("TARGET_OBJECT") or "").strip()
        if target and action in AUDIT_COLUMNS:
            columns = ("PIPELINE_RUN_ID", *AUDIT_COLUMNS[action], ROW_ID_COLUMN)
            owned[table_key(target, catalog)] = columns
    return owned


def with_named_engine_columns(
    used: Mapping[str, Mapping[str, str]],
    owned: Mapping[str, tuple[str, ...]],
    tree: exp.Query,
) -> dict[str, dict[str, str]]:
    """Return the source schemas plus the engine columns the SELECT names.

    A column the project declares keeps its declared type; the engine's only fills a missing one.

    A ``*`` still expands to the business columns only, so existing lineage is unchanged.
    """
    named = {column.name.lower() for column in tree.find_all(exp.Column)}
    return {
        table: {
            **{c.lower(): "UNKNOWN" for c in owned.get(table, ()) if c.lower() in named},
            **columns,
        }
        for table, columns in used.items()
    }
