"""The built browser interface is served under /app to a signed-in session only."""

import re

import pytest
from fastapi.testclient import TestClient

from etl_craft.api import ui_spa
from etl_craft.api.app import create_app
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from fixtures.actions import act

CSRF = "__Host-etl-craft-csrf"
PASSWORD = "correct horse battery"


@pytest.fixture
def scene(engine_db):
    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    with engine_db.engine.begin() as conn:
        mark_packaged_migrations_applied(conn)
    ctx = OperationContext(
        engine_db.engine, engine_db.config, Actor("owner", ActorKind.USER), role=ApiRole.ADMIN
    )
    act(ctx, ActionName.ACCOUNT_ADD, name="alice", role=ApiRole.VIEWER, password=PASSWORD)
    return TestClient(create_app(ctx), base_url="https://testserver", follow_redirects=False)


def sign_in(client):
    page = client.get("/signin", params={"return_to": "/app"})
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    response = client.post(
        "/api/v1/login/password",
        headers={"HX-Request": "true", "X-CSRF-Token": token, "Origin": "https://testserver"},
        json={"name": "alice", "password": PASSWORD, "_return_to": "/app"},
    )
    assert response.status_code == 200, response.text


def test_the_shell_sends_a_visitor_to_sign_in_and_back_to_the_same_page(scene):
    response = scene.get("/app/projects/default/runs", params={"status": "FAILED"})
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/signin?return_to=%2Fapp%2Fprojects%2Fdefault%2Fruns%3Fstatus%3DFAILED"
    )


def test_the_signed_in_shell_carries_the_session_challenge_and_no_inline_script(scene):
    sign_in(scene)
    for path in ("/app", "/app/projects/default/runs", "/app/projects/default/runs/OPS/7"):
        response = scene.get(path)
        assert response.status_code == 200, path
        token = re.search(r'name="csrf-token" content="([^"]+)"', response.text).group(1)
        assert token == scene.cookies[CSRF] and ui_spa.CSRF_SLOT not in response.text
        assert "<script>" not in response.text and 'type="module"' in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]


def test_the_built_assets_are_served_to_the_shell(scene):
    sign_in(scene)
    shell = scene.get("/app").text
    asset = re.search(r'(?:src|href)="(/app/assets/[^"]+\.js)"', shell).group(1)
    served = scene.get(asset)
    assert served.status_code == 200 and "javascript" in served.headers["content-type"]


def test_a_missing_bundle_fails_with_the_remedy(scene, monkeypatch, tmp_path):
    sign_in(scene)
    monkeypatch.setattr(ui_spa, "BUNDLE", tmp_path / "spa")
    response = scene.get("/app")
    assert response.status_code == 404
    assert "bundle is missing" in response.text and "make ui-build" in response.text
