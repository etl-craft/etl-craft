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
