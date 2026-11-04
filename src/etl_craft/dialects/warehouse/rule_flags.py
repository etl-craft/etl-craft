"""Render recorded text keys as a typed, empty-safe dialect subquery."""

from collections.abc import Sequence

from sqlglot import exp

from etl_craft.core.errors import SqlGuardError
from etl_craft.core.rule_flags import KEY_CAP
from etl_craft.dialects.warehouse.base import WarehouseDialect


def key_set(dialect: WarehouseDialect, keys: Sequence[str]) -> str:
    """Keep warehouse-controlled keys literal, never raw SQL or bind names."""
    if len(keys) > KEY_CAP:
        raise SqlGuardError(
            f"rule_flags key count {len(keys)} exceeds cap {KEY_CAP}; "
            "remedy: reduce the source batch or split it into smaller runs"
        )
    if not keys:
        return f"SELECT CAST(NULL AS {dialect.string_type}) AS rule_key WHERE 1=0"
    rows = ", ".join(
        f"(CAST({exp.Literal.string(key).sql(dialect=dialect.sqlglot_dialect)} "
        f"AS {dialect.string_type}))"
        for key in keys
    )
    return (
        f"SELECT CAST(rule_value AS {dialect.string_type}) AS rule_key "
        f"FROM (VALUES {rows}) AS rule_keys(rule_value)"
    ).replace(":", r"\:")
