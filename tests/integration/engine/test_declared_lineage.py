"""Declared lineage is validated metadata, not executable task input."""

import pytest
from sqlalchemy import text

from etl_craft.core.enums import GapAttribute
from etl_craft.services.catalog.collect import build_catalog
from etl_craft.services.catalog.document import catalog_document
from etl_craft.services.validate import validate
from fixtures.metadata import add_pipeline, add_source_column, add_task


@pytest.mark.parametrize(
    "params,expected",
    [
        (
            {"SCRIPT_KIND": "UTILITY", "LINEAGE_SOURCE": "salesforce.Account"},
            "PYTHON SCRIPT_KIND=INGESTION",
        ),
        ({"LINEAGE_COLUMNS": "Id:id"}, "LINEAGE_SOURCE=system.object"),
        (
            {"LINEAGE_SOURCE": "salesforce.Account", "LINEAGE_COLUMNS": "Id:"},
            "source_column:target_column",
        ),
        (
            {"LINEAGE_SOURCE": "salesforce.Account", "LINEAGE_COLUMNS": "Id:id|Other:ID"},
            "each target column once",
        ),
        (
            {"LINEAGE_SOURCE": "salesforce.Account", "LINEAGE_COLUMNS": "Id:missing"},
            "active column",
        ),
    ],
)
def test_validate_refuses_declared_lineage_with_object_value_and_remedy(
    engine_db, tmp_path, params, expected
):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "DECLARED")
        add_source_column(conn, "main.accounts", "id", "BIGINT", 1)
        add_task(
            conn,
            pipeline,
            "load",
            "PYTHON",
            TARGET_OBJECT="main.accounts",
            SCRIPT_FILE="load.py",
            **params,
        )
    result = validate(engine_db.engine, engine_db.config)
    findings = [
        f for f in result.findings if f.where == "DECLARED.load" and "LINEAGE_" in f.message
    ]
    assert any(expected in f.message and "expected" in f.message for f in findings)
    assert all("LINEAGE_" in f.message for f in findings)


def test_declared_columns_are_documented_not_stored_as_derived_audit(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "DECLARED")
        add_source_column(conn, "main.accounts", "id", "BIGINT", 1)
        add_task(
            conn,
            pipeline,
            "load",
            "PYTHON",
            TARGET_OBJECT="main.accounts",
            SCRIPT_FILE="load.py",
            LINEAGE_SOURCE="salesforce.Account",
            LINEAGE_COLUMNS="Id:id",
        )
    document = catalog_document(build_catalog(engine_db.engine, engine_db.config))
    task = next(t for t in document["tasks"] if t["label"] == "DECLARED.load")
    assert task["lineage"]["state"] == "declared"
    assert task["mapping"]["edges"][0]["source_column"] == "Id"
    assert task["mapping"]["edges"][0]["target_column"] == "id"
    assert not [gap for gap in document["gaps"] if gap["attribute"] == GapAttribute.LINEAGE]
    with engine_db.engine.connect() as conn:
        assert not conn.execute(text("SELECT * FROM AUD_COLUMN_LINEAGE")).first()


def test_catalog_definition_edges_keep_kinds_repairs_inactive_tasks_and_gates(engine_db):
    from fixtures.metadata import add_dependency, add_pipeline_dependency

    with engine_db.engine.begin() as conn:
        before = add_pipeline(conn, "BEFORE")
        pipeline = add_pipeline(conn, "FLOW")
        after = add_pipeline(conn, "AFTER")
        add_pipeline_dependency(conn, pipeline, before, "HAS_DATA")
        add_pipeline_dependency(conn, after, pipeline, "ALWAYS")
        target = add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="load.py")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET CONSUME_REPAIRS='N' WHERE PIPELINE_ID=:pipeline"),
            {"pipeline": pipeline},
        )
        for kind in ("SUCCESS", "FAILURE", "ALWAYS", "HAS_DATA"):
            upstream = add_task(conn, pipeline, f"source_{kind}", "PYTHON", SCRIPT_FILE="load.py")
            add_dependency(conn, pipeline, target, upstream, kind)
        add_task(conn, pipeline, "inactive", "PYTHON", SCRIPT_FILE="load.py")
        conn.execute(text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N' WHERE TASK_CODE='inactive'"))
    doc = catalog_document(build_catalog(engine_db.engine, engine_db.config))
    task = next(task for task in doc["tasks"] if task["label"] == "FLOW.load")
    assert {tuple(edge[1:]) for edge in task["upstream"]} == {
        (kind, "N") for kind in ("SUCCESS", "FAILURE", "ALWAYS", "HAS_DATA")
    }
    assert task["run_condition"] == (
        "source_SUCCESS.SUCCESS AND source_FAILURE.FAILED AND "
        "source_ALWAYS.FINISHED AND source_HAS_DATA.HAS_DATA"
    )
    inactive = next(task for task in doc["tasks"] if task["label"] == "FLOW.inactive")
    assert inactive["active_flag"] == "N"
    pipeline = next(p for p in doc["pipelines"] if p["code"] == "FLOW")
    assert pipeline["upstream"][0]["dependency_type"] == "HAS_DATA"
    assert pipeline["downstream"][0]["dependency_type"] == "ALWAYS"
    assert pipeline["gates"][0]["wait_minutes"] == engine_db.config.limits.gate_wait_minutes


@pytest.mark.parametrize("inactive", ["column", "target"])
def test_declared_target_requires_an_active_column_table_and_reference(engine_db, inactive):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ACTIVE_TARGET")
        add_source_column(conn, "main.accounts", "id", "BIGINT", 1)
        task = add_task(
            conn,
            pipeline,
            "load",
            "PYTHON",
            SCRIPT_FILE="load.py",
            TARGET_OBJECT="main.accounts",
            LINEAGE_SOURCE="salesforce.Account",
            LINEAGE_COLUMNS="Id:id",
        )
        if inactive == "column":
            conn.execute(text("UPDATE CFG_COLUMNS SET ACTIVE_FLAG='N' WHERE COLUMN_NAME='id'"))
        else:
            conn.execute(
                text("UPDATE CFG_TASKS SET TARGET_ACTIVE_FLAG='N' WHERE TASK_ID=:task"),
                {"task": task},
            )
    findings = validate(engine_db.engine, engine_db.config).findings
    assert any(
        f.where == "ACTIVE_TARGET.load"
        and "target='id'" in f.message
        and "active column" in f.message
        and "columns.csv" in f.message
        for f in findings
    )
