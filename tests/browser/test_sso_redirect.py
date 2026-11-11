"""Browser SSO redirects through the TLS issuer without copying a device code."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page

from etl_craft.core.enums import ActionName, ApiRole
from fixtures.actions import act

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("site", ["sso-browser"], indirect=True)
def test_sso_browser_returns_signed_in_without_a_copy_code_panel(site):
    ctx, url = site
    act(
        ctx,
        ActionName.ACCOUNT_ADD,
        name="sso-browser-user",
        role=ApiRole.VIEWER,
        oidc_subject="known-subject",
    )
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        page.goto(url + "/ui/signin?return_to=/ui/projects/default")
        expect(page.get_by_role("button", name="Sign in with SSO")).to_be_visible()
        page.evaluate("() => document.fonts.ready")
        with page.expect_request(lambda request: "/authorize?" in request.url, timeout=5000):
            page.get_by_role("button", name="Sign in with SSO").click()
        page.wait_for_url(url + "/ui/projects/default", timeout=10_000)
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        expect(page.get_by_text("Approve SSO sign-in")).to_have_count(0)
        identity = page.request.get(url + "/api/v1/whoami").json()
        assert identity["name"] == "sso-browser-user"
        if folder := os.environ.get("ETL_CRAFT_UI_SCREENSHOTS"):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=f"{folder}/sso-redirect-signed-in.png")
        assert problems == []
        browser.close()


@pytest.mark.parametrize("site", ["sso-browser"], indirect=True)
def test_sso_provider_refusal_shows_a_reason_and_can_start_again(site):
    _, url = site
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        page.goto(url + "/ui/signin/callback?error=access_denied&state=provider-state")
        expect(page.get_by_role("alert")).to_contain_text("The identity provider refused sign-in")
        expect(page).to_have_url(url + "/ui/signin/callback")
        if folder := os.environ.get("ETL_CRAFT_UI_SCREENSHOTS"):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=f"{folder}/sso-redirect-refused.png")
        page.get_by_role("link", name="Start sign-in again").click()
        expect(page.get_by_role("button", name="Sign in with SSO")).to_be_visible()
        if folder := os.environ.get("ETL_CRAFT_UI_SCREENSHOTS"):
            page.screenshot(path=f"{folder}/sso-redirect-signin.png")
        assert problems == []
        browser.close()
