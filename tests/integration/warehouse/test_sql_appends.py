"""Append loads converge after exceptions and process loss on all local warehouses."""

import multiprocessing

import pytest

from etl_craft.core.errors import HandlerError
from etl_craft.warehouse.connection import warehouse_dialect
from fixtures.auth import service_token
from fixtures.engine_db import profile_block
from fixtures.lock_fencing import expire_leases
from fixtures.sql_appends import (
    adopt,
    check_append_adoption,
    check_append_retries,
    check_kept_name_collision,
    check_merge_adoption,
    create_foreign_table,
    create_target_without_task_run_id,
)
from fixtures.sql_warehouse import run_killed_sql, warehouses


def test_append_retries_replace_only_their_task_run(sql_world):
    check_append_retries(sql_world, "retry_events")


def test_killed_append_converges_when_retried(sql_world):
    w = sql_world
    w.setup("killed_events", "SELECT CAST(1 AS BIGINT) AS id", "APPEND_TABLE")
    params = {
        "SQL_ACTION": "APPEND_TABLE",
        "TARGET_OBJECT": "killed_events",
        "SELECT_QUERY": "SELECT CAST(1 AS BIGINT) AS id UNION ALL SELECT 2",
    }
    context = w.task("killed_load", **params)
    process = multiprocessing.get_context("spawn").Process(
        target=run_killed_sql, args=(context, "sql.append.after_insert")
    )
    try:
        process.start()
        process.join(60)
        assert process.exitcode == 137
        expire_leases(w.engine_db)
        result = w.run("killed_load", **params)
        assert (result.insert_count, result.target_count) == (2, 2)
        assert sorted(w.rows(f"SELECT id FROM {w.name('killed_events')}")) == [(1,), (2,)]
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_invalid_task_run_id_is_refused_before_replacing_a_batch(sql_world):
    w = sql_world
    dialect = warehouse_dialect(w.config)
    create_target_without_task_run_id(w, "invalid_load")
    w.execute(
        f"{dialect.alter_table_keyword()} {w.name('invalid_load')} ADD COLUMN TASK_RUN_ID VARCHAR"
    )
    w.task(
        "bad_load",
        SQL_ACTION="APPEND_TABLE",
        TARGET_OBJECT="invalid_load",
        SELECT_QUERY="SELECT 1 AS id",
    )
    with pytest.raises(HandlerError, match="expected BIGINT"):
        w.run(
            "bad_load",
            SQL_ACTION="APPEND_TABLE",
            TARGET_OBJECT="invalid_load",
            SELECT_QUERY="SELECT 1 AS id",
        )
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('invalid_load')}") == [(0,)]


def test_empty_retry_removes_its_old_batch(sql_world):
    w = sql_world
    w.setup("empty_retry", "SELECT CAST(1 AS BIGINT) AS id", "APPEND_TABLE")
    params = {"SQL_ACTION": "APPEND_TABLE", "TARGET_OBJECT": "empty_retry"}
    w.run("load", SELECT_QUERY="SELECT CAST(1 AS BIGINT) AS id", **params)
    result = w.run("load", SELECT_QUERY="SELECT CAST(1 AS BIGINT) AS id WHERE 1 = 0", **params)
    assert (result.insert_count, result.target_count, result.rows_written) == (0, 0, 0)


@pytest.mark.parametrize(
    "action", ["CREATE_TABLE", "OVERWRITE_TABLE", "APPEND_TABLE", "SCD1_MERGE", "SCD2_MERGE"]
)
def test_every_sql_writer_records_pipeline_and_task_run_identities(sql_world, action):
    from etl_craft.handlers import sql

    w = sql_world
    source = "SELECT CAST(1 AS BIGINT) AS id, CAST('a' AS VARCHAR(20)) AS name"
    params = {"SQL_ACTION": action, "TARGET_OBJECT": "identities", "SELECT_QUERY": source}
    if action.startswith("SCD"):
        params.update(MERGE_KEY="id", MERGE_COMPARE_COLUMNS="name")
    if action != "CREATE_TABLE":
        w.setup("identities", source, action)
    first = w.task("first_writer", **params)
    sql.run(first, w.engine_db)
    first_ids = (first.pipeline_id, first.pipeline_run_id, first.task_run_id)
    assert w.rows(
        f"SELECT pipeline_id, pipeline_run_id, task_run_id FROM {w.name('identities')}"
    ) == [first_ids]
    w.new_run()
    params["SELECT_QUERY"] = source.replace("'a'", "'b'")
    second = w.task("second_writer", **params)
    sql.run(second, w.engine_db)
    second_ids = (second.pipeline_id, second.pipeline_run_id, second.task_run_id)
    found = w.rows(f"SELECT pipeline_id, pipeline_run_id, task_run_id FROM {w.name('identities')}")
    expected = (
        [first_ids, second_ids]
        if action == "APPEND_TABLE"
        else [second_ids] * (2 if action == "SCD2_MERGE" else 1)
    )
    assert sorted(found) == sorted(expected)
    if action.startswith("SCD"):
        deleted = w.task(
            "soft_delete",
            SQL_ACTION="DELETE_ROWS",
            TARGET_OBJECT="identities",
            SELECT_QUERY="SELECT 1 AS id",
            MERGE_KEY="id",
        )
        sql.run(deleted, w.engine_db)
        assert set(
            w.rows(
                f"SELECT pipeline_id, pipeline_run_id, task_run_id FROM {w.name('identities')} "
                "WHERE delete_flag = 'Y'"
            )
        ) == {(deleted.pipeline_id, deleted.pipeline_run_id, deleted.task_run_id)}


def test_sql_input_identities_match_target_provenance(sql_world):
    from fixtures.sql_appends import check_identity_inputs

    check_identity_inputs(sql_world, "input_identities")


@warehouses("postgres")
def test_a_dropped_warehouse_connection_fails_retryable_and_the_retry_loads_once(sql_world):
    w = sql_world
    w.setup("dropped_events", "SELECT CAST(1 AS BIGINT) AS id", "APPEND_TABLE")
    w.execute(f"CREATE SEQUENCE {w.schema}.first_attempt")
    params = {
        "SQL_ACTION": "APPEND_TABLE",
        "TARGET_OBJECT": "dropped_events",
        "SELECT_QUERY": (
            "SELECT CAST(1 AS BIGINT) AS id WHERE CASE "
            f"WHEN nextval('{w.schema}.first_attempt') = 1 "
            "THEN pg_terminate_backend(pg_backend_pid()) ELSE TRUE END"
        ),
    }
    with pytest.raises(HandlerError) as dropped:
        w.run("dropped_load", **params)
    assert "terminating connection" in str(dropped.value)
    assert dropped.value.retryable
    result = w.run("dropped_load", **params)
    assert (result.insert_count, result.target_count) == (1, 1)
    assert w.rows(f"SELECT id FROM {w.name('dropped_events')}") == [(1,)]


def test_adoption_rebuilds_a_foreign_append_target_and_drops_the_original(sql_world):
    check_append_adoption(sql_world, "adopted_events")


def test_adoption_maps_merge_flags_keeps_the_original_and_merges(sql_world):
    check_merge_adoption(sql_world, "adopted_customers")


def test_adoption_refuses_a_taken_kept_name(sql_world):
    check_kept_name_collision(sql_world, "collided")


def test_adoption_needs_one_sql_writer_and_refuses_engine_assigned_columns(sql_world):
    w = sql_world
    create_foreign_table(w, "unwritten", "SELECT CAST(1 AS BIGINT) AS id")
    with pytest.raises(HandlerError, match=r"no write action; expected exactly one"):
        adopt(w, "unwritten")
    w.task("load", SQL_ACTION="APPEND_TABLE", TARGET_OBJECT="unwritten", SELECT_QUERY="SELECT 1")
    with pytest.raises(HandlerError, match=r"returns TASK_RUN_ID.*engine assigns"):
        adopt(w, "unwritten", select=f"SELECT id, 1 AS TASK_RUN_ID FROM {w.name('unwritten')}")
    assert w.columns("unwritten") == ["id"]


def test_adoption_refuses_python_script_targets(sql_world):
    from sqlalchemy import text

    w = sql_world
    create_foreign_table(w, "scripted", "SELECT CAST('old' AS VARCHAR(20)) AS name")
    context = w.task("ingest", TARGET_OBJECT="scripted")
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER = 'PYTHON' WHERE TASK_ID = :t"),
            {"t": context.task_id},
        )
    with pytest.raises(HandlerError, match=r"SQL actions only.*its own table"):
        adopt(w, "scripted")


def test_adopt_command_plans_adopts_and_records_requests(sql_world, capsys, monkeypatch):
    monkeypatch.setenv("ETL_CRAFT_TOKEN", service_token(sql_world.engine_db))
    import yaml
    from sqlalchemy import text

    from etl_craft.cli import main

    w = sql_world
    create_foreign_table(w, "cli_load", "SELECT CAST(1 AS BIGINT) AS id")
    w.task(
        "load", SQL_ACTION="APPEND_TABLE", TARGET_OBJECT="cli_load", SELECT_QUERY="SELECT 1 AS id"
    )
    profile = w.config.warehouse
    raw = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {"Project": "default"},
        "Engine": {
            "dev": {"Jdbc_url": f"jdbc:sqlite:{w.engine_db.url.database}", "Schema": "main"}
        },
        "Warehouse": {
            "Name": {
                "duckdb": "DuckDB",
                "duckdb_iceberg": "DuckDB",
                "postgres": "Postgres",
                "trino_iceberg": "Trino",
            }[w.kind],
            "Table_format": str(w.config.warehouse_table_format),
            "dev": profile_block(profile, profile.schema),
        },
    }
    path = w.config.config_path
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    args = ["adopt-target", "--config", str(path), "--target", f"{w.schema}.cli_load"]
    assert main([*args, "--dry-run"]) == 0
    assert "would adopt for APPEND_TABLE; original would be dropped" in capsys.readouterr().out
    assert "task_run_id" not in w.columns("cli_load")
    assert main(args) == 0
    assert "adopted 1 row(s) for APPEND_TABLE; original dropped" in capsys.readouterr().out
    assert main(args) == 0
    assert "already has every column APPEND_TABLE maintains" in capsys.readouterr().out
    with w.engine_db.connect() as conn:
        recorded = conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_ACTIONS WHERE COMMAND='adopt-target'")
        ).scalar_one()
    assert recorded >= 3
