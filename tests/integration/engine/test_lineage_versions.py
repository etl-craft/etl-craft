"""Lineage version history is append-only and documented on both Engine DBs."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl_craft.services.lineage import collect
from fixtures.metadata import add_pipeline, add_task


def test_table_versions_and_edges_cannot_be_rewritten(engine_db):
    db = engine_db
    with db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(
            conn,
            pipeline,
            "load",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="stage.output",
            SELECT_QUERY="SELECT id FROM raw.input",
        )
    collect(db.engine, db.config)
    for sql in (
        "UPDATE AUD_LINEAGE_VERSIONS SET EDGES_HASH='rewritten'",
        "UPDATE AUD_LINEAGE_VERSIONS SET VERSION_NUMBER=2",
        "DELETE FROM AUD_LINEAGE_VERSIONS",
        "UPDATE AUD_LINEAGE_VERSION_EDGES SET SOURCE_COLUMN='rewritten'",
        "DELETE FROM AUD_LINEAGE_VERSION_EDGES",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db.engine.begin() as conn:
            conn.execute(text(sql))
    with db.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT VERSION_NUMBER FROM AUD_LINEAGE_VERSIONS")).scalar_one() == 1
        )
        assert (
            conn.execute(text("SELECT SOURCE_COLUMN FROM AUD_LINEAGE_VERSION_EDGES")).scalar_one()
            == "id"
        )


@pytest.mark.parametrize(
    "empty_engine_db",
    [pytest.param("postgresql", marks=pytest.mark.engine_postgres)],
    indirect=True,
)
def test_postgres_lineage_tables_have_matching_descriptions(empty_engine_db):
    from fixtures.engine_db import apply_schema

    db = empty_engine_db
    apply_schema(db.engine)
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname AS table_name, "
                "obj_description(c.oid,'pg_class') AS description "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname IN "
                "('aud_column_lineage','aud_lineage_versions','aud_lineage_version_edges')"
            )
        )
        comments = {row.table_name: row.description for row in rows}
    assert comments["aud_column_lineage"] == (
        "Derived SQL task lineage cache keyed by SQL, parser version and source schemas."
    )
    assert comments["aud_lineage_versions"] == (
        "Append-only per-target table lineage versions and validity intervals."
    )
    assert comments["aud_lineage_version_edges"] == (
        "Recorded column sources and writing tasks for a table lineage version."
    )
