"""Atomic script landing replacement on real warehouses."""

from dataclasses import replace

from sqlalchemy import text

from etl_craft.handlers.python_scripts import script_task
from etl_craft.handlers.registry import task_store
from fixtures.metadata import add_source_column


def test_landing_replaces_its_batch_and_casts_declared_columns(sql_world):
    w = sql_world
    w.setup(
        "landing",
        "SELECT CAST(NULL AS BIGINT) AS id, CAST(NULL AS VARCHAR(100)) AS name WHERE 1=0",
        "APPEND_TABLE",
    )
    context = replace(
        w.task("loader", TARGET_OBJECT=w.name("landing"), SCRIPT_KIND="INGESTION"), handler="PYTHON"
    )
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='PYTHON' WHERE TASK_ID=:id"),
            {"id": w.tasks["loader"]},
        )
        add_source_column(conn, w.name("landing"), "id", "BIGINT", 1)
        add_source_column(conn, w.name("landing"), "name", "VARCHAR(100)", 2)
    task = script_task(context, task_store(context, w.engine_db), None, {})
    assert (
        task.replace_landing(iter([{"id": "1", "name": "first'\\"}, {"id": 2, "name": "é"}])) == 2
    )
    assert w.rows(f"SELECT id,name FROM {w.name('landing')} ORDER BY id") == [
        (1, "first'\\"),
        (2, "é"),
    ]
    assert task.replace_landing(iter([{"id": 3, "name": "replacement"}])) == 1
    assert task.replace_landing(iter([{"id": 3, "name": "replacement"}])) == 1
    assert w.rows(f"SELECT id,name FROM {w.name('landing')}") == [(3, "replacement")]
    assert task.replace_landing(iter(())) == 0
    assert w.rows(f"SELECT id FROM {w.name('landing')}") == []
