"""The native catalog's provenance and SELECT mapping contract."""

from datetime import UTC, datetime

import pytest

from etl_craft.core.errors import MetadataError
from etl_craft.engine.repository.catalog import TaskRow
from etl_craft.handlers.lineage import extract
from etl_craft.services.catalog.collect import Catalog, TaskAsset
from etl_craft.services.catalog.document import catalog_document

pytestmark = pytest.mark.unit


def task(handler="SQL", **params):
    return TaskAsset(
        TaskRow(1, "P", "load", "ETL", handler, "N", None, run_condition_count=2),
        params,
        None,
        None,
        target="mart.orders",
    )


def document(asset):
    catalog = Catalog(datetime.now(UTC), {}, {"P.load": asset}, {}, {}, {}, [], [])
    return catalog_document(catalog)


@pytest.mark.parametrize(
    "handler,params,state,reason",
    [
        ("SQL", {}, "derived", None),
        ("SQL", {"SQL_ACTION": "DROP_TABLE"}, "unavailable", "no SELECT"),
        ("SQL", {"SQL_ACTION": "drop_table"}, "unavailable", "no SELECT"),
        (
            "PYTHON",
            {
                "SCRIPT_KIND": "INGESTION",
                "LINEAGE_SOURCE": "salesforce.Account",
                "LINEAGE_COLUMNS": "Id:id",
            },
            "declared",
            "doesn't verify",
        ),
        (
            "PYTHON",
            {"SCRIPT_KIND": "INGESTION", "LINEAGE_SOURCE": "s3.orders/*.csv"},
            "declared",
            "doesn't verify",
        ),
        ("PYTHON", {"SCRIPT_KIND": "INGESTION"}, "unavailable", "add it"),
        ("PYTHON", {"SCRIPT_KIND": "UTILITY"}, "unavailable", "arbitrary code"),
        ("SQL_SCRIPT", {}, "unavailable", "unmanaged"),
    ],
)
def test_shape_two_lineage_states_and_run_condition(handler, params, state, reason):
    result = document(task(handler, **params))
    assert result["schema"] == "etl-craft/catalog/2"
    found = result["tasks"][0]
    assert found["run_condition_count"] == 2
    assert found["lineage"]["state"] == state
    if reason:
        assert reason in found["lineage"]["reason"]
    assert "lineage_error" not in found
    assert not result["gaps"]


def test_select_mapping_uses_the_lineage_tree_and_engine_write_keys():
    from etl_craft.handlers.lineage_mapping import parse_select, steps

    sql = """SELECT o.id, CASE WHEN c.active THEN SUM(o.amount * r.rate) ELSE 0 END AS total
    FROM raw.orders o JOIN ref.customers c ON c.id=o.customer_id
    LEFT JOIN ref.rates r ON r.currency=o.currency WHERE o.amount>0 GROUP BY o.id,c.active"""
    tree = parse_select(sql, "postgres")
    asset = task(SQL_ACTION="SCD2_MERGE", MERGE_KEY="id", MERGE_COMPARE_COLUMNS="total")
    asset.mapping = steps(tree, "postgres")
    asset.column_edges = extract(tree, "mart.orders", dialect="postgres")
    result = document(asset)["tasks"][0]["mapping"]
    assert len([s for s in result["steps"] if s["kind"] == "join"]) == 2
    assert any("LEFT JOIN" in s["expression"] for s in result["steps"])
    assert any(s["kind"] == "filter" and "amount > 0" in s["expression"] for s in result["steps"])
    assert any(s["kind"] == "aggregate" for s in result["steps"])
    assert any(
        e["transformation"] == "copy" and e["target_column"] == "id" for e in result["edges"]
    )
    assert any("CASE" in e["transformation"] for e in result["edges"])
    assert result["write"]["managed_columns"]
    assert {key: result["write"][key] for key in ("action", "keys")} == {
        "action": "SCD2_MERGE",
        "keys": {"MERGE_KEY": "id", "MERGE_COMPARE_COLUMNS": "total"},
    }


@pytest.mark.parametrize(
    "handler,params",
    [
        ("SQL", {"LINEAGE_SOURCE": "x.y"}),
        ("PYTHON", {"SCRIPT_KIND": "UTILITY", "LINEAGE_SOURCE": "x.y"}),
        ("PYTHON", {"SCRIPT_KIND": "INGESTION", "LINEAGE_COLUMNS": "a:b"}),
        ("PYTHON", {"SCRIPT_KIND": "INGESTION", "LINEAGE_SOURCE": "bad"}),
        ("PYTHON", {"SCRIPT_KIND": "INGESTION", "LINEAGE_SOURCE": "x.y", "LINEAGE_COLUMNS": "a:"}),
        (
            "PYTHON",
            {"SCRIPT_KIND": "INGESTION", "LINEAGE_SOURCE": "x.y", "LINEAGE_COLUMNS": "a:b|c:B"},
        ),
    ],
)
def test_declared_lineage_refuses_bad_contracts_with_remedy(handler, params):
    from etl_craft.handlers.declared_lineage import columns

    with pytest.raises(MetadataError) as error:
        columns(params, handler, "P.load")
    assert all(word in str(error.value) for word in ("P.load", "LINEAGE_", "expected"))


def test_only_failed_managed_lineage_is_a_gap_and_shape_is_documented():
    from pathlib import Path

    from etl_craft.services.catalog.collect import TableAsset
    from etl_craft.services.catalog.gaps import lineage_records

    sql = task()
    sql.lineage["reason"] = "SELECT could not parse; correct SELECT_QUERY"
    utility = task("PYTHON", SCRIPT_KIND="UTILITY")
    catalog = Catalog(
        datetime.now(UTC), {}, {"P.sql": sql, "P.utility": utility}, {}, {}, {}, [], []
    )
    table = TableAsset("mart.orders", writers=["P.sql", "P.utility"])
    gaps = lineage_records(catalog, table)
    assert len(gaps) == 1 and gaps[0].tasks == ("P.sql",)
    assert "correct SELECT_QUERY" in gaps[0].reason
    reference = Path(__file__).resolve().parents[2] / "docs/reference/catalog-document.md"
    assert "etl-craft/catalog/2" in reference.read_text()


def test_unavailable_tasks_do_not_publish_derived_edges_in_shape_two():
    from etl_craft.handlers.lineage import Edge

    asset = task("SQL_SCRIPT")
    edge = Edge("mart.orders", "id", "raw.orders", "id", "copy", "P.load")
    asset.column_edges = [edge]
    catalog = Catalog(datetime.now(UTC), {}, {"P.load": asset}, {}, {}, {}, [edge], [])
    result = catalog_document(catalog)
    assert result["tasks"][0]["lineage"]["state"] == "unavailable"
    assert result["column_edges"] == []
    assert result["tasks"][0]["mapping"]["edges"] == []


def test_missing_source_schema_is_a_gap_even_without_column_edges():
    from etl_craft.services.catalog.collect import TableAsset
    from etl_craft.services.catalog.gaps import lineage_records

    asset = task()
    asset.lineage["reason"] = "source raw.orders: schema missing; declare columns and rebuild"
    asset.missing_sources = ("raw.orders",)
    catalog = Catalog(datetime.now(UTC), {}, {"P.load": asset}, {}, {}, {}, [], [])
    gaps = lineage_records(catalog, TableAsset("mart.orders", writers=["P.load"]))
    assert len(gaps) == 1
    assert gaps[0].tasks == ("P.load",)
    assert gaps[0].reason == asset.lineage["reason"]


def test_mapping_predicates_split_and_attach_once_without_splitting_or():
    from etl_craft.handlers.lineage_mapping import parse_select, steps

    sql = "SELECT a FROM raw.t WHERE a > 0 AND b = 'x' AND (c > 1 OR d < 2) AND a < b"
    stage = next(
        step for step in steps(parse_select(sql, "duckdb"), "duckdb") if step.kind == "filter"
    )
    assert len(stage.logic) == 4
    assert [row.columns for row in stage.logic] == [("a",), ("b",), (), ()]
    assert [row.expression for row in stage.logic] == [
        "a > 0",
        "b = 'x'",
        "(c > 1 OR d < 2)",
        "a < b",
    ]


def test_mapping_join_keys_group_rows_aggregate_and_having_share_the_parse():
    from etl_craft.handlers.lineage_mapping import parse_select, steps

    sql = (
        "SELECT o.id, SUM(o.amount) AS total FROM raw.orders o "
        "JOIN ref.rates r ON o.id=r.id WHERE o.amount > 0 "
        "GROUP BY o.id HAVING SUM(o.amount)>10"
    )
    stages = steps(parse_select(sql, "duckdb"), "duckdb")
    join = next(step for step in stages if step.kind == "join")
    assert join.logic[0].columns == ("o.id", "r.id")
    aggregate = next(step for step in stages if step.kind == "aggregate")
    assert any(row.label == "Group by" and row.columns == ("o.id",) for row in aggregate.logic)
    assert any(
        row.label == "Output" and "SUM(o.amount) AS total" in row.expression
        for row in aggregate.logic
    )
    assert any("SUM(o.amount) > 10" in row.expression for row in aggregate.logic)


def test_rule_predicates_use_the_checked_column_not_the_returned_row_key():
    from etl_craft.dialects.business_rules import expand_scope
    from etl_craft.handlers.lineage import trace
    from etl_craft.handlers.lineage_mapping import TraceContext
    from etl_craft.handlers.mapping_logic import rule_predicates

    traced = trace(
        expand_scope(
            "SELECT row_id FROM $$rows_in_scope WHERE amount < 0 AND (a > b OR a < 0)", "raw.orders"
        ),
        TraceContext(
            "raw.out",
            "duckdb",
            schemas={
                "raw.orders": {"row_id": "BIGINT", "amount": "BIGINT", "a": "BIGINT", "b": "BIGINT"}
            },
        ),
    )
    rows = rule_predicates(traced.tree, "duckdb")
    assert rows[0].columns == ("orders.amount",)
    assert rows[0].expression == "orders.amount < 0"
    assert rows[1].columns == ()
    assert "OR" in rows[1].expression


def test_inactive_and_drop_tasks_are_limits_not_failed_select_gaps():
    from dataclasses import replace

    from etl_craft.core.enums import YesNo
    from etl_craft.services.catalog.collect import TableAsset
    from etl_craft.services.catalog.gaps import lineage_records
    from etl_craft.services.catalog.mapping import lineage

    inactive = task()
    inactive.row = replace(inactive.row, active_flag=YesNo.NO)
    inactive.lineage = lineage(inactive)
    drop = task(SQL_ACTION="DROP_TABLE")
    drop.lineage = lineage(drop)
    catalog = Catalog(
        datetime.now(UTC), {}, {"P.inactive": inactive, "P.drop": drop}, {}, {}, {}, [], []
    )
    assert (
        lineage_records(catalog, TableAsset("mart.orders", writers=["P.inactive", "P.drop"])) == []
    )


def test_predicate_and_column_edges_share_the_same_qualified_tree(monkeypatch):
    from sqlglot import exp

    from etl_craft.handlers.lineage import table_name, trace
    from etl_craft.handlers.lineage_mapping import TraceContext, parse_select, steps

    tree = parse_select("SELECT amount FROM warehouse.raw.orders WHERE amount > 0", "duckdb")
    traced = trace(
        tree,
        TraceContext("mart.out", "duckdb", "warehouse", {"raw.orders": {"amount": "BIGINT"}}),
    )
    assert traced.tree is tree
    predicate = tree.find(exp.Where).this.find(exp.Column)
    table = tree.find(exp.Table)
    edge = traced.edges[0]

    def refuse_reparse(*args, **kwargs):
        pytest.fail("mapping must inspect the qualified trace tree, not parse another SELECT")

    import sqlglot

    from etl_craft.handlers.mapping_logic import rule_predicates

    monkeypatch.setattr(sqlglot, "parse_one", refuse_reparse)
    clause = next(stage for stage in steps(traced.tree, "duckdb") if stage.kind == "filter")
    assert rule_predicates(traced.tree, "duckdb")[0] == clause.logic[0]
    assert clause.logic[0].columns == (predicate.sql(dialect="duckdb"),)
    assert clause.logic[0].columns == (f"{table.alias_or_name}.{edge.source_column}",)
    assert table_name((table.catalog, table.db, table.name), "warehouse") == edge.source_object
    assert predicate.name == edge.source_column
