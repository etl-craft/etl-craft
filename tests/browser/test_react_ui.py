"""The React interface in a real browser: Home, a pipeline's runs and one run with its recovery."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName
from fixtures.actions import act
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_task,
    finish_run,
    start_run,
    task_run,
)

pytestmark = pytest.mark.browser
PASSWORD = "correct horse battery"


@pytest.fixture
def scene(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "OPS")
        extract = add_task(conn, pipeline, "EXTRACT")
        load = add_task(conn, pipeline, "LOAD")
        add_dependency(conn, pipeline, load, extract)
        good = start_run(conn, pipeline)
        task_run(conn, extract, good)
        task_run(conn, load, good)
        finish_run(conn, good)
        bad = start_run(conn, pipeline)
        task_run(conn, extract, bad)
        task_run(conn, load, bad, "FAILED")
        finish_run(conn, bad, "FAILED")
    return ctx, url, good, bad


def sign_in(page, url, destination="/app", name="owner"):
    page.goto(url + "/signin?return_to=" + destination.replace("/", "%2F"))
    page.get_by_label("Account name", exact=True).fill(name)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url(url + destination)


def open_page(pw, **options):
    browser = pw.chromium.launch()
    page = browser.new_context(ignore_https_errors=True, **options).new_page()
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    return browser, page, problems


def test_home_runs_and_run_detail_lead_to_a_confirmed_recovery(scene):
    ctx, url, _, bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url)
        expect(page).to_have_title("Home · etl-craft")
        card = page.get_by_role("link", name="default", exact=True)
        expect(card).to_be_visible()
        expect(page.get_by_text("1 failed run in the last 24 hours")).to_be_visible()
        page.get_by_role("link", name=f"#{bad}").first.click()
        expect(page.get_by_role("heading", name=f"OPS #{bad}")).to_be_visible()
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("EXTRACT")).to_be_visible()
        expect(graph.get_by_text("LOAD")).to_be_visible()
        expect(page.get_by_label("Task LOAD")).to_be_visible()  # the failed task opens itself
        page.get_by_role("button", name="Recover run").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("default")).to_be_visible()
        submit = dialog.get_by_role("button", name="Recover run")
        expect(submit).to_be_disabled()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("fixed the source")
        submit.click()
        expect(page.get_by_role("status").filter(has_text="Recover accepted")).to_be_visible()
        assert problems == []
        browser.close()
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ACTION AS action, REASON AS reason FROM AUD_CONTROL_REQUESTS "
                "WHERE PIPELINE_RUN_ID=:run"
            ),
            {"run": bad},
        ).all()
    assert [(row.action, row.reason) for row in rows] == [("RECOVER", "fixed the source")]


def test_the_runs_table_filters_by_status_and_pipeline_in_the_address(scene):
    _, url, good, bad = scene
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, "/app/projects/default/runs")
        table = page.get_by_role("table", name="Pipeline runs")
        expect(table.get_by_role("link", name=f"#{good}")).to_be_visible()
        expect(table.get_by_role("link", name=f"#{bad}")).to_be_visible()
        page.get_by_label("Status").select_option("FAILED")
        expect(table.get_by_role("link", name=f"#{good}")).to_have_count(0)
        expect(table.get_by_role("link", name=f"#{bad}")).to_be_visible()
        assert "status=FAILED" in page.url
        page.reload()
        expect(page.get_by_label("Status")).to_have_value("FAILED")
        browser.close()


def test_a_viewer_sees_the_failed_run_but_no_recover_action(scene):
    ctx, url, _, bad = scene
    act(
        ctx,
        ActionName.ACCESS_GRANT,
        project="default",
        account="alice",
        permission="CAN_VIEW",
        reason="view the runs",
    )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, f"/app/projects/default/runs/OPS/{bad}", name="alice")
        expect(page.get_by_role("heading", name=f"OPS #{bad}")).to_be_visible()
        expect(page.get_by_text("Failed", exact=True).first).to_be_visible()
        expect(page.get_by_role("button", name="Recover run")).to_have_count(0)
        browser.close()


def test_production_is_unmistakable_and_recovery_needs_the_project_code(scene):
    ctx, url, _, bad = scene
    act(
        ctx,
        ActionName.PROJECT_SET,
        project="default",
        environment_type="PROD",
        governance="STRICT",
        reason="production project",
    )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, f"/app/projects/default/runs/OPS/{bad}")
        expect(page).to_have_title(f"PRODUCTION · default · OPS #{bad} · etl-craft")
        expect(page.get_by_role("status").filter(has_text="PRODUCTION")).to_be_visible()
        page.get_by_role("button", name="Recover run").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("urgent")
        submit = dialog.get_by_role("button", name="Recover run")
        expect(submit).to_be_disabled()
        dialog.get_by_label("This is PRODUCTION").fill("default")
        expect(submit).to_be_enabled()
        browser.close()


def test_the_navigation_collapses_to_icons_keeps_its_links_and_is_remembered(scene):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, "/app/projects/default/runs")
        nav = page.get_by_role("navigation", name="Main")
        runs = nav.get_by_role("link", name="Runs", exact=True)
        wide = runs.bounding_box()["width"]
        expect(nav.get_by_text("Overview")).to_be_visible()
        # the column reaches the bottom edge of the window, however short the page is
        side = page.locator("aside").bounding_box()
        assert side["y"] + side["height"] >= 899
        page.get_by_role("button", name="Collapse the navigation").click()
        expect(nav.get_by_text("Overview")).to_have_count(0)
        expect(page.locator("aside")).to_have_css("width", "56px")
        assert runs.bounding_box()["width"] < wide / 2
        expect(runs).to_have_attribute("title", "Runs")
        assert runs.locator("svg").count() == 1
        page.reload()
        expect(page.get_by_role("button", name="Expand the navigation")).to_be_visible()
        page.get_by_role("button", name="Expand the navigation").click()
        expect(nav.get_by_text("Overview")).to_be_visible()
        assert runs.locator("svg").count() == 1
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_every_page_renders_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    _, url, _, bad = scene
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    pages = {
        "home": "/app",
        "runs": "/app/projects/default/runs",
        "run": f"/app/projects/default/runs/OPS/{bad}",
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
            assert page.evaluate("document.documentElement.dataset.theme") == scheme
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=f"{shots}/{name}-{scheme}-{width}.png", full_page=True)
        assert problems == [], "console errors (a refused style or script shows here)"
        browser.close()
