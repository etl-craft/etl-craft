"""Account-owned credentials and their guards on both Engine DBs."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from etl_craft.api.app import create_app
from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import UsageError
from etl_craft.services.operations import OperationContext, tokens
from fixtures.actions import act

OWNER = Actor("owner", ActorKind.USER)


def context(db):
    return OperationContext(db.engine, db.config, OWNER, role=ApiRole.ADMIN)


def test_tokens_share_current_account_role_and_disable_together(engine_db):
    ctx = context(engine_db)
    first = act(ctx, ActionName.TOKEN_CREATE, name="ci", role="viewer")
    second = act(ctx, ActionName.TOKEN_CREATE, name="ci", role="viewer")
    client = TestClient(create_app(ctx))
    headers = {"Authorization": "Bearer " + first.token}
    assert client.get("/api/v1/tokens", headers=headers).status_code == 403
    with acting_as(OWNER), ctx.engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) AS count FROM CFG_ACCOUNTS")).scalar_one() == 1
        conn.execute(text("UPDATE CFG_ACCOUNTS SET ROLE='admin' WHERE ACCOUNT_NAME='ci'"))
    assert client.get("/api/v1/tokens", headers=headers).status_code == 200
    assert tokens.authenticate(ctx, second.token).role == "admin"
    assert {t.role for t in act(ctx, ActionName.TOKEN_LIST).tokens} == {"admin"}
    with pytest.raises(UsageError, match=r"account 'ci'.*expected an active account"):
        act(ctx, ActionName.TOKEN_CREATE, name="ci", role="viewer")
    with acting_as(OWNER), ctx.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_ACCOUNTS SET ACTIVE_FLAG='N' WHERE ACCOUNT_NAME='ci'"))
    assert client.get("/api/v1/health", headers=headers).status_code == 401
    assert tokens.authenticate(ctx, second.token) is None
    with pytest.raises(UsageError, match="ACTIVE_FLAG='N'"):
        act(ctx, ActionName.TOKEN_CREATE, name="ci", role="admin")
    assert len(act(ctx, ActionName.TOKEN_LIST).tokens) == 2


def test_account_history_never_contains_password_hashes(engine_db):
    ctx = context(engine_db)
    act(ctx, ActionName.TOKEN_CREATE, name="person", role="developer")
    with acting_as(OWNER), ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_ACCOUNTS SET ACCOUNT_KIND='USER', PASSWORD_HASH=:hash, "
                "OIDC_SUBJECT='issuer:person' WHERE ACCOUNT_NAME='person'"
            ),
            {"hash": "scrypt:private-password-hash"},
        )
        conn.execute(text("UPDATE CFG_ACCOUNTS SET PASSWORD_HASH='scrypt:rotated'"))
    with ctx.engine.connect() as conn:
        columns = {
            c["name"].upper()
            for c in inspect(conn).get_columns(
                "aud_cfg_accounts_history"
                if conn.dialect.name == "postgresql"
                else "AUD_CFG_ACCOUNTS_HISTORY"
            )
        }
        assert "PASSWORD_HASH" not in columns
        versions = conn.execute(
            text(
                "SELECT CREATED_BY AS creator, UPDATED_BY AS updater, CURRENT_FLAG AS current_flag "
                "FROM AUD_CFG_ACCOUNTS_HISTORY ORDER BY CHANGE_ID"
            )
        ).all()
        assert len(versions) == 3
        assert all(v.creator == v.updater == "owner" for v in versions)
        assert [v.current_flag for v in versions] == ["N", "N", "Y"]
        evidence = str(
            conn.execute(
                text(
                    "SELECT BEFORE_JSON AS before_json, AFTER_JSON AS after_json "
                    "FROM AUD_METADATA_CHANGES WHERE TABLE_NAME='CFG_ACCOUNTS'"
                )
            ).all()
        )
        assert "scrypt:" not in evidence and "password_hash" not in evidence.lower()


@pytest.mark.parametrize(
    "change",
    [
        "ACCOUNT_KIND='SYSTEM'",
        "ROLE='root'",
        "ACTIVE_FLAG='X'",
        "PASSWORD_HASH='secret'",
        "ACCOUNT_NAME=''",
    ],
)
def test_account_constraints_refuse_invalid_values(engine_db, change):
    act(context(engine_db), ActionName.TOKEN_CREATE, name="ci", role="viewer")
    with engine_db.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT ACCOUNT_NAME AS name FROM CFG_ACCOUNTS")).scalar_one() == "ci"
        )
    with pytest.raises(DBAPIError), acting_as(OWNER), engine_db.engine.begin() as conn:
        conn.execute(text(f"UPDATE CFG_ACCOUNTS SET {change}"))


def test_account_identity_is_reserved_and_tokens_require_an_account(engine_db):
    act(context(engine_db), ActionName.TOKEN_CREATE, name="ci", role="viewer")
    with acting_as(OWNER), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_ACCOUNTS SET ACTIVE_FLAG='N', OIDC_SUBJECT='subject'"))
    for values in ("'ci', NULL", "'other', 'subject'"):
        with pytest.raises(DBAPIError), acting_as(OWNER), engine_db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO CFG_ACCOUNTS "
                    "(ACCOUNT_NAME, OIDC_SUBJECT, ACCOUNT_KIND, ROLE) VALUES ("
                    + values
                    + ", 'SERVICE', 'viewer')"
                )
            )
    with (
        pytest.raises(DBAPIError, match="cannot be deleted"),
        acting_as(OWNER),
        engine_db.engine.begin() as conn,
    ):
        conn.execute(text("DELETE FROM CFG_ACCOUNTS"))
    with pytest.raises(DBAPIError), acting_as(OWNER), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_API_TOKENS SET ACCOUNT_ID=-1"))
    with pytest.raises(DBAPIError), acting_as(OWNER), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_API_TOKENS SET ACCOUNT_ID=NULL"))
