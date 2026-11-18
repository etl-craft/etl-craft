"""Both SCD actions retain audit stamps and enforce live/deleted state."""

import pytest
from sqlalchemy import text

from etl_craft.core.errors import HandlerError
from fixtures.metadata import add_pipeline, add_task
from fixtures.scd_lifecycle import check_scd_lifecycle
from fixtures.sql_appends import adopt


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_scd_lifecycle(sql_world, kind):
    check_scd_lifecycle(sql_world, "lifecycle", kind)


def test_setup_and_adoption_refuse_mixed_scd_lifecycles(sql_world):
    w = sql_world
    for kind in ("SCD1_MERGE", "SCD2_MERGE"):
        w.task(
            kind,
            SQL_ACTION=kind,
            TARGET_OBJECT="mixed",
            SELECT_QUERY="SELECT 1 AS id",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="id",
        )
    with pytest.raises(HandlerError, match="different row lifecycles"):
        w.setup("mixed", "SELECT 1 AS id", "SCD1_MERGE")
    with pytest.raises(HandlerError, match="exactly one"):
        adopt(w, "mixed")
    assert "mixed" not in w.tables()


def test_merge_refuses_opposite_writer_in_another_pipeline_with_a_qualified_alias(sql_world):
    w = sql_world
    source = "SELECT 1 AS id, CAST('Ann' AS VARCHAR(20)) AS name"
    w.setup("shared", source, "SCD1_MERGE")
    with w.engine_db.begin() as conn:
        pipeline = add_pipeline(conn, "OTHER")
        other = add_task(
            conn,
            pipeline,
            "other",
            "SQL",
            SQL_ACTION="SCD2_MERGE",
            TARGET_OBJECT=w.name("shared"),
            SELECT_QUERY=source,
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
        )
    params = {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": "shared",
        "SELECT_QUERY": source,
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    with pytest.raises(HandlerError, match="conflicts with an active SCD2_MERGE writer"):
        w.run("load", **params)
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('shared')}") == [(0,)]
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG = 'N' WHERE TASK_ID = :id"), {"id": other}
        )
    assert w.run("load", **params).insert_count == 1
