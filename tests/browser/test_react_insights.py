"""Insights, the command console and the catalog in a real browser."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, RunStatus
from etl_craft.engine import transitions
from fixtures.actions import act
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_task,
    finish_run,
    start_run,
    task_run,
)
from fixtures.run_scene import attempt

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
        load = add_task(conn, pipeline, "LOAD")
        add_dependency(conn, pipeline, load, extract)
        for _ in range(3):
            run = start_run(conn, pipeline)
            task_run(conn, extract, run, rows_written=10, target_count=10)
            task_run(conn, load, run, rows_written=10, target_count=10)
            finish_run(conn, run)
        run = start_run(conn, pipeline)
        task_run(conn, extract, run)
        summary = transitions.find_or_create_task_run(conn, load, run).task_run_id
        attempt(conn, summary, fail="connection reset by source")
        transitions.finish_task_run(conn, summary, status=RunStatus.FAILED)
        finish_run(conn, run, "FAILED")
    return ctx, url


def test_insights_summarises_runs_and_filters_through_the_address(scene):
    _, url = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default")
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        expect(page.get_by_text("Success rate", exact=True).first).to_be_visible()
        expect(page.get_by_role("list", name="Runs per day")).to_be_visible()
        expect(page.get_by_role("list", name="Latest runs")).to_be_visible()
        shoot(page, "insights")
        page.get_by_role("tab", name="Pipelines").click()
        pipelines = page.get_by_role("table", name="Pipelines")
        expect(pipelines.get_by_role("link", name="ORDERS")).to_be_visible()
        page.get_by_role("tab", name="Failures").click()
        expect(page.get_by_role("table", name="Failures").get_by_text("LOAD")).to_be_visible()
        page.get_by_role("tab", name="Overview").click()
        page.get_by_label("To (UTC day)").fill("2020-01-05")
        page.get_by_label("From (UTC day)").fill("2020-01-01")
        expect(page.get_by_text("No runs started in this window.")).to_be_visible()
        assert "from=2020-01-01" in page.url and "to=2020-01-05" in page.url
        page.get_by_text("Pipelines (all you can view)").click()
        page.get_by_label("ORDERS").click()
        expect(page.get_by_label("ORDERS")).to_be_checked()
        assert "pipeline=ORDERS" in page.url
        page.reload()
        expect(page.get_by_text("Pipelines (1 selected)")).to_be_visible()
        assert problems == []
        browser.close()


def test_the_console_runs_a_line_completes_commands_and_recalls_history(scene):
    _, url = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/console")
        log = page.get_by_role("log", name="Console output")
        expect(
            page.get_by_role("button", name="pipelines", exact=True)
        ).to_be_visible()  # commands loaded
        expect(log).to_contain_text("type help for the commands you can run")
        line = page.get_by_label("$ etl-craft")
        line.fill("pipe")
        line.press("Tab")
        expect(line).to_have_value("pipelines ")
        line.press("Enter")
        expect(log).to_contain_text("$ etl-craft pipelines")
        expect(log).to_contain_text("ORDERS")
        line.press("ArrowUp")
        expect(line).to_have_value("pipelines")
        line.fill("nonsense")
        line.press("Enter")
        expect(log).to_contain_text("exit")
        shoot(page, "console")
        page.get_by_role("button", name="status", exact=True).click()
        expect(line).to_have_value("status ")
        assert problems == []
        browser.close()


def test_a_viewer_is_offered_fewer_console_commands(scene):
    ctx, url = scene
    act(
        ctx,
        ActionName.ACCESS_GRANT,
        project="default",
        account="alice",
        permission="CAN_VIEW",
        reason="read",
    )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, "/ui/projects/default/console")
        expect(page.get_by_role("button", name="status", exact=True)).to_be_visible()
        owner_commands = (
            page.get_by_role("list")
            .filter(has=page.get_by_role("button", name="status", exact=True))
            .get_by_role("button")
            .count()
        )
        browser.close()
        browser, page, _ = open_page(pw)
        sign_in(page, url, "/ui/projects/default/console", name="alice")
        expect(page.get_by_role("button", name="status", exact=True)).to_be_visible()
        viewer_commands = (
            page.get_by_role("list")
            .filter(has=page.get_by_role("button", name="status", exact=True))
            .get_by_role("button")
            .count()
        )
        assert 0 < viewer_commands < owner_commands
        browser.close()


def test_the_catalog_says_when_nothing_is_built_and_offers_the_rebuild(scene):
    _, url = scene
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog")
        expect(page.get_by_role("heading", name="Catalog", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Validate metadata")).to_be_visible()
        expect(page.get_by_role("button", name="Rebuild catalog")).to_be_visible()
        expect(page.get_by_text("catalog is not generated")).to_be_visible()
        expect(page.get_by_text("Use Rebuild catalog above.")).to_be_visible()
        page.get_by_role("button", name="Rebuild catalog").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_label("Reason (kept in the audit trail)")).to_have_count(
            0
        )  # takes none
        dialog.get_by_role("button", name="Rebuild catalog").click()
        expect(
            page.get_by_role("status").filter(has_text="The catalog was rebuilt.")
        ).to_be_visible()
        expect(page.get_by_role("tree", name="Catalog objects")).to_be_visible()
        expect(page.get_by_role("heading", name="default catalog")).to_be_visible()
        expect(page.get_by_text("Pipelines", exact=True).first).to_be_visible()
        expect(page.get_by_text("catalog is not generated")).to_have_count(0)
        page.get_by_role("button", name="Validate metadata").click()
        expect(
            page.get_by_text("Checked 2 pipeline(s)").or_(page.get_by_text("Checked 1 pipeline(s)"))
        ).to_be_visible()
        shoot(page, "catalog")
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_pages_render_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    _, url = scene
    pages = {
        "insights": "/ui/projects/default",
        "console": "/ui/projects/default/console",
        "catalog": "/ui/projects/default/catalog",
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
        assert [p for p in problems if "status of 404" not in p] == []
        browser.close()


def test_platform_lists_the_projects_and_the_old_insights_address_opens_home(scene):
    _, url = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 800})
        sign_in(page, url, "/ui/projects/default")
        page.get_by_role("link", name="Projects", exact=True).click()
        expect(page.get_by_role("heading", name="Projects", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="default", exact=True)).to_be_visible()
        shoot(page, "projects")
        page.goto(url + "/ui/projects/default/insights?pipeline=ORDERS")
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        assert page.url.endswith("/ui/projects/default?pipeline=ORDERS")
        assert problems == []
        browser.close()
