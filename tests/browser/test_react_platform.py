"""System health, agents, administration, maintenance, search, settings and sign-in in a browser."""

import contextlib
import os
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_ui import PASSWORD, open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run, task_run

pytestmark = pytest.mark.browser


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


@pytest.fixture
def scene(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ORDERS")
        extract = add_task(conn, pipeline, "EXTRACT")
        run = start_run(conn, pipeline)
        task_run(conn, extract, run)
        finish_run(conn, run)
    return ctx, url, run


def test_sign_in_refuses_a_wrong_password_and_returns_to_the_page_asked_for(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        page.goto(url + "/app/projects/default/runs")
        page.wait_for_url(url + "/app/signin?return_to=%2Fapp%2Fprojects%2Fdefault%2Fruns")
        page.get_by_label("Account name", exact=True).fill("owner")
        page.get_by_label("Password", exact=True).fill("not the password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.get_by_role("alert")).to_be_visible()
        assert page.url.endswith("/app/signin?return_to=%2Fapp%2Fprojects%2Fdefault%2Fruns")
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(url + "/app/projects/default/runs")
        page.goto(url + "/app/signin")  # already signed in: nothing to ask
        page.wait_for_url(url + "/app")
        assert [p for p in problems if "status of 400" not in p] == []
        browser.close()


def test_system_health_agents_and_about_read_the_engine_db(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, "/app/system")
        expect(page.get_by_role("heading", name="System health", exact=True)).to_be_visible()
        expect(page.get_by_text("Not running")).to_be_visible()  # no controller in the scene
        expect(
            page.get_by_role("table", name="Projects").get_by_text("default", exact=True).first
        ).to_be_visible()
        shoot(page, "system")
        page.get_by_role("link", name="Open agents").click()
        expect(page.get_by_role("heading", name="Agents", exact=True)).to_be_visible()
        expect(page.get_by_text("No agents have registered")).to_be_visible()
        page.goto(url + "/app/about")
        expect(page.get_by_text("Package version")).to_be_visible()
        assert problems == []
        browser.close()


def test_settings_save_and_the_password_change_ends_the_session(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/app/settings")
        save = page.get_by_role("button", name="Save settings")
        expect(save).to_be_disabled()
        page.get_by_label("Page size (1 to 100)").fill("30")
        save.click()
        expect(page.get_by_role("status").filter(has_text="Settings saved.")).to_be_visible()
        page.reload()
        expect(page.get_by_label("Page size (1 to 100)")).to_have_value("30")
        page.goto(url + "/app/password")
        page.get_by_label("Current password").fill("wrong wrong wrong")
        page.get_by_label("New password", exact=True).fill("another correct horse")
        page.get_by_label("Confirm new password").fill("another correct horse")
        page.get_by_role("button", name="Change password").click()
        expect(page.get_by_role("alert")).to_contain_text("password change refused")
        page.get_by_label("Current password").fill(PASSWORD)
        page.get_by_role("button", name="Change password").click()
        page.wait_for_url(url + "/app/signin?changed=1")
        expect(page.get_by_text("Your password was changed")).to_be_visible()
        assert [p for p in problems if "status of 400" not in p] == []
        browser.close()


def test_search_finds_pipelines_runs_and_remembers_what_was_opened(scene):
    _, url, _run = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, "/app/projects/default/pipelines/ORDERS")
        page.get_by_label("Search pipelines, tasks, tables and runs").fill("ORD")
        page.keyboard.press("Enter")
        results = page.get_by_role("table", name="Search results")
        expect(results.get_by_role("link", name="ORDERS")).to_be_visible()
        shoot(page, "search")
        expect(page.get_by_role("link", name="ORDERS").last).to_be_visible()  # recent
        page.get_by_label("Search pipelines, tasks, tables and runs").fill("EXTRACT")
        page.keyboard.press("Enter")
        page.get_by_role("link", name="EXTRACT").first.click()
        expect(page).to_have_url(url + "/app/projects/default/pipelines/ORDERS/tasks/EXTRACT")
        page.goto(url + "/app/projects/default/search")
        page.keyboard.press("/")
        expect(page.get_by_label("Search pipelines, tasks, tables and runs")).to_be_focused()
        assert problems == []
        browser.close()


def test_administrators_manage_accounts_and_tokens_through_confirmations(scene):
    ctx, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/app/admin?tab=accounts")
        expect(page.get_by_role("table", name="Accounts").get_by_text("alice")).to_be_visible()
        page.get_by_role("button", name="Add account").click()
        dialog = page.get_by_role("dialog")
        add = dialog.get_by_role("button", name="Add account")
        expect(add).to_be_disabled()  # the name is required
        dialog.get_by_label("Account name").fill("bob")
        dialog.get_by_label("Temporary password (users) (optional)").fill("temporary password 1")
        add.click()
        expect(page.get_by_role("status").filter(has_text="Account added.")).to_be_visible()
        expect(page.get_by_role("table", name="Accounts").get_by_text("bob")).to_be_visible()
        shoot(page, "admin-accounts")
        page.get_by_role("tab", name="Tokens").click()
        page.get_by_role("button", name="Create token").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Name").fill("ci")
        dialog.get_by_role("button", name="Create token").click()
        expect(page.get_by_text("This token is shown once")).to_be_visible()
        tokens = page.get_by_role("table", name="API tokens")
        expect(tokens.get_by_text("ci", exact=True)).to_be_visible()
        page.get_by_role("tab", name="Projects").click()
        expect(
            page.get_by_role("table", name="Projects").get_by_text("default", exact=True).first
        ).to_be_visible()
        assert problems == []
        browser.close()
    with ctx.engine.connect() as conn:
        rows = conn.execute(text("SELECT ACCOUNT_NAME AS name FROM CFG_ACCOUNTS")).all()
    names = {r.name for r in rows}
    assert "bob" in names


def test_a_viewer_is_told_the_administration_page_needs_an_administrator(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, "/app/admin", name="alice")
        expect(page.get_by_role("alert")).to_contain_text("needs the admin role")
        expect(page.get_by_role("link", name="Administration")).to_have_count(0)
        browser.close()


def test_maintenance_previews_without_changing_anything(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1100})
        sign_in(page, url, "/app/projects/default/maintenance")
        page.get_by_role("button", name="Preview purge").click()
        expect(page.locator("pre").first).to_contain_text("dry_run")
        shoot(page, "maintenance")
        page.get_by_role("button", name="Purge", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_role("button", name="Purge")).to_be_disabled()  # needs a reason
        dialog.get_by_role("button", name="Cancel").click()
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_pages_render_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    _, url, _ = scene
    pages = {
        "system": "/app/system",
        "agents": "/app/agents",
        "about": "/app/about",
        "settings": "/app/settings",
        "search": "/app/projects/default/search?q=ORD",
        "accounts": "/app/admin?tab=accounts",
        "projects-admin": "/app/admin?tab=projects",
        "maintenance": "/app/projects/default/maintenance",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        sign_in(page, url)
        for name, path in pages.items():
            page.goto(url + path)
            page.wait_for_load_state("networkidle")
            expect(page.locator("main")).to_be_visible()
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 0, f"{name} scrolls sideways by {overflow}px at {width}px"
            shoot(page, f"{name}-{scheme}-{width}")
        page.context.clear_cookies()
        page.goto(url + "/app/signin")
        expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
        shoot(page, f"signin-{scheme}-{width}")
        assert [p for p in problems if "status of 404" not in p] == []
        browser.close()


def test_a_session_that_ended_says_so_and_signing_in_returns_to_the_page(scene):
    ctx, url, _ = scene
    with sync_playwright() as pw:
        browser, page, _problems = open_page(pw)
        sign_in(page, url, "/app/projects/default/pipelines/ORDERS")
        expect(page.get_by_role("heading", name="ORDERS")).to_be_visible()
        with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
            conn.execute(text("UPDATE CFG_API_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP"))
        with contextlib.suppress(PlaywrightTimeoutError):  # a refused refresh may cover the page
            page.get_by_role("link", name="Runs", exact=True).click(timeout=2000)
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("Your session has ended")).to_be_visible()
        assert "/signin" not in page.url  # nothing was thrown away
        dialog.get_by_role("button", name="Sign in again").click()
        page.wait_for_url("**/app/signin?return_to=*")
        browser.close()
