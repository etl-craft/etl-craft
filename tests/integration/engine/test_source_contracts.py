"""Scoped source contracts preserve identities, evidence and historical exports."""

import csv

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from etl_craft.engine import migrations
from etl_craft.services.config_files import export_config, read_config_files, sync_config
from fixtures.metadata import add_source_column


def test_retirement_reserves_name_but_releases_active_ordinal(engine_db):
    db = engine_db
    with db.engine.begin() as conn:
        column_id = add_source_column(conn, "raw.orders", "id", "INT", 1)
        conn.execute(
            text("UPDATE CFG_COLUMNS SET ACTIVE_FLAG='N' WHERE COLUMN_ID=:id"), {"id": column_id}
        )
        add_source_column(conn, "raw.orders", "replacement", "INT", 1)
    with pytest.raises(IntegrityError), db.engine.begin() as conn:
        add_source_column(conn, "raw.orders", "id", "INT", 2)
    with pytest.raises(IntegrityError), db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CFG_TABLES (SCHEMA_NAME,TABLE_NAME,ACTIVE_FLAG) "
                "VALUES ('raw','orders','N')"
            )
        )
    with pytest.raises(IntegrityError), db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CFG_COLUMNS (TABLE_ID,COLUMN_NAME,DATA_TYPE,COLUMN_POSITION) "
                "VALUES (-1,'id','INT',1)"
            )
        )


def test_catalog_resolution_round_trip_keeps_parent_and_column_ids(
    engine_db, tmp_path, monkeypatch
):
    from etl_craft.engine.repository.source_columns import fetch_source_columns

    db = engine_db
    with db.engine.begin() as conn:
        column_id = add_source_column(conn, "raw.orders", "id", "INT", 1)
        table_id = conn.execute(text("SELECT TABLE_ID FROM CFG_TABLES")).scalar_one()
        definitions = fetch_source_columns(conn)
    monkeypatch.setattr(
        "etl_craft.services.lineage.dialect_and_catalog", lambda config: ("duckdb", "analytics")
    )
    monkeypatch.setattr("etl_craft.services.config_export.seed_sources", lambda *args: definitions)
    folder = tmp_path / "resolved"
    export_config(db.engine, folder, config=db.config)
    tables = list(csv.DictReader((folder / "tables.csv").open()))
    assert len(tables) == 1 and tables[0]["CATALOG_NAME"] == "analytics"
    files = read_config_files(folder)
    planned = sync_config(db.engine, db.config, files, apply=False)
    assert len(planned.changes) == 1 and planned.changes[0].columns[0].column == "CATALOG_NAME"
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT CATALOG_NAME FROM CFG_TABLES")).scalar_one() is None
    done = sync_config(db.engine, db.config, files, apply=True)
    assert done.applied and not done.failed
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT TABLE_ID,CATALOG_NAME FROM CFG_TABLES")).one() == (
            table_id,
            "analytics",
        )
        assert conn.execute(text("SELECT COLUMN_ID,TABLE_ID FROM CFG_COLUMNS")).one() == (
            column_id,
            table_id,
        )
    assert not sync_config(db.engine, db.config, files, apply=False).changes


def test_project_source_resolution_is_audited_before_commit(engine_db, tmp_path):
    db = engine_db
    with db.engine.begin() as conn:
        migrations.mark_packaged_migrations_applied(conn)
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_source.sql").write_text(
        "INSERT INTO CFG_TABLES (SCHEMA_NAME,TABLE_NAME) VALUES ('raw','orders');\n"
        "INSERT INTO CFG_COLUMNS (TABLE_ID,COLUMN_NAME,DATA_TYPE,COLUMN_POSITION) "
        "SELECT TABLE_ID,'id','INT',1 FROM CFG_TABLES WHERE TABLE_NAME='orders';\n"
    )
    migrations.apply_pending_migrations(
        db.engine, folder, catalog="analytics", warehouse_dialect="duckdb"
    )
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT CATALOG_NAME FROM CFG_TABLES")).scalar_one() == "analytics"
        assert (
            conn.execute(
                text("SELECT MIGRATION FROM AUD_CFG_TABLES_HISTORY WHERE CURRENT_FLAG='Y'")
            ).scalar_one()
            == "0001_source.sql"
        )
