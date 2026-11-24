"""Common config contracts, safe token history and atomic Engine DB upgrades."""

from dataclasses import replace

import pytest
from sqlalchemy import DateTime, inspect, text
from sqlalchemy.exc import DBAPIError

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.text import sha256_hex
from etl_craft.core.time import as_utc
from etl_craft.engine import migrations
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.services.operations import OperationContext, tokens
from fixtures.actions import act

ALICE = Actor("alice", ActorKind.USER)
BOB = Actor("bob", ActorKind.USER)


def test_all_config_tables_have_mandatory_base_fields_and_one_key(engine_db):
    with engine_db.engine.connect() as conn:
        inspector = inspect(conn)
        for table in inspector.get_table_names():
            if not table.upper().startswith("CFG_"):
                continue
            columns = {column["name"].upper(): column for column in inspector.get_columns(table)}
            for name in ("CREATED_BY", "CREATE_DATE", "UPDATED_BY", "UPDATED_DATE", "ACTIVE_FLAG"):
                assert not columns[name]["nullable"], (table, name)
                if name.endswith("DATE"):
                    assert isinstance(columns[name]["type"], DateTime)
                    if conn.dialect.name == "postgresql":
                        assert columns[name]["type"].timezone
            assert len(inspector.get_pk_constraint(table)["constrained_columns"]) == 1


@pytest.mark.parametrize(
    "problem", ["missing", "nullable", "date_type", "no_key", "two_keys", "nullable_key"]
)
def test_team_config_tables_do_not_need_the_package_base_contract(engine_db, tmp_path, problem):
    date = "TIMESTAMPTZ" if engine_db.engine.dialect.name == "postgresql" else "TIMESTAMP"
    columns = (
        "ID BIGINT PRIMARY KEY NOT NULL, CREATED_BY VARCHAR NOT NULL, "
        f"CREATE_DATE {date} NOT NULL, UPDATED_BY VARCHAR NOT NULL, "
        f"UPDATED_DATE {date} NOT NULL, ACTIVE_FLAG VARCHAR NOT NULL"
    )
    if problem == "missing":
        columns = "ID BIGINT PRIMARY KEY"
    elif problem == "nullable":
        columns = columns.replace("CREATED_BY VARCHAR NOT NULL", "CREATED_BY VARCHAR")
    elif problem == "date_type":
        columns = columns.replace(
            f"CREATE_DATE {date}",
            "CREATE_DATE TIMESTAMP" if date == "TIMESTAMPTZ" else "CREATE_DATE VARCHAR",
        )
    elif problem == "no_key":
        columns = columns.replace(" PRIMARY KEY", "")
    elif problem == "nullable_key":
        columns = columns.replace(
            "PRIMARY KEY NOT NULL", "PRIMARY KEY" if date == "TIMESTAMP" else ""
        )
    else:
        columns = columns.replace(" PRIMARY KEY", "") + ", OTHER BIGINT, PRIMARY KEY (ID, OTHER)"
    project = tmp_path / "migrations"
    project.mkdir()
    (project / "0001_config.sql").write_text(f"CREATE TABLE CFG_PROJECT ({columns});")
    with engine_db.engine.begin() as conn:
        migrations.mark_packaged_migrations_applied(conn)
    with selected_project(1):  # the migration engine, called below `migrate`
        applied = migrations.apply_pending_migrations(engine_db.engine, project)
    assert "0001_config.sql" in applied
    with engine_db.engine.connect() as conn:
        assert "CFG_PROJECT" in {name.upper() for name in inspect(conn).get_table_names()}


def test_token_lifecycle_is_attributed_without_credentials(engine_db, monkeypatch):
    import threading

    used = threading.Event()
    original = tokens._write_use

    def write_use(*args):
        try:
            original(*args)
        finally:
            used.set()

    monkeypatch.setattr(tokens, "_write_use", write_use)
    # An earlier test's background write holds the process-wide usage slot until it ends.
    assert tokens._USAGE_SLOT.acquire(timeout=30)
    tokens._USAGE_SLOT.release()
    ctx = OperationContext(engine_db.engine, engine_db.config, ALICE, role=ApiRole.ADMIN)
    created = act(ctx, ActionName.TOKEN_CREATE, name="dashboard", role="viewer")
    assert tokens.authenticate(ctx, created.token)
    assert used.wait(5)
    with acting_as(BOB), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_API_TOKENS SET ACTIVE_FLAG='N'"))
    assert tokens.authenticate(ctx, created.token) is None
    with acting_as(BOB), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_API_TOKENS SET ACTIVE_FLAG='Y'"))
    assert tokens.authenticate(ctx, created.token)
    rotated = "rotated-token"
    with acting_as(BOB), engine_db.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_API_TOKENS SET TOKEN_SHA256=:digest"),
            {"digest": sha256_hex(rotated.encode())},
        )
    assert tokens.authenticate(ctx, created.token) is None
    assert tokens.authenticate(ctx, rotated)
    act(replace(ctx, actor=BOB), ActionName.TOKEN_REVOKE, token_id=created.metadata.token_id)
    assert tokens.authenticate(ctx, created.token) is None
    with engine_db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT CREATED_BY, CREATE_DATE, UPDATED_BY, ACTIVE_FLAG FROM CFG_API_TOKENS")
        ).one()
        assert (row[0], row[2], row[3]) == ("alice", "bob", "N")
        assert as_utc(row[1]) == created.metadata.created_at
        assert not conn.execute(
            text("SELECT 1 AS found FROM AUD_METADATA_CHANGES WHERE TABLE_NAME='CFG_API_TOKENS'")
        ).first()
    for flag in (None, "x"):
        with pytest.raises(DBAPIError), engine_db.engine.begin() as conn:
            conn.execute(text("UPDATE CFG_API_TOKENS SET ACTIVE_FLAG=:flag"), {"flag": flag})
