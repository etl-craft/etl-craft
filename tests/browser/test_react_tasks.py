"""The task history, attempt, items and matrix pages, and run and task controls, in a browser."""

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
ERROR = "connection reset by source"


@pytest.fixture
def scene(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ORDERS")
        extract = add_task(conn, pipeline, "EXTRACT")
        load = add_task(conn, pipeline, "LOAD")
        add_dependency(conn, pipeline, load, extract)
        good = start_run(conn, pipeline)
        task_run(conn, extract, good)
        task_run(conn, load, good)
        finish_run(conn, good)
        for _ in range(26):  # a matrix wider than its card must scroll inside the card
            older = start_run(conn, pipeline)
            task_run(conn, extract, older)
            task_run(conn, load, older)
            finish_run(conn, older)
        bad = start_run(conn, pipeline)
        task_run(conn, extract, bad)
        summary = transitions.find_or_create_task_run(conn, load, bad).task_run_id
        failed = attempt(conn, summary, fail=ERROR)
        transitions.finish_task_run(conn, summary, status=RunStatus.FAILED)
        finish_run(conn, bad, "FAILED")
    return ctx, url, good, bad, failed


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


def test_a_failed_task_explains_itself_and_leads_to_its_attempt_and_history(scene):
    _, url, _, bad, failed = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        page.context.set_default_timeout(8000)
        sign_in(page, url, f"/ui/projects/default/runs/ORDERS/{bad}")
        page.get_by_role("table", name="Run grid").get_by_role(
            "img", name=f"LOAD in run {bad}: failed"
        ).click()
        panel = page.get_by_label("Task LOAD")
        expect(panel.get_by_text(ERROR).first).to_be_visible()
        expect(panel.get_by_text("Dependencies")).to_be_visible()
        expect(panel.get_by_text("EXTRACT")).to_be_visible()
        expect(panel.get_by_role("button", name="Mark as")).to_be_visible()
        shoot(page, "run-task-panel")
        panel.get_by_role("link", name="Open attempt 1").click()
        expect(page.get_by_role("heading", name="Attempt 1 of LOAD")).to_be_visible()
        expect(page.get_by_text(f"attempt id {failed}")).to_have_count(0)
        page.get_by_text("Process details").click()  # internals sit behind one disclosure
        expect(page.get_by_text("Attempt id", exact=True)).to_be_visible()
        expect(page.get_by_text("How the process ended")).to_be_visible()
        expect(page.get_by_text(ERROR).first).to_be_visible()
        shoot(page, "attempt")
        page.get_by_role("link", name="Task history").click()
        expect(page.get_by_role("heading", name="LOAD")).to_be_visible()
        expect(page.get_by_text("27 of 28")).to_be_visible()
        assert problems == []
        browser.close()


def test_the_task_history_lists_runs_with_counts_and_exports_csv(scene):
    _, url, good, bad, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/ORDERS/tasks/LOAD")
        table = page.get_by_role("table", name="Task runs")
        expect(table.get_by_role("link", name=f"#{good}", exact=True)).to_be_visible()
        expect(table.get_by_role("link", name=f"#{bad}", exact=True)).to_be_visible()
        expect(page.get_by_text("Handler")).to_be_visible()
        shoot(page, "task")
        with page.expect_download() as download:
            page.get_by_role("button", name="Export CSV").click()
        content = Path(download.value.path()).read_text(encoding="utf-8")
        assert content.startswith("run,status,started,seconds,rows_in")
        assert problems == []
        browser.close()


def test_the_grid_shows_every_task_against_recent_runs(scene):
    _, url, _, bad, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, "/ui/projects/default/pipelines/ORDERS")
        matrix = page.get_by_role("table", name="Run grid")
        expect(matrix.get_by_role("img", name=f"LOAD in run {bad}: failed")).to_be_visible()
        expect(matrix.get_by_role("img", name=f"LOAD in run {bad - 1}: success")).to_be_visible()
        expect(matrix.get_by_role("img", name=f"EXTRACT in run {bad}: success")).to_be_visible()
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"the matrix scrolls the page sideways by {overflow}px"
        shoot(page, "matrix")
        page.get_by_role("tab", name="Runs").click()
        page.get_by_label("Failure class").select_option("TRANSIENT")
        assert "failure_class=TRANSIENT" in page.url
        assert problems == []
        browser.close()


def test_the_items_page_says_when_a_task_recorded_none(scene):
    _, url, _, bad, _ = scene
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        page.context.set_default_timeout(8000)
        sign_in(page, url, f"/ui/projects/default/runs/ORDERS/{bad}/tasks/LOAD/items")
        expect(page.get_by_role("heading", name="Items of LOAD")).to_be_visible()
        expect(
            page.get_by_text("This task run recorded no items.").or_(page.get_by_role("alert"))
        ).to_be_visible()
        browser.close()


def test_a_viewer_reads_task_pages_without_controls(scene):
    ctx, url, _, bad, _ = scene
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
        page.context.set_default_timeout(8000)
        sign_in(page, url, f"/ui/projects/default/runs/ORDERS/{bad}", name="alice")
        page.get_by_role("table", name="Run grid").get_by_role(
            "img", name=f"LOAD in run {bad}: failed"
        ).click()
        expect(page.get_by_label("Task LOAD").get_by_text(ERROR).first).to_be_visible()
        expect(page.get_by_role("button", name="Mark as")).to_have_count(0)
        expect(page.get_by_role("button", name="Hold")).to_have_count(0)
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_task_pages_render_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    _, url, _, bad, failed = scene
    pages = {
        "task": "/ui/projects/default/pipelines/ORDERS/tasks/LOAD",
        "attempt": f"/ui/projects/default/runs/ORDERS/{bad}/tasks/LOAD/attempts/{failed}",
        "matrix": "/ui/projects/default/pipelines/ORDERS",
        "items": f"/ui/projects/default/runs/ORDERS/{bad}/tasks/LOAD/items",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        page.context.set_default_timeout(8000)
        sign_in(page, url)
        for name, path in pages.items():
            page.goto(url + path)
            page.wait_for_load_state("networkidle")
            expect(page.locator("main")).to_be_visible()
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 0, f"{name} scrolls sideways by {overflow}px at {width}px"
            shoot(page, f"{name}-{scheme}-{width}")
        assert [p for p in problems if "status of 4" not in p] == []
        browser.close()


def test_a_skipped_task_names_its_failed_upstream(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "SKIP_REASON")
        source = add_task(conn, pipeline, "SOURCE")
        load = add_task(conn, pipeline, "LOAD")
        add_dependency(conn, pipeline, load, source)
        run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, source, run).task_run_id
        attempt(conn, summary, fail="source unavailable")
        transitions.finish_task_run(conn, summary, status=RunStatus.FAILED)
        task_run(conn, load, run, RunStatus.SKIPPED)
        finish_run(conn, run, RunStatus.FAILED)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, f"/ui/projects/default/runs/SKIP_REASON/{run}")
        expect(
            page.get_by_role("table", name="Task list").get_by_text("Skipped: SOURCE failed")
        ).to_be_visible()
        assert problems == []
        browser.close()
