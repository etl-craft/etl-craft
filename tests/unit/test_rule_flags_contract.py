"""Rule flag scopes are explicit and warehouse values cannot become SQL syntax."""

import pytest
from sqlglot import parse_one

from etl_craft.core.errors import SqlGuardError
from etl_craft.core.rule_flags import parse_scopes, replace_scopes
from etl_craft.dialects.warehouse import for_key
from etl_craft.dialects.warehouse.rule_flags import key_set

pytestmark = pytest.mark.unit


def test_explicit_types_and_protected_text():
    sql = (
        "SELECT '$$rule_flags(no)' AS note FROM x WHERE k NOT IN "
        "($$rule_flags(check, REJECT, INCOMPLETE)) -- $$rule_flags(no)"
    )
    scopes = parse_scopes(sql)
    assert len(scopes) == 1
    assert scopes[0].task == "check"
    assert scopes[0].types == ("REJECT", "INCOMPLETE")
    expanded = replace_scopes(sql, lambda scope: "SELECT CAST(NULL AS VARCHAR) WHERE 1=0")
    assert "'$$rule_flags(no)'" in expanded
    assert "NOT IN (SELECT CAST(NULL AS VARCHAR) WHERE 1=0)" in expanded


@pytest.mark.parametrize(
    "token",
    [
        "$$rule_flags(check)",
        "$$rule_flags(check, BAD)",
        "$$rule_flags(check, REJECT, REJECT)",
        "$$rule_flags(check, REJECT",
        "$$rule_flags(../check, REJECT)",
    ],
)
def test_bad_scope_is_refused(token):
    with pytest.raises(SqlGuardError, match=r"rule_flags.*expected.*remedy"):
        parse_scopes("SELECT k FROM x WHERE k IN (" + token)


@pytest.mark.parametrize(
    "dialect", ["duckdb", "postgres", "trino_iceberg", "duckdb_iceberg", "snowflake", "databricks"]
)
def test_keys_are_typed_dialect_literals(dialect):
    d = for_key(dialect)
    values = ("quote'\\backslash; DROP TABLE victim--", "é😀", "x" * 4096, ":bound")
    sql = key_set(d, values)
    tree = parse_one(sql, read=d.sqlglot_dialect)
    assert tree is not None
    assert key_set(d, ()) == f"SELECT CAST(NULL AS {d.string_type}) AS rule_key WHERE 1=0"
    assert "rule_key" in sql


def test_never_truncates_at_cap():
    with pytest.raises(SqlGuardError, match=r"10001.*10000.*remedy"):
        key_set(for_key("duckdb"), tuple(str(x) for x in range(10001)))


@pytest.mark.parametrize("vendor", ["Snowflake", "Databricks"])
def test_generated_hostile_keys_remain_one_managed_select(vendor, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "test-only")
    from etl_craft.config import parse_config
    from etl_craft.handlers.sql.spec import resolve_select
    from etl_craft.warehouse.connection import warehouse_dialect

    config = parse_config(
        {
            "Secrets": {"Source_type": "ENVIRONMENT"},
            "Engine": {"dev": {"Jdbc_url": "jdbc:sqlite:engine.db", "Schema": "main"}},
            "Warehouse": {
                "Name": vendor,
                "dev": {
                    "Jdbc_url": "jdbc:"
                    + (
                        "snowflake://account.snowflakecomputing.com/?db=test&schema=test&warehouse=test&role=test"
                        if vendor == "Snowflake"
                        else "databricks://host:443/default;httpPath=/sql/1.0/warehouses/test;ConnCatalog=test;ConnSchema=test"
                    ),
                    "Schema": "test",
                    "Auth_mode": "TOKEN",
                    "Secret": "TEST_TOKEN",
                    "User": "test",
                },
            },
        },
        tmp_path / "craft-connector.yml",
    )
    sql = key_set(warehouse_dialect(config), ("quote'\\backslash; DROP TABLE victim--",))
    assert resolve_select(config, {"SELECT_QUERY": sql}, pipeline_run_id=1, refresh_type="FULL")[0]
