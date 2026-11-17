"""Resolve configured source objects to the identities the warehouse dialect uses."""

from collections import defaultdict

from sqlalchemy.engine import Connection

from etl_craft.core.errors import MigrationError
from etl_craft.core.text import is_safe_identifier
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.normalization import ObjectIdentity, object_identity


def resolve_source_identity(
    catalog_name: str | None,
    schema_name: str,
    table_name: str,
    catalog: str | None,
    dialect: str | None,
) -> ObjectIdentity:
    """Resolve the unquoted identifier components supported by source consumers."""
    parts = [part for part in (catalog_name, schema_name, table_name) if part is not None]
    if not all(is_safe_identifier(part) for part in parts):
        raise ValueError(f"source components {parts!r}: expected separate unquoted SQL identifiers")
    return object_identity(".".join(parts), catalog, dialect)


def resolve_project_sources(
    conn: Connection, catalog: str | None, dialect: str | None
) -> list[tuple[ObjectIdentity, ObjectIdentity]]:
    """Resolve current source identities once before committing a project migration."""
    plans = []
    changes = []
    keys: dict[ObjectIdentity, list[int]] = defaultdict(list)
    for row in conn.execute(statement(conn, "source_contract_select_cfg_tables")):
        try:
            identity = resolve_source_identity(
                row.catalog_name, row.schema_name, row.table_name, catalog, dialect
            )
        except ValueError as error:
            raise MigrationError(f"CFG_TABLES TABLE_ID={row.table_id}: {error}") from error
        keys[identity].append(row.table_id)
        before = (row.catalog_name, row.schema_name, row.table_name)
        if identity != before:
            changes.append((before, identity))
            plans.append(
                dict(zip(("catalog", "schema", "table"), identity, strict=True))
                | {"id": row.table_id}
            )
    duplicates = {key: ids for key, ids in keys.items() if len(ids) > 1}
    if duplicates:
        raise MigrationError(
            f"CFG_TABLES has ambiguous resolved identities {duplicates}; "
            "use one existing parent per warehouse object"
        )
    for plan in plans:
        conn.execute(
            statement(conn, "source_contract_update_cfg_tables"),
            plan,
        )
    return changes
