"""Destination-native casts for declared reference values."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def cast_value(conn: Connection, kind: str, value: object) -> object:
    """Cast using a type already parsed as a warehouse DataType."""
    if value is None:
        return conn.execute(text(f"SELECT CAST(NULL AS {kind})")).scalar_one()
    return conn.execute(text(f"SELECT CAST(:value AS {kind})"), {"value": value}).scalar_one()
