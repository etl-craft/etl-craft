"""Team configuration is independent of package guards, audit history and config files."""

import sqlite3
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import inspect, text

from etl_craft.core.errors import MigrationError
from etl_craft.dialects.engine.tables import CONFIG_TABLES
from etl_craft.engine import migrations
from etl_craft.services.config_files import export_config
from fixtures.engine_db import POSTGRES_PASSWORD, POSTGRES_USER
from fixtures.services import require


def external_connection(db):
    if db.engine.dialect.name == "sqlite":
        return sqlite3.connect(db.engine.url.database)
    service = require("postgres")
    connection = psycopg.connect(
        host=service.host,
        port=service.port,
        dbname=db.engine.url.database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )
    connection.execute(f'SET search_path TO "{db.config.engine.schema or "public"}"')
    connection.commit()
    return connection


@pytest.fixture
def plain(engine_db):
    connection = external_connection(engine_db)
    try:
        yield connection
    finally:
        connection.close()


def test_team_table_has_no_contract_actor_or_history(engine_db, plain, tmp_path):
    with engine_db.engine.begin() as conn:
        migrations.mark_packaged_migrations_applied(conn)
    project = tmp_path / "migrations"
    project.mkdir()
    (project / "0001_team.sql").write_text(
        "CREATE TABLE CFG_TEAM (VALUE VARCHAR); INSERT INTO CFG_TEAM VALUES ('team');"
    )
    migrations.apply_pending_migrations(engine_db.engine, project)
    plain.execute("INSERT INTO CFG_TEAM VALUES ('outside')")
    plain.execute("UPDATE CFG_TEAM SET VALUE='updated' WHERE VALUE='team'")
    plain.commit()
    with engine_db.engine.connect() as conn:
        assert {r.value for r in conn.execute(text("SELECT VALUE AS value FROM CFG_TEAM"))} == {
            "updated",
            "outside",
        }
        assert "AUD_CFG_TEAM_HISTORY" not in {t.upper() for t in inspect(conn).get_table_names()}
        assert (
            conn.execute(
                text("SELECT COUNT(*) AS n FROM AUD_METADATA_CHANGES WHERE TABLE_NAME='CFG_TEAM'")
            ).scalar_one()
            == 0
        )
    out = tmp_path / "config"
    export_config(engine_db.engine, out)
    assert not any("TEAM" in path.name.upper() for path in out.iterdir())
    with pytest.raises(
        (sqlite3.DatabaseError, psycopg.Error), match=r"written only by etl-craft|no such function"
    ):
        plain.execute(
            "INSERT INTO CFG_PIPELINES (PIPELINE_CODE,PIPELINE_NAME,REFRESH_TYPE) "
            "VALUES ('outside','outside','FULL')"
        )
    plain.rollback()


def test_a_project_audit_table_is_refused_and_its_file_rolls_back(engine_db, tmp_path):
    with engine_db.engine.begin() as conn:
        migrations.mark_packaged_migrations_applied(conn)
    project = tmp_path / "migrations"
    project.mkdir()
    (project / "0001_team.sql").write_text(
        "CREATE TABLE CFG_TEAM (VALUE VARCHAR); CREATE TABLE AUD_TEAM (VALUE VARCHAR);"
    )
    with pytest.raises(MigrationError, match=r"(?i)AUD_TEAM.*reserved.*rename"):
        migrations.apply_pending_migrations(engine_db.engine, project)
    with engine_db.engine.connect() as conn:
        assert "CFG_TEAM" not in {t.upper() for t in inspect(conn).get_table_names()}


@pytest.mark.unit
def test_package_config_manifest_matches_the_current_schema():
    import re

    root = Path(__file__).parents[3] / "src/etl_craft/dialects/engine"
    for dialect in ("sqlite", "postgres"):
        declared = set(
            re.findall(
                r"^CREATE TABLE (CFG_\w+)",
                (root / dialect / "schema.sql").read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        )
        assert declared == CONFIG_TABLES
