"""Target state and rule results keep their rows and times as separate name components."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text

from etl_craft.engine import locks

RECORDED = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
COMBINED = {"SOURCE_OBJECT", "TARGET_OBJECT", "TARGET_TABLE"}


def rows(engine, sql):
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql))]


@pytest.mark.parametrize(
    "spelling",
    [("raw.orders", "analytics"), ("analytics.raw.orders", "other"), ("ANALYTICS.Raw.ORDERS", "")],
)
def test_one_target_takes_one_lock_however_its_name_is_written(engine_db, spelling):
    assert locks.target(*spelling).key == locks.target("raw.orders", "analytics").key


def combined_name_columns(engine):
    tables = inspect(engine).get_table_names()
    return sorted(
        f"{table.upper()}.{column['name'].upper()}"
        for table in tables
        if not (table.upper().startswith("AUD_CFG_") and table.upper().endswith("_HISTORY"))
        for column in inspect(engine).get_columns(table)
        if column["name"].upper() in COMBINED
    )


def test_no_table_outside_the_config_histories_stores_a_combined_object_name(engine_db):
    assert combined_name_columns(engine_db.engine) == []
