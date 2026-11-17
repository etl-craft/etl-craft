"""Native metadata labels keep quoting semantics without changing other metadata readers."""

import pytest

from etl_craft.dialects.warehouse import for_key

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("postgres", 'Catalog."Schema"."People"'),
        ("snowflake", '"Catalog"."Schema"."People"'),
        ("snowflake_iceberg", '"Catalog"."Schema"."People"'),
        ("duckdb", "Catalog.Schema.People"),
        ("duckdb_iceberg", "Catalog.Schema.People"),
        ("trino_iceberg", "Catalog.Schema.People"),
    ],
)
def test_native_metadata_lookup_preserves_resolved_case(kind, expected):
    assert for_key(kind).erasure_metadata_table("Catalog.Schema.People") == expected


@pytest.mark.parametrize(
    "key,table_format,kept_in,warehouse_bound",
    [
        ("postgres", "NATIVE", None, None),
        ("duckdb", "NATIVE", None, None),
        ("duckdb_iceberg", "ICEBERG", "Iceberg snapshots", None),
        ("trino_iceberg", "ICEBERG", "Iceberg snapshots", None),
        ("databricks", "NATIVE", "Delta table history", None),
        ("databricks_iceberg", "ICEBERG", "Delta table history", None),
        ("snowflake", "NATIVE", "Snowflake Time Travel and Fail-safe", "DATA_RETENTION"),
        ("snowflake_iceberg", "ICEBERG", "Snowflake Time Travel and Fail-safe", "DATA_RETENTION"),
    ],
)
def test_each_warehouse_names_where_erased_rows_stay_readable(
    key, table_format, kept_in, warehouse_bound
):
    from etl_craft.core.enums import TableFormat
    from etl_craft.dialects.warehouse.erasure import old_versions

    found = old_versions(for_key(key), TableFormat(table_format))
    assert (found and found.kept_in) == kept_in
    if found is not None:
        assert found.remedy
        assert (found.warehouse_bound or "").startswith(warehouse_bound or "") and bool(
            found.warehouse_bound
        ) == bool(warehouse_bound)
