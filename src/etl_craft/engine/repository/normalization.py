"""Warehouse object identities, normalized with the warehouse dialect's identifier rules."""

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

ObjectIdentity = tuple[str | None, str, str]


def object_identity(value: str, catalog: str | None, dialect: str | None) -> ObjectIdentity:
    """Resolve exactly two or three identifier components using warehouse case rules."""
    try:
        table = parse_one(value, into=exp.Table, read=dialect)
        if (
            not isinstance(table, exp.Table)
            or not table.db
            or len(table.parts) not in (2, 3)
            or not all(isinstance(part, exp.Identifier) and part.name for part in table.parts)
            or any(node.comments for node in table.walk())
        ):
            raise ValueError
        if not table.catalog and catalog is not None:
            table.set("catalog", exp.to_identifier(catalog))
        normalized = normalize_identifiers(table, dialect=dialect)
        return normalized.catalog or None, normalized.db, normalized.name
    except (SqlglotError, ValueError):
        raise ValueError(
            f"object reference {value!r}: expected schema.table or catalog.schema.table "
            "with exactly two or three SQL identifiers; separate catalog, schema and table "
            "components and quote identifiers containing dots; remove SQL or comments"
        ) from None
