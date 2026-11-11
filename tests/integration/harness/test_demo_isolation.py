"""Concurrent installed demos own their Iceberg namespaces and clean only those namespaces."""

import json
import urllib.request

import pytest
from sqlalchemy import text

from etl_craft.warehouse.connection import warehouse_dialect
from fixtures.demo import PASSWORD_VAR, S3_VAR, SCHEMAS, Demo
from fixtures.services import MINIO_PASSWORD, POSTGRES_PASSWORD, require

pytestmark = pytest.mark.harness


@pytest.mark.parametrize("warehouse", ["duckdb_iceberg", "trino_iceberg"])
def test_building_and_closing_another_demo_cannot_remove_the_first_demos_rows(
    tmp_path, monkeypatch, warehouse
):
    monkeypatch.setenv(PASSWORD_VAR, POSTGRES_PASSWORD)
    monkeypatch.setenv(S3_VAR, MINIO_PASSWORD)
    first = Demo(tmp_path / "cli", tmp_path / "first", "sqlite", warehouse)
    second = Demo(tmp_path / "cli", tmp_path / "second", "sqlite", warehouse)
    try:
        first.build()
        with first.warehouse() as engine, engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE {first.table('lnd.probe')} AS SELECT 1 AS id"))
            if warehouse_dialect(first.config).views:
                conn.execute(text(f"CREATE VIEW {first.table('lnd.probe_view')} AS SELECT 1 AS id"))
        second.build()
        assert first.rows("SELECT id AS id FROM {c}.lnd.probe") == [(1,)]
        with second.warehouse() as engine, engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE {second.table('lnd.probe')} AS SELECT 2 AS id"))
            if warehouse_dialect(second.config).views:
                conn.execute(
                    text(f"CREATE VIEW {second.table('lnd.probe_view')} AS SELECT 2 AS id")
                )
        assert second.rows("SELECT id AS id FROM {c}.lnd.probe") == [(2,)]
        second.close()
        assert first.rows("SELECT id AS id FROM {c}.lnd.probe") == [(1,)]
        if warehouse_dialect(first.config).views:
            assert first.rows("SELECT id AS id FROM {c}.lnd.probe_view") == [(1,)]
    finally:
        second.close()
        first.close()
    catalog = require("iceberg_rest")
    with urllib.request.urlopen(f"{catalog.http_url}/v1/namespaces", timeout=10) as reply:
        namespaces = {tuple(name) for name in json.load(reply)["namespaces"]}
    owned = {(f"{demo.prefix}{schema}",) for demo in (first, second) for schema in SCHEMAS}
    assert not namespaces & owned
