"""A full refresh re-reads from the start, stores the position it reaches, then ends."""

from dataclasses import replace

import pytest

from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import InjectedFaultError, SqlGuardError
from etl_craft.engine import transitions
from etl_craft.engine.repository.offsets import fetch_task_offset
from etl_craft.handlers import sql

SOURCE = (
    "SELECT id, name FROM (VALUES (1, 'ann'), (2, 'bob'), (3, 'cy'), (4, 'di')) AS s(id, name) "
    "WHERE id <= {last} AND id > $$watermark"
)


def merge_params(last):
    return {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": "fr_merge",
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
        "WATERMARK_COLUMN": "id",
        "WATERMARK_TYPE": "NUMBER",
        "WATERMARK_START": "0",
        "SELECT_QUERY": SOURCE.format(last=last),
    }


def run_task(w, code, params, *, full_refresh=False, empty=()):
    """Run one task of a new pipeline run to success, as a normal run or a full refresh."""
    w.new_run()
    context = w.task(code, **params)
    if full_refresh:
        context = replace(context, full_refresh=True, empty_targets=empty, refresh_type="FULL")
    result = sql.run(context, w.engine_db)
    with w.engine_db.begin() as conn:
        transitions.finish_task_run(
            conn, context.task_run_id, status=RunStatus.SUCCESS, counts=result, offset=result.offset
        )
    return context, result


def position(w, context):
    with w.engine_db.connect() as conn:
        stored = fetch_task_offset(conn, context.task_id)
    return None if stored is None else stored.offset_value


def test_a_full_refresh_reads_everything_once_and_the_next_run_is_incremental(sql_world):
    w = sql_world
    w.setup(
        "fr_merge", "SELECT CAST(1 AS BIGINT) AS id, CAST('x' AS VARCHAR(30)) AS name", "SCD1_MERGE"
    )
    context, first = run_task(w, "fr_merge_load", merge_params(2))
    assert first.source_count == 2 and position(w, context) == "2"
    # Rows 1 and 2 were corrected upstream; a normal run only reads what is newer than 2.
    _, normal = run_task(w, "fr_merge_load", merge_params(3))
    assert normal.source_count == 1 and position(w, context) == "3"
    # The full refresh reads from WATERMARK_START again, whatever the stored position.
    _, refreshed = run_task(w, "fr_merge_load", merge_params(3), full_refresh=True)
    assert refreshed.source_count == 3 and position(w, context) == "3"
    # And the run after it is incremental again: only the one new row.
    _, back = run_task(w, "fr_merge_load", merge_params(4))
    assert back.source_count == 1 and position(w, context) == "4"


def test_a_failed_full_refresh_leaves_the_stored_position_alone(sql_world):
    w = sql_world
    w.setup(
        "fr_merge", "SELECT CAST(1 AS BIGINT) AS id, CAST('x' AS VARCHAR(30)) AS name", "SCD1_MERGE"
    )
    context, _ = run_task(w, "fr_merge_load", merge_params(3))
    assert position(w, context) == "3"
    w.new_run()
    broken = {
        **merge_params(4),
        "SELECT_QUERY": "SELECT id, name FROM missing_table WHERE id > $$watermark",
    }
    refresh = replace(w.task("fr_merge_load", **broken), full_refresh=True, refresh_type="FULL")
    with pytest.raises(Exception, match=r"(?i)missing_table|not exist|catalog"):
        sql.run(refresh, w.engine_db)
    assert position(w, context) == "3"


def append_params(last):
    return {
        "SQL_ACTION": "APPEND_TABLE",
        "TARGET_OBJECT": "fr_append",
        "WATERMARK_COLUMN": "id",
        "WATERMARK_TYPE": "NUMBER",
        "WATERMARK_START": "0",
        "SELECT_QUERY": SOURCE.format(last=last),
    }


def append_count(w):
    return w.rows(f"SELECT COUNT(*) FROM {w.name('fr_append')}")[0][0]


def test_a_confirmed_append_target_is_emptied_so_the_reload_has_no_duplicates(sql_world):
    w = sql_world
    w.setup(
        "fr_append",
        "SELECT CAST(1 AS BIGINT) AS id, CAST('x' AS VARCHAR(30)) AS name",
        "APPEND_TABLE",
    )
    context, _ = run_task(w, "fr_append_load", append_params(2))
    assert append_count(w) == 2
    target = w.task("fr_append_load", **append_params(3)).task_params["TARGET_OBJECT"]
    _, refreshed = run_task(
        w, "fr_append_load", append_params(3), full_refresh=True, empty=(target,)
    )
    assert refreshed.source_count == 3 and append_count(w) == 3  # not 5
    assert position(w, context) == "3"
    # A normal run afterwards appends only what is new, and empties nothing.
    run_task(w, "fr_append_load", append_params(4))
    assert append_count(w) == 4


def test_an_append_target_nobody_confirmed_is_never_touched(sql_world):
    w = sql_world
    w.setup(
        "fr_append",
        "SELECT CAST(1 AS BIGINT) AS id, CAST('x' AS VARCHAR(30)) AS name",
        "APPEND_TABLE",
    )
    context, _ = run_task(w, "fr_append_load", append_params(2))
    w.new_run()
    refresh = replace(
        w.task("fr_append_load", **append_params(3)), full_refresh=True, empty_targets=()
    )
    with pytest.raises(SqlGuardError, match="emptying this target was not confirmed"):
        sql.run(refresh, w.engine_db)
    assert append_count(w) == 2 and position(w, context) == "2"


def test_a_retry_after_a_failure_between_the_empty_and_the_load_converges(sql_world, monkeypatch):
    w = sql_world
    w.setup(
        "fr_append",
        "SELECT CAST(1 AS BIGINT) AS id, CAST('x' AS VARCHAR(30)) AS name",
        "APPEND_TABLE",
    )
    context, _ = run_task(w, "fr_append_load", append_params(2))
    target = w.task("fr_append_load", **append_params(3)).task_params["TARGET_OBJECT"]
    w.new_run()
    refresh = replace(
        w.task("fr_append_load", **append_params(3)),
        full_refresh=True,
        empty_targets=(target,),
        refresh_type="FULL",
    )
    with monkeypatch.context() as patch:
        patch.setenv("ETL_CRAFT_FAULT", "sql.append.after_delete")
        with pytest.raises(InjectedFaultError):
            sql.run(refresh, w.engine_db)
    assert position(w, context) == "2"
    result = sql.run(refresh, w.engine_db)
    with w.engine_db.begin() as conn:
        transitions.finish_task_run(
            conn, refresh.task_run_id, status=RunStatus.SUCCESS, counts=result, offset=result.offset
        )
    assert append_count(w) == 3 and position(w, context) == "3"
