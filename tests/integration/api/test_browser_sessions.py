"""Cookie authority and account security through the sign-in and account actions."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api.app import create_app
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from fixtures.actions import act

SESSION = "__Host-etl-craft-session"
CSRF = "__Host-etl-craft-csrf"
PASSWORD = "correct horse battery"


@pytest.fixture
def browser_scene(engine_db):
    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    with engine_db.engine.begin() as conn:
        mark_packaged_migrations_applied(conn)
    ctx = OperationContext(
        engine_db.engine, engine_db.config, Actor("owner", ActorKind.USER), role=ApiRole.ADMIN
    )
    act(ctx, ActionName.ACCOUNT_ADD, name="owner", role=ApiRole.ADMIN, password=PASSWORD)
    act(ctx, ActionName.ACCOUNT_ADD, name="alice", role=ApiRole.VIEWER, password=PASSWORD)
    return ctx, TestClient(
        create_app(ctx), base_url="https://testserver", raise_server_exceptions=False
    )


def login(client, name="alice", password=PASSWORD, destination="/ui"):
    page = client.get("/ui/signin")
    assert page.status_code == 200, page.text
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    return client.post(
        "/api/v1/login/password",
        headers={
            "Accept": "application/json",
            "X-CSRF-Token": csrf,
            "Origin": "https://testserver",
        },
        json={"name": name, "password": password, "_return_to": destination},
    )


def change(client, path, fields):
    return client.post(path, headers={"X-CSRF-Token": client.cookies[CSRF]}, json=fields)


def test_browser_cookie_return_to_csrf_and_shared_tab_revocation(browser_scene):
    _, client = browser_scene
    before = client.get("/ui/about", follow_redirects=False)
    assert before.status_code == 303
    assert before.headers["location"] == "/ui/signin?return_to=%2Fui%2Fabout"
    response = login(client, destination="/ui/about")
    assert response.status_code == 200, response.text
    assert response.json() == {"redirect": "/ui/about"}
    assert "access_token" not in response.text
    cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(SESSION + "=")
    )
    assert all(flag in cookie.lower() for flag in ("httponly", "secure", "samesite=lax", "path=/"))
    assert "domain=" not in cookie.lower()
    tab = TestClient(client.app, base_url="https://testserver")
    tab.cookies.update(client.cookies)
    assert tab.get("/ui/about").status_code == 200
    assert client.post("/api/v1/account/settings", json={"theme": "dark"}).status_code == 403
    assert (
        client.post("/api/v1/account/settings", json={"theme": "dark", "_csrf": "é"}).status_code
        == 403
    )
    denied = client.post(
        "/api/v1/account/settings",
        headers={"X-CSRF-Token": client.cookies[CSRF], "Origin": "https://evil.example"},
        json={"theme": "dark"},
    )
    assert denied.status_code == 403
    changed = {
        "theme": "dark",
        "timezone": "Asia/Kolkata",
        "page_size": 40,
        "time_display": "absolute",
    }
    assert change(client, "/api/v1/account/settings", changed).status_code == 200
    settings = tab.get("/api/v1/whoami").json()["settings"]
    assert settings["theme"] == "dark" and settings["page_size"] == 40
    assert change(client, "/api/v1/login/revoke", {}).status_code == 200
    assert tab.get("/api/v1/whoami").status_code == 401


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.example",
        "//evil.example",
        "/%2fevil.example",
        "/%255cevil",
        "/\\evil",
        "/%0d%0aLocation:evil",
    ],
)
def test_browser_return_to_refuses_external_or_encoded_authority(browser_scene, destination):
    _, client = browser_scene
    response = login(client, destination=destination)
    assert response.status_code == 400
    assert "same-site" in response.text


def test_signin_keeps_a_valid_challenge_and_never_echoes_a_malformed_one(browser_scene):
    _, client = browser_scene
    kept = "A" * 43
    client.cookies.set(CSRF, kept, domain="testserver.local")
    page = client.get("/ui/signin")
    assert f'content="{kept}"' in page.text
    assert CSRF not in page.headers.get("set-cookie", "")
    client.cookies.clear()
    client.cookies.set(CSRF, "x; Domain=evil.example", domain="testserver.local")
    page = client.get("/ui/signin")
    issued = re.search(CSRF + r"=([^;]+);", page.headers["set-cookie"]).group(1)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", issued)
    assert "evil.example" not in page.headers["set-cookie"]


def test_lockout_generic_message_unlock_and_temporary_password(browser_scene):
    ctx, client = browser_scene
    generic = login(client, password="wrong").text
    assert login(client, name="missing", password="wrong").text == generic
    for _ in range(ctx.config.auth.lockout_after - 1):
        assert login(client, password="wrong").status_code == 400
    assert "Account locked" not in login(client, password="wrong").text
    assert "Account locked, contact your administrator" in login(client).text
    act(ctx, ActionName.ACCOUNT_UNLOCK, name="alice")
    assert login(client).status_code == 200
    with ctx.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT FAILED_SIGNINS AS failed_signins, LOCKED_DATE AS locked_date FROM "
                "CFG_ACCOUNTS WHERE ACCOUNT_NAME='alice'"
            )
        ).one()
        assert row.failed_signins == 0 and row.locked_date is None
    act(ctx, ActionName.ACCOUNT_RESET_PASSWORD, name="alice", password="temporary password")
    response = login(client, password="temporary password", destination="/ui/about")
    assert response.json() == {"redirect": "/ui/password"}  # a temporary password is changed first
    assert client.get("/api/v1/about").status_code == 403
    from etl_craft.core.errors import PermissionDeniedError
    from etl_craft.services.operations.identity import authenticated_context
    from etl_craft.services.operations.tokens import authenticate

    identity = authenticate(ctx, client.cookies[SESSION])
    with pytest.raises(PermissionDeniedError, match="temporary password"):
        act(authenticated_context(ctx, identity), ActionName.MIGRATE)
    response = change(
        client,
        "/api/v1/account/password",
        {"current_password": "temporary password", "password": "replacement password"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/whoami").status_code == 401
    assert login(client, password="replacement password").status_code == 200
    assert client.get("/api/v1/about").status_code == 200


def test_browser_sso_uses_the_same_cookie(browser_scene, monkeypatch):
    from dataclasses import replace

    from etl_craft.services import oidc

    ctx, _ = browser_scene
    act(ctx, ActionName.ACCOUNT_ADD, name="sso", role=ApiRole.VIEWER, oidc_subject="subject")
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            auth=replace(
                ctx.config.auth, oidc_issuer="https://issuer.example", oidc_client_id="console"
            ),
        ),
    )
    monkeypatch.setattr(
        oidc,
        "start_device",
        lambda auth: oidc.DeviceGrant(
            "ABC", "https://issuer.example/approve", "device", "nonce", 1, 60
        ),
    )
    monkeypatch.setattr(
        oidc, "poll_device", lambda auth, device, nonce: oidc.IdentityClaims("subject")
    )
    client = TestClient(create_app(ctx), base_url="https://testserver")
    client.get("/ui/signin")
    h = {"Accept": "application/json", "X-CSRF-Token": client.cookies[CSRF]}
    started = client.post("/api/v1/login/sso", headers=h, json={"_return_to": "/ui/about"})
    assert started.status_code == 200 and started.json()["user_code"] == "ABC"
    response = client.post(
        "/api/v1/login/sso/poll",
        headers=h,
        json={"device_code": "device", "nonce": "nonce", "_return_to": "/ui/about"},
    )
    assert response.status_code == 200 and response.json() == {"redirect": "/ui/about"}
    assert SESSION in client.cookies and "access_token" not in response.text


def test_full_settings_replacement_repairs_invalid_preferences(browser_scene):
    ctx, client = browser_scene
    assert login(client).status_code == 200
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_ACCOUNTS SET UI_SETTINGS=:settings WHERE ACCOUNT_NAME='alice'"),
            {"settings": '{"timezone":"Invalid/Place"}'},
        )
    partial = change(client, "/api/v1/account/settings", {"theme": "light"})
    assert partial.status_code == 404 and "replace all five" in partial.text
    result = change(
        client,
        "/api/v1/account/settings",
        {
            "theme": "system",
            "timezone": "UTC",
            "default_project": "",
            "page_size": 25,
            "time_display": "relative",
        },
    )
    assert result.status_code == 200
    assert client.get("/api/v1/whoami").json()["settings"]["timezone"] == "UTC"
