"""ROW_IDs come from the writing task run: unique after replaces, drops, deletes and retries."""

import multiprocessing
from dataclasses import replace

import pytest
from sqlalchemy import text

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
        rows = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('events')}")
        assert sorted(row[0] for row in rows) == [0, 1, 2, 3, 4]
        assert_owned(rows)
    finally:
        release.set()
        for process in processes:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(5)
        results.close()


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


SPAN = 2**32


def assert_owned(rows):
    """Each (…, row_id, task_run_id) row's ID is in its task run's range, and no ID repeats."""
    ids = [row[-2] for row in rows]
    assert len(ids) == len(set(ids)), ids
    for row in rows:
        assert row[-2] // SPAN == row[-1] and row[-2] % SPAN > 0, row


def test_replace_then_append_never_reuses_an_id(sql_world, caplog):
    w = sql_world
    w.setup("events", "SELECT 0 AS id", "OVERWRITE_TABLE")
    replace = {"SQL_ACTION": "OVERWRITE_TABLE", "TARGET_OBJECT": "events"}
    w.run("replace_first", SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id", **replace)
    first = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('events')}")
    assert_owned(first)
    w.run("replace_second", SELECT_QUERY="SELECT 3 AS id", **replace)
    second = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('events')}")
    assert_owned(second)
    assert not {row[1] for row in first} & {row[1] for row in second}
    w.setup("appends", "SELECT 0 AS id", "APPEND_TABLE")
    append = {"SQL_ACTION": "APPEND_TABLE", "TARGET_OBJECT": "appends"}
    w.run("load_first", SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id", **append)
    removed = {row[0] for row in w.rows(f"SELECT row_id FROM {w.name('appends')}")}
    w.run(
        "remove_first",
        SQL_ACTION="DELETE_ROWS",
        TARGET_OBJECT="appends",
        HARD_DELETE="true",
        MERGE_KEY="id",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2 AS id",
    )
    with caplog.at_level("INFO", logger="etl_craft.handlers.sql.session"):
        w.run("load_second", SELECT_QUERY="SELECT 3 AS id", **append)
    rows = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('appends')}")
    assert [row[0] for row in rows] == [3] and rows[0][1] not in removed
    assert_owned(rows)
    assert f"ROW_ID {rows[0][1]} to {rows[0][1]} for 1 row(s)" in caplog.text


@pytest.mark.parametrize("setup", [False, True])
def test_drop_and_recreate_never_reuse_an_id(sql_world, setup):
    w = sql_world
    w.run(
        "make",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="scratch",
        SELECT_QUERY="SELECT 1 AS id UNION ALL SELECT 2",
    )
    before = {row[0] for row in w.rows(f"SELECT row_id FROM {w.name('scratch')}")}
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
    rows = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('scratch')}")
    assert [row[0] for row in rows] == [3] and rows[0][1] not in before
    assert_owned(rows)


def test_delete_then_append_continues_after_rows_it_did_not_write(sql_world):
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
    rows = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('older')}")
    assert [row[0] for row in rows] == [3] and rows[0][1] % SPAN == 1
    assert_owned(rows)


def test_scd2_numbers_only_successors(sql_world):
    w = sql_world
    w.setup("numbered_scd2", "SELECT 1 AS id, 10 AS value", "SCD2_MERGE")
    params = {
        "SQL_ACTION": "SCD2_MERGE",
        "TARGET_OBJECT": "numbered_scd2",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "value",
    }
    w.run("initial", SELECT_QUERY="SELECT 1 AS id, 10 AS value", **params)
    (first,) = w.rows(f"SELECT row_id FROM {w.name('numbered_scd2')}")
    w.run("change", SELECT_QUERY="SELECT 1 AS id, 20 AS value UNION ALL SELECT 2, 30", **params)
    (retired,) = w.rows(f"SELECT row_id FROM {w.name('numbered_scd2')} WHERE active_flag='N'")
    assert retired == first
    active = w.rows(
        f"SELECT id, row_id, task_run_id FROM {w.name('numbered_scd2')} WHERE active_flag='Y'"
    )
    assert sorted(row[1] % SPAN for row in active) == [1, 2]
    assert_owned(active)


def test_a_retry_after_a_committed_merge_numbers_after_its_own_rows(sql_world):
    w = sql_world
    w.setup("merged", "SELECT 1 AS id, 10 AS value", "SCD1_MERGE")
    params = {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": "merged",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "value",
    }
    # The same task run writes twice, as a retry does after its first write committed.
    w.run("merge", SELECT_QUERY="SELECT 1 AS id, 10 AS value", **params)
    w.run("merge", SELECT_QUERY="SELECT 1 AS id, 10 AS value UNION ALL SELECT 2, 20", **params)
    rows = w.rows(f"SELECT id, row_id, task_run_id FROM {w.name('merged')} ORDER BY id")
    assert [(row[0], row[1] % SPAN) for row in rows] == [(1, 1), (2, 2)]
    assert_owned(rows)
