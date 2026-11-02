"""Reference row publication through the managed replacement implementation."""

from datetime import UTC, datetime

from sqlalchemy import text

from etl_craft.core.enums import SqlAction
from etl_craft.core.protection_state import RowProtection
from etl_craft.handlers.sql.creation import replace_select
from etl_craft.handlers.sql.protection import refuse_replacement
from etl_craft.handlers.sql.protection_columns import business_columns
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.tables import AUDIT_COLUMNS, check_column_names, declared_columns


def replace_seed(
    session: Session,
    columns: tuple[tuple[str, str], ...],
    rows: list[dict[str, object]],
    merge: tuple[SqlAction, tuple[str, ...]] | None,
    actor: str,
) -> None:
    """Prepare declared rows and the merge's audit shape, then publish atomically."""
    refuse_replacement(session)
    check_column_names(session, [name for name, _ in columns])
    stage = session.scratch("seed", persistent=True)
    declared = ", ".join(f"CAST(NULL AS {kind}) AS {name}" for name, kind in columns)
    session.create_table_as(stage, f"SELECT {declared} WHERE 1=0", step="declare the seed stage")
    if rows:
        names = ", ".join(name for name, _ in columns)
        bindings = ", ".join(":" + name for name, _ in columns)
        session.conn.execute(
            text(f"INSERT INTO {stage} ({names}) VALUES ({bindings})"),
            rows,
        )
    action = SqlAction.CREATE_TABLE if merge is None else merge[0]
    shape = declared_columns(session, columns, AUDIT_COLUMNS[action])
    projection = [name for name, _ in columns]
    values = {
        "CREATE_DATE": ":now",
        "UPDATE_DATE": ":now",
        "CREATED_BY": ":actor",
        "UPDATED_BY": ":actor",
        "ACTIVE_FLAG": "'Y'",
        "DELETE_FLAG": "'N'",
    }
    session.bindings = {"now": datetime.now(UTC), "actor": actor}
    if merge:
        session.bindings["protection_baseline"] = RowProtection(None).encoded()
        values["ETL_PROTECTION"] = ":protection_baseline"
        business = business_columns(tuple(name for name, _ in columns))
        types = {name.lower(): kind for name, kind in columns}
        values["ETL_ROW_FINGERPRINT"] = session.dialect.hash_expression(
            [*business, f"CAST(:protection_baseline AS {session.dialect.string_type})"],
            [*(types[name] for name in business), "VARCHAR"],
        )
        values["HASH_KEY"] = session.dialect.hash_expression(
            list(merge[1]),
            [{column.lower(): kind for column, kind in columns}[name] for name in merge[1]],
        )
    projection.extend(
        f"CAST({values.get(name, 'NULL')} AS {kind}) AS {name}"
        for name, kind in shape.items()
        if name not in dict(columns)
    )
    shaped = session.create_scratch(
        session.scratch("seed_shape"),
        f"SELECT {', '.join(projection)} FROM {stage}",
        step="stage the seed audit values",
    )
    replace_select(session, f"SELECT * FROM {shaped}", shape)
