"""Both SCD actions publish complete business changes with one target MERGE."""

import pytest

from etl_craft.core.errors import HandlerError
from fixtures.single_merge import check_single_merge, target_mutations
from fixtures.sql_merges import merge_rows
from fixtures.sql_warehouse import warehouses


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_one_merge_publishes_updates_and_insertions_and_replays_nothing(sql_world, kind):
    check_single_merge(sql_world, kind)


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_a_failing_single_merge_preserves_every_existing_version(sql_world, kind):
    w = sql_world
    source = "SELECT 1 AS id,CAST('old' AS VARCHAR(20)) AS name"
    w.setup("people", source, kind)
    params = {
        "SQL_ACTION": kind,
        "TARGET_OBJECT": "people",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    w.run("seed", SELECT_QUERY=source, **params)
    before = merge_rows(w, "people")
    changed = source.replace("'old'", "'new'") + " UNION ALL SELECT 2,'add'"
    with target_mutations(w, "people", fail=True), pytest.raises(HandlerError, match="merge"):
        w.run("changed", SELECT_QUERY=changed, **params)
    assert merge_rows(w, "people") == before
    result = w.run("changed", SELECT_QUERY=changed, **params)
    assert result.update_count == 1
    assert result.insert_count == (2 if kind == "SCD2_MERGE" else 1)


def test_scd2_internal_source_columns_do_not_shadow_business_values(sql_world):
    w = sql_world
    source = (
        "SELECT 1 AS id,CAST('old' AS VARCHAR(20)) AS name,"
        "7 AS __etl_match_row_id,8 AS __etl_insert_version,9 AS __etl_new_row_id"
    )
    w.setup("collision", source, "SCD2_MERGE")
    params = {
        "SQL_ACTION": "SCD2_MERGE",
        "TARGET_OBJECT": "collision",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    w.run("seed", SELECT_QUERY=source, **params)
    changed = source.replace("'old'", "'new'")
    w.run("changed", SELECT_QUERY=changed, **params)
    rows = merge_rows(w, "collision")
    assert sorted((r["name"], r["active_flag"]) for r in rows) == [("new", "Y"), ("old", "N")]
    assert all(
        (r["__etl_match_row_id"], r["__etl_insert_version"], r["__etl_new_row_id"]) == (7, 8, 9)
        for r in rows
    )


@warehouses("postgres")
@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_pre_merge_postgres_uses_the_same_transaction_fallback(sql_world, monkeypatch, kind):
    from etl_craft.dialects.warehouse.postgres import PostgresWarehouse

    monkeypatch.setattr(PostgresWarehouse, "supports_insert_merge", lambda self, conn: False)
    from fixtures.sql_merges import check_composite_merge

    check_composite_merge(sql_world, "legacy", kind)


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_concurrent_merges_serialize_row_id_allocation_on_both_engine_dbs(
    sql_world, engine_db, kind
):
    from dataclasses import replace

    from etl_craft.handlers import sql
    from fixtures.metadata import add_pipeline, start_run
    from fixtures.races import two_at_once

    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ATOMIC")
        run_id = start_run(conn, pipeline)
    w = replace(
        sql_world,
        config=replace(sql_world.config, engine=engine_db.config.engine),
        engine_db=engine_db.engine,
        pipeline_id=pipeline,
        pipeline_run_id=run_id,
        tasks={},
    )
    shape = "SELECT 0 AS id,CAST('seed' AS VARCHAR(20)) AS name"
    w.setup("concurrent", shape, kind)
    params = {
        "SQL_ACTION": kind,
        "TARGET_OBJECT": "concurrent",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    w.run("seed", SELECT_QUERY=shape, **params)
    contexts = [
        w.task(f"writer_{number}", SELECT_QUERY=f"SELECT {number} AS id,'add' AS name", **params)
        for number in (1, 2)
    ]
    results = two_at_once(
        lambda: sql.run(contexts[0], w.engine_db),
        lambda: sql.run(contexts[1], w.engine_db),
        at="etl_craft.handlers.sql.read_sql_task",
        timeout=30,
    )
    assert all(result.insert_count == 1 for result in results)
    rows = merge_rows(w, "concurrent")
    assert sorted(row["id"] for row in rows) == [0, 1, 2]
    assert len({row["row_id"] for row in rows}) == 3
    assert all(row["active_flag"] == "Y" for row in rows)
