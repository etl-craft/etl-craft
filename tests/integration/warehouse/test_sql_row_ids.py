"""Generated keys survive concurrent task processes and interrupted allocation."""

import multiprocessing
from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.errors import InjectedFaultError
from fixtures.business_rules import add_rule, run_rules
from fixtures.engine_db import apply_schema
from fixtures.metadata import add_dependency, add_pipeline, start_run
from fixtures.sql_row_ids import check_row_id_generation, run_paused_append
from fixtures.sql_warehouse import warehouses


def test_generated_row_ids_survive_writes_and_evolution(sql_world):
    check_row_id_generation(sql_world, "numbered")


@warehouses("trino_iceberg")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
def test_concurrent_appends_keep_row_ids_unique_across_processes(sql_world, request, engine_kind):
    w = sql_world
    if engine_kind == "postgresql":
        db = request.getfixturevalue("postgres_database")
        apply_schema(db.engine)
        w.config = replace(w.config, engine=db.config.engine)
        w.engine_db = db.engine
        with db.engine.begin() as conn:
            w.pipeline_id = add_pipeline(conn, "P", refresh_type="INCREMENTAL")
            w.pipeline_run_id = start_run(conn, w.pipeline_id)
    w.setup("events", "SELECT 1 AS id", "APPEND_TABLE")
    params = {"SQL_ACTION": "APPEND_TABLE", "TARGET_OBJECT": "events"}
    w.run("seed", SELECT_QUERY="SELECT 0 AS id", **params)
    contexts = [
        w.task("first", SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2", **params),
        w.task(
            "second",
            SELECT_QUERY="SELECT 3 AS id UNION ALL SELECT 4",
            **{**params, "TARGET_OBJECT": w.name("events").upper()},
        ),
    ]
    # Both references normalize to the same target lock; each process builds its own pools.
    spawn = multiprocessing.get_context("spawn")
    attempted = [spawn.Event(), spawn.Event()]
    allocated = [spawn.Event(), spawn.Event()]
    release = spawn.Event()
    results = spawn.Queue()
    processes = [
        spawn.Process(
            target=run_paused_append,
            args=(context, i == 0, attempted[i], allocated[i], release, results),
        )
        for i, context in enumerate(contexts)
    ]
    try:
        processes[0].start()
        assert allocated[0].wait(20), "first append never reached its allocating INSERT"
        processes[1].start()
        assert attempted[1].wait(20), "second append never attempted the target lock"
        assert not allocated[1].wait(0.3), (
            "second append reached its allocating INSERT before the first committed"
        )
        release.set()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert [results.get(timeout=5) for _ in processes] == [("ok", 2), ("ok", 2)]
        rows = w.rows(f"SELECT id, row_id FROM {w.name('events')}")
        assert sorted(row[0] for row in rows) == [0, 1, 2, 3, 4]
        assert sorted(row[1] for row in rows) == [1, 2, 3, 4, 5]
        assert {row[1] for row in rows if row[0] in {1, 2}} == {2, 3}
        assert {row[1] for row in rows if row[0] in {3, 4}} == {4, 5}
    finally:
        release.set()
        for process in processes:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(5)
        results.close()


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_failed_computed_allocation_releases_the_target_lock(sql_world, monkeypatch):
    w = sql_world
    w.setup("events", "SELECT 1 AS id", "APPEND_TABLE")

    params = {
        "SQL_ACTION": "APPEND_TABLE",
        "TARGET_OBJECT": "events",
        "SELECT_QUERY": "SELECT 1 AS id UNION ALL SELECT 2",
    }
    with monkeypatch.context() as patch:
        patch.setenv("ETL_CRAFT_FAULT", "sql.row_id.after_reserve")
        with pytest.raises(InjectedFaultError, match=r"sql\.row_id\.after_reserve"):
            w.run("load", **params)
    assert not w.rows(f"SELECT id FROM {w.name('events')}")
    assert w.run("load", **params).insert_count == 2
    assert w.rows(f"SELECT row_id FROM {w.name('events')} ORDER BY row_id") == [(3,), (4,)]


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_replacement_and_following_append_keep_computed_ids_monotonic(sql_world, caplog):
    w = sql_world
    w.setup("events", "SELECT 0 AS id", "OVERWRITE_TABLE")
    w.run(
        "replace_first",
        SQL_ACTION="OVERWRITE_TABLE",
        TARGET_OBJECT="events",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id",
    )
    (previous,) = w.rows(f"SELECT MAX(row_id) FROM {w.name('events')}")
    w.run(
        "replace_second",
        SQL_ACTION="OVERWRITE_TABLE",
        TARGET_OBJECT="events",
        SELECT_QUERY="SELECT 3 AS id",
    )
    assert w.rows(f"SELECT id, row_id FROM {w.name('events')}") == [(3, previous[0] + 1)]

    w.setup("appends", "SELECT 0 AS id", "APPEND_TABLE")
    w.run(
        "load_first",
        SQL_ACTION="APPEND_TABLE",
        TARGET_OBJECT="appends",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id",
    )
    w.run(
        "remove_first",
        SQL_ACTION="DELETE_ROWS",
        TARGET_OBJECT="appends",
        HARD_DELETE="true",
        MERGE_KEY="id",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id",
    )
    with caplog.at_level("INFO", logger="etl_craft.handlers.sql.session"):
        w.run(
            "load_second",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="appends",
            SELECT_QUERY="SELECT 3 AS id",
        )
    assert w.rows(f"SELECT id, row_id FROM {w.name('appends')}") == [(3, 3)]
    assert "reserved ROW_ID 3 to 3 for 1 row(s)" in caplog.text


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_scd2_reserves_only_successor_ids(sql_world):
    w = sql_world
    w.setup("numbered_scd2", "SELECT 1 AS id, 10 AS value", "SCD2_MERGE")
    params = {
        "SQL_ACTION": "SCD2_MERGE",
        "TARGET_OBJECT": "numbered_scd2",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "value",
    }
    w.run("initial", SELECT_QUERY="SELECT 1 AS id, 10 AS value", **params)
    w.run("change", SELECT_QUERY="SELECT 1 AS id, 20 AS value UNION ALL SELECT 2, 30", **params)
    (retired,) = w.rows(f"SELECT row_id FROM {w.name('numbered_scd2')} WHERE active_flag='N'")
    assert retired == (1,)
    assert w.rows(
        f"SELECT row_id FROM {w.name('numbered_scd2')} WHERE active_flag='Y' ORDER BY row_id"
    ) == [(2,), (3,)]
    with w.engine_db.connect() as conn:
        from etl_craft.engine.locks import target
        from etl_craft.engine.queries import statement

        saved = conn.execute(
            statement(conn, "target_row_id_high_water"),
            {"key": target(w.name("numbered_scd2"), w.catalog).key},
        ).scalar_one()
    assert saved == 3


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_replacing_stage_records_each_runs_reject_and_excludes_it(sql_world):
    from etl_craft.warehouse.connection import warehouse_dialect

    w = sql_world
    w.setup("stage", "SELECT 1 AS id, 1 AS amount", "OVERWRITE_TABLE")
    w.task("rules")
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='BUSINESS_RULES' WHERE TASK_ID=:id"),
            {"id": w.tasks["rules"]},
        )
    add_rule(
        w,
        "negative",
        "SELECT row_id FROM $$rows_in_scope WHERE amount < 0",
        key="row_id",
        target="stage",
    )
    kind = warehouse_dialect(w.config).string_type
    filtered = {
        "SQL_ACTION": "CREATE_TABLE",
        "TARGET_OBJECT": "ods",
        "SELECT_QUERY": f"SELECT id, amount FROM {w.name('stage')} "
        f"WHERE CAST(row_id AS {kind}) NOT IN ($$rule_flags(rules, REJECT))",
    }
    w.task("ods", **filtered)
    with w.engine_db.begin() as conn:
        add_dependency(conn, w.pipeline_id, w.tasks["ods"], w.tasks["rules"])
    for bad, good in [(101, 102), (201, 202)]:
        w.run(
            "replace_stage",
            SQL_ACTION="OVERWRITE_TABLE",
            TARGET_OBJECT="stage",
            SELECT_QUERY=f"SELECT {bad} AS id, -1 AS amount UNION ALL SELECT {good}, 1",
        )
        assert run_rules(w).insert_count == 1
        w.finish("rules")
        w.run("ods", **filtered)
        assert w.rows(f"SELECT id, amount FROM {w.name('ods')}") == [(good, 1)]
        w.new_run()


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_committed_duplicate_row_ids_fail_the_attempt(sql_world, monkeypatch):
    from etl_craft.core.errors import SqlGuardError
    from etl_craft.handlers.sql.session import Session

    w = sql_world
    w.setup("numbered", "SELECT 1 AS id", "APPEND_TABLE")
    original = Session.run

    def duplicate_on_insert(session, sql, params=None, *, step):
        if step == "append the SELECT's rows":
            sql = sql.replace("CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT)", "1")
        return original(session, sql, params, step=step)

    monkeypatch.setattr(Session, "run", duplicate_on_insert)
    with pytest.raises(SqlGuardError, match=r"numbered: ROW_ID reservation \[1, 2\].*IDs \[1\]"):
        w.run(
            "load",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="numbered",
            SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2",
        )
    assert w.rows(f"SELECT row_id FROM {w.name('numbered')}") == [(1,), (1,)]


@warehouses("trino_iceberg", "duckdb_iceberg")
def test_hard_delete_saves_maximum_from_unregistered_legacy_rows(sql_world):
    w = sql_world
    w.setup("older", "SELECT 1 AS id", "APPEND_TABLE")
    w.execute(f"INSERT INTO {w.name('older')} (id, row_id) VALUES (1, 40), (2, 42)")
    w.run(
        "erase_old",
        SQL_ACTION="DELETE_ROWS",
        TARGET_OBJECT="older",
        MERGE_KEY="id",
        HARD_DELETE="true",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2",
    )
    w.run(
        "load_new", SQL_ACTION="APPEND_TABLE", TARGET_OBJECT="older", SELECT_QUERY="SELECT 3 AS id"
    )
    assert w.rows(f"SELECT id, row_id FROM {w.name('older')}") == [(3, 43)]


@warehouses("trino_iceberg", "duckdb_iceberg")
@pytest.mark.parametrize("setup", [False, True])
def test_drop_and_recreate_retain_the_target_high_water(sql_world, setup):
    w = sql_world
    w.run(
        "make",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="scratch",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2",
    )
    w.finish("make")
    w.run("drop", SQL_ACTION="DROP_TABLE", TARGET_OBJECT="scratch")
    if setup:
        with w.engine_db.begin() as conn:
            w.pipeline_id = add_pipeline(conn, "RECREATE", refresh_type="INCREMENTAL")
            w.pipeline_run_id = start_run(conn, w.pipeline_id)
        w.tasks.clear()
        w.setup("scratch", "SELECT 3 AS id", "APPEND_TABLE")
        w.run(
            "append_after_drop",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="scratch",
            SELECT_QUERY="SELECT 3 AS id",
        )
    else:
        w.run(
            "recreate",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="scratch",
            SELECT_QUERY="SELECT 3 AS id",
        )
    assert w.rows(f"SELECT id, row_id FROM {w.name('scratch')}") == [(3, 3)]


@warehouses("postgres", "duckdb")
@pytest.mark.parametrize("setup", [False, True])
def test_recreating_a_legacy_target_starts_its_native_generator_above_the_floor(sql_world, setup):
    w = sql_world
    target = w.name("legacy")
    w.run("make", SQL_ACTION="CREATE_TABLE", TARGET_OBJECT="legacy", SELECT_QUERY="SELECT 1 AS id")
    w.finish("make")
    w.execute(f"DROP TABLE {target}")
    w.execute(f"CREATE TABLE {target} (id BIGINT, ROW_ID BIGINT)")
    w.execute(f"INSERT INTO {target} (id, ROW_ID) VALUES (1, 42)")
    w.run("drop", SQL_ACTION="DROP_TABLE", TARGET_OBJECT="legacy")
    if setup:
        with w.engine_db.begin() as conn:
            w.pipeline_id = add_pipeline(conn, "RECREATE", refresh_type="INCREMENTAL")
            w.pipeline_run_id = start_run(conn, w.pipeline_id)
        w.tasks.clear()
        w.setup("legacy", "SELECT 3 AS id", "APPEND_TABLE")
        w.execute(f"INSERT INTO {target} (id) VALUES (3)")
    else:
        w.run(
            "recreate",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="legacy",
            SELECT_QUERY="SELECT 3 AS id",
        )
    assert w.rows(f"SELECT id, row_id FROM {target}") == [(3, 43)]
    w.execute(f"INSERT INTO {target} (id) VALUES (4)")
    assert w.rows(f"SELECT id, row_id FROM {target} WHERE id = 4") == [(4, 44)]
