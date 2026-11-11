"""Hard process loss cannot split a landing replacement or duplicate its retry."""

import pytest

from fixtures.landing_crashes import check_landing_exit, check_landing_inflight
from fixtures.sql_warehouse import warehouses


@pytest.mark.chaos
@warehouses("duckdb", "postgres", "trino_iceberg")
@pytest.mark.parametrize(
    "point", ["landing.before_publish", "landing.before_commit", "landing.after_commit"]
)
def test_killed_landing_retries_once_and_preserves_other_items(sql_world, monkeypatch, point):
    check_landing_exit(sql_world, monkeypatch, point)


@pytest.mark.chaos
@warehouses("duckdb", "postgres", "trino_iceberg")
def test_killed_during_landing_statement_preserves_other_item(sql_world, monkeypatch):
    check_landing_inflight(sql_world, monkeypatch)
