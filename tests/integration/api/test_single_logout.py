"""Provider logout discovery cannot leave a local session live or redirect off-origin."""

from urllib.parse import parse_qs, urlsplit

import pytest
from test_browser_sso import authorize, begin, finish
from test_browser_sso import browser_login as browser_login

from etl_craft.api.browser_sessions import CSRF, SESSION


@pytest.mark.parametrize("provider", [True, False])
@pytest.mark.parametrize("interface", ["browser", "api"])
def test_logout_revokes_the_session_and_reports_provider_redirect(
    browser_login, provider, interface
):
    ctx, client, issuer = browser_login
    if provider:
        issuer["end_session_endpoint"] = ctx.config.auth.oidc_issuer + "/logout"
    answer = finish(client, authorize(begin(client)))
    assert answer.status_code == 200, answer.text
    token = client.cookies.get(SESSION)
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF)
    if interface == "api":
        client.cookies.clear()
        client.headers["Authorization"] = "Bearer " + token
    result = client.post("/api/v1/login/revoke", json={"token": token})
    assert result.status_code == 200, result.text
    denied = client.get("/api/v1/whoami", headers={"Authorization": "Bearer " + token})
    assert denied.status_code == 401
    data = result.json()
    if provider:
        target = urlsplit(data["redirect"])
        assert target.path == "/logout"
        assert target.netloc == urlsplit(ctx.config.auth.oidc_issuer).netloc
        assert parse_qs(target.query)["post_logout_redirect_uri"] == ["https://testserver"]
        assert "id_token_hint" not in parse_qs(target.query)
    else:
        assert data["redirect"] is None
        assert (
            data["message"] == "Signed out of etl-craft; the provider has no end-session endpoint, "
            "so provider sign-out stays local."
        )


def test_logout_refuses_a_foreign_post_logout_address_without_a_redirect(browser_login):
    ctx, client, issuer = browser_login
    issuer["end_session_endpoint"] = ctx.config.auth.oidc_issuer + "/logout"
    assert finish(client, authorize(begin(client))).status_code == 200
    token = client.cookies.get(SESSION)
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF)
    answer = client.post(
        "/api/v1/login/revoke", json={"post_logout_redirect_uri": "https://foreign.example/"}
    )
    assert answer.status_code == 403
    assert "public origin" in answer.text
    assert "location" not in answer.headers
    assert "redirect" not in answer.json()
    assert (
        client.get("/api/v1/whoami", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )


def test_logout_refuses_insecure_provider_endpoint_after_revoking_locally(browser_login):
    _, client, issuer = browser_login
    issuer["end_session_endpoint"] = "http://provider.example/logout"
    assert finish(client, authorize(begin(client))).status_code == 200
    token = client.cookies.get(SESSION)
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF)
    answer = client.post("/api/v1/login/revoke", json={})
    assert answer.status_code == 409
    assert "HTTPS URL" in answer.text
    assert "location" not in answer.headers
    assert (
        client.get("/api/v1/whoami", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )
