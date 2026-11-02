"""Bound identifier equality and row-level DELETE without exposing parameter values."""

from dataclasses import dataclass

from sqlalchemy.engine import Connection, Engine
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


@dataclass(frozen=True)
class ErasureDelete:
    """Resolved SQL and physical columns; the personal key remains a bound parameter."""

    target: str
    native: str
    predicate: str
    types: dict[str, str]

    @property
    def count(self) -> str:
        """Count the exact deletion predicate without materializing personal values."""
        return f"SELECT COUNT(*) FROM {self.target} WHERE {self.predicate}"

    def hashes(self, expression: str) -> str:
        """Project only the typed business-key fingerprint of each affected row."""
        return (
            f"SELECT DISTINCT {expression} AS key_hash FROM {self.target} t WHERE {self.predicate}"
        )

    def fully_selected_hashes(
        self, expression: str, keys: tuple[str, ...], dialect: WarehouseDialect
    ) -> str:
        """Identify business keys whose every physical version is being erased."""
        match = " AND ".join(
            f"other.{quote_output_key(c, dialect.sqlglot_dialect)} IS NOT DISTINCT FROM "
            f"t.{quote_output_key(c, dialect.sqlglot_dialect)}"
            for c in keys
        )
        return (
            self.hashes(expression) + f" AND NOT EXISTS (SELECT 1 FROM {self.target} other "
            f"WHERE {match} AND ({self.predicate}) IS NOT TRUE)"
        )

    def statement(self, keys: tuple[str, ...], dialect: WarehouseDialect, conn: Connection) -> str:
        """One MERGE deletes the selected keys, with PostgreSQL's pre-15 DELETE fallback."""
        from etl_craft.dialects.warehouse.merges import delete_merge

        if not dialect.supports_insert_merge(conn):
            return f"DELETE FROM {self.target} WHERE {self.predicate}"
        quoted = tuple(quote_output_key(c, dialect.sqlglot_dialect) for c in keys)
        source = f"(SELECT DISTINCT {', '.join(quoted)} FROM {self.target} WHERE {self.predicate})"
        return delete_merge(self.target, source, quoted, null_safe=True)


def deletion_plan(
    conn: Connection, dialect: WarehouseDialect, table: str, selected: tuple[str, ...]
) -> ErasureDelete:
    """Resolve a case-aware predicate using only declared types and quoted identifiers."""
    native = dialect.erasure_table(conn, table)
    target = ".".join(quote_output_key(p, dialect.sqlglot_dialect) for p in native.split("."))
    types = dialect.full_column_types(conn, dialect.erasure_metadata_table(native))
    missing = {column.lower() for column in selected} - types.keys()
    if missing:
        raise HandlerError(
            f"{table}: missing type metadata for {sorted(missing)}; "
            "expected complete column types; restore warehouse "
            "metadata and retry erasure"
        )
    predicate = " OR ".join(
        f"{quote_output_key(column, dialect.sqlglot_dialect)}=CAST(:erasure_value "
        f"AS {types[column.lower()]})"
        for column in selected
    )
    return ErasureDelete(target, native, f"({predicate})", types)


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
