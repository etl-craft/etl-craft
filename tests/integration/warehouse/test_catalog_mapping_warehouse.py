"""The mapping parser renders the same SELECT accepted by both local SQL dialects."""

from fixtures.sql_warehouse import warehouses


@warehouses("duckdb", "postgres")
def test_mapping_operators_and_edges_use_the_executed_warehouse_select(sql_world):
    from etl_craft.handlers.lineage import extract
    from etl_craft.handlers.lineage_mapping import parse_select, steps
    from etl_craft.warehouse.connection import warehouse_dialect

    w = sql_world
    w.run(
        "source",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="source",
        SELECT_QUERY="SELECT 1 AS id, 12 AS amount",
    )
    w.run(
        "rate",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="rate",
        SELECT_QUERY="SELECT 1 AS id, 2 AS factor",
    )
    dialect = warehouse_dialect(w.config).sqlglot_dialect
    tree = parse_select(
        f"SELECT s.id, SUM(s.amount * r.factor) AS total FROM {w.name('source')} s "
        f"JOIN {w.name('rate')} r ON s.id=r.id WHERE s.amount>0 GROUP BY s.id",
        dialect,
    )
    assert w.rows(tree.sql(dialect=dialect)) == [(1, 24)]
    plan = steps(tree, dialect)
    assert {step.kind for step in plan} >= {"source", "join", "filter", "aggregate"}
    edges = extract(tree, "mart.total", dialect=dialect)
    assert any(edge.target_column == "id" and edge.transformation == "copy" for edge in edges)
    assert any(edge.source_column == "factor" and edge.target_column == "total" for edge in edges)
