"""Browser authorization-code proof over real TLS, retaining the device protocol."""

from dataclasses import replace
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api.app import create_app
from etl_craft.api.browser_sessions import CSRF, SESSION
from etl_craft.config.model import DocsSiteConfig
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from fixtures.actions import act

SSO_COOKIE = "__Host-etl-craft-sso"


@pytest.fixture
def browser_login(empty_engine_db, issuer, monkeypatch):
    from etl_craft.engine.schema import init_db

    engine_db = empty_engine_db
    init_db(engine_db.engine)
    auth, issuer_state = issuer
    monkeypatch.setenv("BROWSER_TEST_SECRET", "test-key-material-that-is-at-least-thirty-two-bytes")
    config = replace(
        engine_db.config,
        auth=SimpleNamespace(**(vars(auth) | {"browser_state_secret": "BROWSER_TEST_SECRET"})),
        docs_site=DocsSiteConfig(external_url="https://testserver"),
    )
    ctx = OperationContext(
        engine_db.engine, config, Actor("owner", ActorKind.USER), role=ApiRole.ADMIN
    )
    act(
        ctx, ActionName.ACCOUNT_ADD, name="alice", role=ApiRole.VIEWER, oidc_subject="known-subject"
    )
    client = TestClient(create_app(ctx), base_url="https://testserver")
    page = client.get("/ui/signin")
    import re

    csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text)[1]
    client.headers["X-CSRF-Token"] = csrf
    return ctx, client, issuer_state


def begin(client):
    answer = client.post("/api/v1/login/browser/start", json={"return_to": "/ui/projects"})
    assert answer.status_code == 200, answer.text
    return answer.json()["authorization_url"]


def authorize(address):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None

    try:
        build_opener(NoRedirect()).open(address)
    except HTTPError as error:
        assert error.code == 302
        return {k: v[0] for k, v in parse_qs(urlsplit(error.headers["Location"]).query).items()}
    raise AssertionError("issuer did not redirect")


def finish(client, response):
    return client.post("/api/v1/login/browser/callback", json=response)


def assert_refused(ctx, answer):
    assert answer.status_code == 403, answer.text
    assert SESSION not in answer.cookies
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) AS count FROM AUD_ACTIONS "
                    "WHERE COMMAND='login' AND OUTCOME='REFUSED'"
                )
            ).scalar_one()
            > 0
        )
        assert conn.execute(text("SELECT COUNT(*) AS count FROM CFG_API_TOKENS")).scalar_one() == 0


def test_authorization_parameters_verified_session_actor_and_single_use(browser_login):
    ctx, client, _ = browser_login
    address = begin(client)
    params = {k: v[0] for k, v in parse_qs(urlsplit(address).query).items()}
    assert params["response_type"] == "code"
    assert params["scope"] == "openid email profile"
    assert params["client_id"] == "etl"
    assert params["redirect_uri"] == "https://testserver/ui/signin/callback"
    assert params["code_challenge_method"] == "S256"
    assert all(params[k] for k in ("state", "nonce", "code_challenge"))
    proof = client.cookies.get(SSO_COOKIE)
    response = authorize(address)
    answer = finish(client, response)
    assert answer.status_code == 200, answer.text
    assert answer.json()["redirect"] == "/ui/projects"
    assert SESSION in answer.cookies
    cookie_header = answer.headers.get_list("set-cookie")[0]
    assert (
        "HttpOnly" in cookie_header
        and "SameSite=lax" in cookie_header
        and "Secure" in cookie_header
    )
    assert client.get("/api/v1/whoami").json()["name"] == "alice"
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) AS count FROM AUD_ACTIONS "
                    "WHERE COMMAND='login' AND ACTOR='alice' AND OUTCOME='SUCCESS'"
                )
            ).scalar_one()
            > 0
        )
    client.cookies.set(SSO_COOKIE, proof, domain="testserver.local", path="/")
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF)
    # Even a fresh issuer code using the old state must not make that state reusable.
    another_code = authorize(address)
    replay = finish(client, another_code)
    assert replay.status_code == 403
    assert "already used" in replay.text
    assert finish(client, response).status_code == 403
    fresh = authorize(begin(client))
    stale_code = {"state": fresh["state"], "code": response["code"]}
    code_replay = finish(client, stale_code)
    assert code_replay.status_code == 403
    assert "code exchange refused" in code_replay.text
    payload = jwt.decode(
        proof, "test-key-material-that-is-at-least-thirty-two-bytes", algorithms=["HS256"]
    )
    with ctx.engine.connect() as conn:
        arguments = " ".join(
            str(row.arguments)
            for row in conn.execute(text("SELECT ARGUMENTS AS arguments FROM AUD_ACTIONS"))
        )
    for secret in (payload["state"], payload["verifier"], payload["nonce"], proof):
        assert secret not in arguments


@pytest.mark.parametrize(
    "attack",
    ["state", "expired", "missing_nonce", "wrong_nonce", "signature", "pkce", "tampered_cookie"],
)
def test_browser_proof_refusals_are_audited_without_sessions(browser_login, attack):
    ctx, client, state = browser_login
    address = begin(client)
    response = authorize(address)
    if attack == "state":
        response["state"] = "not-the-issued-state"
    elif attack == "missing_nonce":
        state["omit_claims"] = ("nonce",)
    elif attack == "wrong_nonce":
        state["extra_claims"] = {"nonce": "not-the-issued-nonce"}
    elif attack == "signature":
        state["bad_signature"] = True
    else:
        proof = client.cookies.get(SSO_COOKIE)
        key = "test-key-material-that-is-at-least-thirty-two-bytes"
        payload = jwt.decode(proof, key, algorithms=["HS256"])
        if attack == "expired":
            payload["exp"] = 1
        elif attack == "pkce":
            payload["verifier"] = "wrong-verifier"
        proof = jwt.encode(payload, key, algorithm="HS256")
        if attack == "tampered_cookie":
            proof = proof.rsplit(".", 1)[0] + ".invalid"
        client.cookies.set(SSO_COOKIE, proof, domain="testserver.local", path="/")
    assert_refused(ctx, finish(client, response))


@pytest.mark.parametrize("value", [None, "short"])
def test_missing_or_short_browser_secret_names_the_variable(browser_login, monkeypatch, value):
    _, client, _ = browser_login
    if value is None:
        monkeypatch.delenv("BROWSER_TEST_SECRET")
    else:
        monkeypatch.setenv("BROWSER_TEST_SECRET", value)
    answer = client.post("/api/v1/login/browser/start", json={})
    assert answer.status_code == 409
    assert "BROWSER_TEST_SECRET" in answer.text
    assert "32 bytes" in answer.text if value else "not set" in answer.text
