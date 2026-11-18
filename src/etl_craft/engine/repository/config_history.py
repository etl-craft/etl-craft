"""The ``CFG_`` tables as they stood at a past moment, read from their history tables.

Each ``AUD_<table>_HISTORY`` holds every version of a ``CFG_`` row, valid from ``VALID_FROM``
until ``VALID_TO``. A row's state at a moment is the version valid then; a row with versions but
none valid then did not exist. A row with no version at all has not changed since the Engine DB
began recording, and stands as it is now. The rows go into an in-memory SQLite database holding
the configuration tables, so they are read exactly as the live ones are.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from etl_craft.core.errors import MetadataError
from etl_craft.core.time import as_utc
from etl_craft.dialects.engine import for_engine
from etl_craft.engine.repository.config_rows import TABLES

Row = dict[str, Any]


def config_as_of(conn: Connection, as_of: datetime) -> Engine:
    """Rebuild the ``CFG_`` tables at ``as_of``; ``MetadataError`` where history cannot."""
    dialect = for_engine(conn)
    versions = {
        table.table: dialect.table_rows(conn, f"AUD_{table.table}_HISTORY", order_by="CHANGE_ID")
        for table in TABLES
    }
    _require_history_at(as_of, versions)
    scratch = create_engine("sqlite://", poolclass=StaticPool)
    try:
        with scratch.begin() as out:
            _copy_tables(conn, out, versions, as_of)
            _copy_admin_identity(conn, out, as_of)
    except Exception:
        scratch.dispose()
        raise
    return scratch


def _require_history_at(as_of: datetime, versions: dict[str, list[dict[str, Any]]]) -> None:
    """Refuse a time before the first recorded config change."""
    starts = [as_utc(rows[0]["valid_from"]) for rows in versions.values() if rows]
    if not starts or as_of < min(starts):
        since = f"from {min(starts).isoformat()} on" if starts else "none yet"
        raise MetadataError(
            f"cannot rebuild the config as of {as_of.isoformat()}: the Engine DB records config "
            f"changes {since}, and nothing earlier; choose a later time"
        )


def _copy_tables(
    conn: Connection, out: Connection, versions: dict[str, list[dict[str, Any]]], as_of: datetime
) -> None:
    """Write each ``CFG_`` table's rows at ``as_of``."""
    dialect = for_engine(conn)
    for table in TABLES:
        current = dialect.table_rows(conn, table.table)
        columns = list(current[0]) if current else dialect.column_names(conn, table.table)
        rows = _at(current, versions[table.table], table.id_column.lower(), table.table, as_of)
        for_engine(out).write_table(
            out,
            table.table,
            columns,
            [{name: _cell(row.get(name)) for name in columns} for row in rows],
        )


def _at(
    current: list[Row], versions: list[Row], key: str, table: str, as_of: datetime
) -> list[Row]:
    """Return the rows valid at ``as_of``: their version then, or the current row if unchanged."""
    valid: dict[str, Row] = {}
    first: dict[str, Row] = {}
    for version in versions:
        row_id = str(version[key])
        first.setdefault(row_id, version)
        if as_utc(version["valid_from"]) <= as_of < as_utc(version["valid_to"]):
            valid[row_id] = version
    unknown = [
        row_id
        for row_id, version in first.items()
        if row_id not in valid
        and version["operation"] != "INSERT"
        and as_of < as_utc(version["valid_from"])
    ]
    if unknown:
        raise MetadataError(
            f"cannot rebuild {table} as of {as_of.isoformat()}: row(s) "
            f"{key.upper()} {', '.join(unknown)} existed before the Engine DB "
            "recorded changes and changed later, so their values then are unknown; "
            "choose a time after their first recorded change"
        )
    return list(valid.values()) + [row for row in current if str(row[key]) not in first]


def _cell(value: object) -> object:
    """Keep a value as SQLite can hold it: nested JSON, decimals and dates as text."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, (Decimal, date)):
        return value.isoformat() if isinstance(value, date) else str(value)
    return value


def _copy_admin_identity(conn: Connection, out: Connection, as_of: datetime) -> None:
    """Retain historical project/pool resolution without exporting admin configuration."""
    dialect = for_engine(conn)
    for table, key in (("CFG_PROJECTS", "project_id"), ("CFG_POOLS", "pool_name")):
        current = dialect.table_rows(conn, table)
        versions = dialect.table_rows(conn, f"AUD_{table}_HISTORY", order_by="CHANGE_ID")
        columns = dialect.column_names(conn, table)
        rows = _at(current, versions, key, table, as_of)
        if table == "CFG_PROJECTS" and versions:
            first = min(versions, key=lambda row: row["change_id"])
            if (
                first.get("project_id") == 1
                and first.get("project_code") == "default"
                and as_of < as_utc(first["valid_from"])
            ):
                rows = [first]
        for_engine(out).write_table(
            out, table, columns, [{name: _cell(row.get(name)) for name in columns} for row in rows]
        )
