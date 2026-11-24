"""The exact Python files included in the guide run against a DuckDB warehouse."""

import importlib.util
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text

from etl_craft.config import parse_config
from etl_craft.scripting import ScriptTask

pytestmark = pytest.mark.docs
ROOT = Path(__file__).resolve().parents[3]


def test_python_contract_examples(tmp_path):
    config = parse_config(
        {
            "Secrets": {"Source_type": "ENVIRONMENT"},
            "Orchestration": {"Project": "default"},
            "Engine": {"dev": {"Jdbc_url": "jdbc:sqlite:engine.db", "Schema": "main"}},
            "Warehouse": {
                "dev": {
                    "Jdbc_url": f"jdbc:duckdb:{tmp_path / 'warehouse.duckdb'}",
                    "Schema": "main",
                }
            },
        },
        tmp_path / "craft-connector.yml",
    )
    task = ScriptTask(
        pipeline_code="EXAMPLE",
        task_code="load",
        pipeline_run_id=2,
        pipeline_id=1,
        task_run_id=3,
        refresh_type="INCREMENTAL",
        offset=None,
        input_params={},
        task_params={},
        force=False,
        config=config,
        logger=logging.getLogger("example"),
    )
    with task.warehouse() as engine, engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE main.orders (id INTEGER PRIMARY KEY, amount INTEGER, "
                "pipeline_id BIGINT, pipeline_run_id BIGINT, task_run_id BIGINT)"
            )
        )
    (tmp_path / "orders.json").write_text(
        json.dumps([{"id": 1, "amount": 7}, {"id": 2, "amount": 9}])
    )
    scripts = {}
    guide = (ROOT / "docs/guides/python-scripts.md").read_text()
    for name in ("contract_ingestion", "contract_warehouse"):
        relative = f"docs/examples/python_scripts/{name}.py"
        assert f'--8<-- "{relative}"' in guide
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        scripts[name] = module.run
    result = scripts["contract_ingestion"](task)
    assert result.row_count == 2
    assert result.offset.value == 2
    # A replay after warehouse commit but before Engine success must not double rows.
    scripts["contract_ingestion"](task)
    empty = scripts["contract_ingestion"](replace(task, offset=result.offset))
    assert empty.row_count == 0
    assert empty.offset is None
    summary = scripts["contract_warehouse"](replace(task, task_code="summary", offset=None))
    assert summary.variables == {"orders": 2, "amount": 16}
    assert summary.row_count is None
    assert summary.offset is None
    with task.warehouse() as engine, engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM main.orders ORDER BY id")).mappings().all()
    assert all(
        (row["pipeline_id"], row["pipeline_run_id"], row["task_run_id"]) == (1, 2, 3)
        for row in rows
    )
