"""Bound identifier equality and row-level DELETE without exposing parameter values."""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import Dialect, exp, parse_one
from sqlglot.errors import SqlglotError

from etl_craft.core.erasure import ErasureSelection
from etl_craft.core.errors import HandlerError
from etl_craft.dialects.business_rules import quote_output_key
from etl_craft.dialects.warehouse.base import REJECT_COLUMNS, WarehouseDialect


def columns(warehouse: Engine, dialect: WarehouseDialect, table: str) -> tuple[str, ...]:
    """Read the native physical shape without sampling personal values."""
    try:
        with warehouse.connect() as conn:
            table = dialect.erasure_table(conn, table)
            return tuple(
                str(row[0])
                for row in dialect.read_metadata(
                    conn, dialect.erasure_metadata_table(table)
                ).columns
            )
    except SQLAlchemyError:
        raise HandlerError(
            f"table {table}: metadata read failed; expected an existing readable warehouse "
            "table; correct --table or restore the warehouse connection and retry"
        ) from None


def selection_columns(
    warehouse: Engine, dialect: WarehouseDialect, selection: ErasureSelection
) -> tuple[str, ...]:
    """Require an engine reject ledger before selecting an optional auxiliary."""
    if not selection.optional:
        return selection.columns
    existing = set(columns(warehouse, dialect, selection.entry.table))
    if not existing:
        return ()
    missing = set(REJECT_COLUMNS) - {name.upper() for name in existing}
    if missing:
        raise HandlerError(
            f"{selection.entry.table}: missing {sorted(missing)}; expected the package reject "
            "ledger; restore its audit shape or move the team-owned table out of the reserved "
            "__rejects path before erasing"
        )
    return tuple(column for column in selection.columns if column in existing)


def count_or_delete(
    warehouse: Engine,
    dialect: WarehouseDialect,
    selection: ErasureSelection,
    *,
    dry_run: bool,
) -> int | None:
    """Commit one supported row deletion; never emulate DELETE with a rewrite."""
    entry = selection.entry
    table, value = entry.table, entry.value
    selected = selection_columns(warehouse, dialect, selection)
    if not selected:
        return None
    try:
        with warehouse.begin() as conn:
            native = dialect.erasure_table(conn, table)
            target = ".".join(
                quote_output_key(p, dialect.sqlglot_dialect) for p in native.split(".")
            )
            types = dialect.full_column_types(conn, dialect.erasure_metadata_table(native))
            missing = {column.lower() for column in selected} - types.keys()
            if missing:
                raise HandlerError(
                    f"{table}: missing type metadata for {sorted(missing)}; expected complete "
                    "column types; restore the warehouse metadata and retry erasure"
                )
            predicate = " OR ".join(
                f"{quote_output_key(column, dialect.sqlglot_dialect)}="
                f"CAST(:erasure_value AS {types[column.lower()]})"
                for column in selected
            )
            count = int(
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {target} WHERE {predicate}"),
                    {"erasure_value": value},
                ).scalar_one()
            )
            if not dry_run:
                conn.execute(
                    text(f"DELETE FROM {target} WHERE {predicate}"),
                    {"erasure_value": value},
                )
            return count
    except SQLAlchemyError as error:
        raise HandlerError(
            f"{table} columns {selected}, entry {entry.key_hmac}: "
            f"row-level deletion failed ({type(error).__name__}); "
            "expected a table supporting "
            "transactional DELETE (Iceberg format version 2 or later); correct the table's "
            "format/permissions or restore its connection and retry erasure. "
            "Parameters are withheld"
        ) from None


def column_identity(value: str, dialect: WarehouseDialect) -> str:
    """Accept exactly one SQL identifier and use native identifier normalization."""
    try:
        column = parse_one(value, read=dialect.sqlglot_dialect, into=exp.Identifier)
        if not isinstance(column, exp.Identifier) or column.comments:
            raise HandlerError("erasure column: expected one identifier; correct --column")
        return Dialect.get_or_raise(dialect.sqlglot_dialect).normalize_identifier(column).name
    except SqlglotError:
        raise HandlerError(
            f"column {value!r}: expected one SQL identifier; correct --column"
        ) from None


def resolved_column(
    warehouse: Engine, dialect: WarehouseDialect, table: str, column: str, *, lineage: bool = False
) -> str:
    """Resolve physical labels, refusing ambiguous case-folded lineage rather than guessing."""
    language = Dialect.get_or_raise(dialect.sqlglot_dialect)
    found = columns(warehouse, dialect, table)
    matches = [
        name
        for name in found
        if (
            name.lower() == column.lower()
            if lineage
            else language.normalize_identifier(exp.to_identifier(name, quoted=True)).name == column
        )
    ]
    if len(matches) != 1:
        raise HandlerError(
            f"{table}.{column}: found {len(matches)} matching columns; expected one existing, "
            "unambiguous warehouse column; correct --table/--column, create the table, or "
            "give case-distinct columns unique aliases before erasing"
        )
    return matches[0]
