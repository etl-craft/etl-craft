"""The React pipelines, pipeline, scheduled and held pages in a real browser."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_ui import open_page, sign_in

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


@pytest.fixture
def scene(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        for code, tags, schedule in (
            ("OPS", ["team:ops", "tier:gold"], "0 * * * *"),
            ("SALES", ["team:sales"], None),
        ):
            pipeline = add_pipeline(conn, code)
            conn.execute(
                text(
                    "UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS=:params, RUN_SCHEDULE=:schedule "
                    "WHERE PIPELINE_ID=:id"
                ),
                {"params": json.dumps({"TAGS": tags}), "schedule": schedule, "id": pipeline},
            )
            extract = add_task(conn, pipeline, "EXTRACT")
            load = add_task(conn, pipeline, "LOAD")
            add_dependency(conn, pipeline, load, extract)
            run = start_run(conn, pipeline)
            task_run(conn, extract, run)
            task_run(conn, load, run)
            finish_run(conn, run)
        sales = conn.execute(
            text("SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE='SALES'")
        ).scalar_one()
        active = start_run(conn, sales)
    return ctx, url, active


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


def test_filter_by_tag_select_pause_and_export(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines")
        table = page.get_by_role("table", name="Pipelines")
        expect(table.get_by_role("link", name="OPS")).to_be_visible()
        expect(table.get_by_role("link", name="SALES")).to_be_visible()
        page.get_by_role("button", name="Tags").click()
        page.get_by_role("checkbox", name="team:ops").click()
        page.keyboard.press("Escape")
        expect(table.get_by_role("link", name="SALES")).to_have_count(0)
        assert "tag=team%3Aops" in page.url
        page.reload()
        expect(page.get_by_role("button", name="Tags (1 selected)")).to_be_visible()
        page.get_by_role("button", name="Tags (1 selected)").click()
        page.get_by_role("button", name="Clear", exact=True).click()  # clear the filter
        page.keyboard.press("Escape")
        expect(table.get_by_role("link", name="SALES")).to_be_visible()
        shoot(page, "pipelines")

        table.get_by_label("Select SALES").check()
        expect(page.get_by_text("1 selected")).to_be_visible()
        page.get_by_role("button", name="Pause selected").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("SALES")).to_be_visible()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("month-end freeze")
        dialog.get_by_role("button", name="Pause selected").click()
        expect(page.get_by_role("status").filter(has_text="1 requested")).to_be_visible()
        expect(table.get_by_text("month-end freeze")).to_be_visible()

        with page.expect_download() as download:
            page.get_by_role("button", name="Export CSV").click()
        content = Path(download.value.path()).read_text(encoding="utf-8")
        assert content.startswith(
            "pipeline,name,tags,schedule,next_run,automatic_runs,paused_tasks"
        )
        assert "SALES" in content and "paused by owner: month-end freeze" in content
        assert problems == []
        browser.close()


def test_a_pipeline_pauses_resumes_and_links_to_its_runs_and_tasks(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("heading", name="OPS")).to_be_visible()
        expect(page.get_by_text("Active")).to_be_visible()
        expect(page.get_by_role("table", name="Run grid")).to_be_visible()
        shoot(page, "pipeline-runs")
        page.get_by_role("button", name="Pause", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("investigate")
        dialog.get_by_role("button", name="Pause", exact=True).click()
        expect(page.get_by_text("by owner: investigate")).to_be_visible()
        page.get_by_role("button", name="Resume", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("fixed")
        dialog.get_by_role("button", name="Resume", exact=True).click()
        expect(page.get_by_text("Active")).to_be_visible()

        page.get_by_role("button", name="Graph", exact=True).click()
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("EXTRACT")).to_be_visible()
        graph.get_by_text("LOAD", exact=True).click()
        expect(graph.locator("[data-focus=focus]")).to_have_count(1)
        expect(graph.locator("[data-focus=lineage]")).to_have_count(1)
        shoot(page, "pipeline-tasks")
        assert problems == []
        browser.close()


def test_run_now_asks_for_a_reason_and_names_the_project(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        page.get_by_role("button", name="Run now").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("default")).to_be_visible()
        expect(dialog.get_by_role("button", name="Run now")).to_be_disabled()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("rerun")
        expect(dialog.get_by_role("button", name="Run now")).to_be_enabled()
        browser.close()


def test_scheduled_and_held_pages_list_work_and_release_a_hold(scene):
    ctx, url, active = scene
    act(
        ctx,
        ActionName.CONTROL,
        pipeline_code="SALES",
        run_id=active,
        action="HOLD",
        reason="check totals",
    )
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/scheduled")
        nxt = page.get_by_role("table", name="Next runs")
        expect(nxt.get_by_role("link", name="OPS")).to_be_visible()
        expect(nxt.get_by_role("link", name="SALES")).to_have_count(0)  # not scheduled
        shoot(page, "scheduled")
        page.goto(url + "/ui/projects/default/held")
        held = page.get_by_role("table", name="Held runs and tasks")
        expect(held.get_by_text("check totals")).to_be_visible()
        shoot(page, "held")
        held.get_by_role("button", name="Release").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("totals checked")
        dialog.get_by_role("button", name="Release").click()
        expect(page.get_by_text("Nothing is held.")).to_be_visible()
        assert problems == []
        browser.close()


def test_a_viewer_can_read_the_pipelines_but_not_change_them(scene):
    ctx, url, _ = scene
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
        sign_in(page, url, "/ui/projects/default/pipelines", name="alice")
        table = page.get_by_role("table", name="Pipelines")
        expect(table.get_by_role("link", name="OPS")).to_be_visible()
        expect(table.get_by_role("checkbox")).to_have_count(0)
        page.goto(url + "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("heading", name="OPS")).to_be_visible()
        for name in ("Run now", "Pause", "Resume"):
            expect(page.get_by_role("button", name=name, exact=True)).to_have_count(0)
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_pipeline_pages_render_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    ctx, url, active = scene
    act(
        ctx,
        ActionName.CONTROL,
        pipeline_code="SALES",
        run_id=active,
        action="HOLD",
        reason="check totals",
    )
    act(ctx, ActionName.CONTROL, pipeline_code="SALES", action="PAUSE", reason="freeze")
    pages = {
        "pipelines": "/ui/projects/default/pipelines",
        "pipeline": "/ui/projects/default/pipelines/OPS",
        "pipeline-tasks": "/ui/projects/default/pipelines/OPS?tab=tasks",
        "scheduled": "/ui/projects/default/scheduled",
        "held": "/ui/projects/default/held",
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
        assert problems == []
        browser.close()


def test_the_panes_resize_and_the_graph_stays_whole(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS?view=graph")
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("EXTRACT")).to_be_visible()
        divider = page.get_by_role("separator", name="Resize the panes")
        before = int(divider.get_attribute("aria-valuenow"))
        box = divider.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + 240, box["y"] + box["height"] / 2, steps=5)
        page.mouse.up()
        assert int(divider.get_attribute("aria-valuenow")) > before
        divider.focus()
        page.keyboard.press("Home")
        assert int(divider.get_attribute("aria-valuenow")) == before
        expect(graph.get_by_text("EXTRACT")).to_be_visible()  # a resize refits the graph
        page.get_by_role("button", name="Horizontal").click()
        assert "flow=lr" in page.url
        assert problems == []
        browser.close()


def test_a_pipeline_has_an_overview_tasks_details_and_documentation(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("tab", name="Overview")).to_have_attribute("aria-selected", "true")
        expect(page.get_by_text("Failed runs", exact=True)).to_be_visible()
        page.get_by_role("tab", name="Tasks").click()
        expect(
            page.get_by_role("table", name="Pipeline tasks").get_by_role("link")
        ).not_to_have_count(0)
        page.get_by_role("tab", name="Details").click()
        expect(page.get_by_text("Refresh", exact=True).last).to_be_visible()
        page.get_by_role("tab", name="Documentation").click()
        expect(page.get_by_text("About this pipeline")).to_be_visible()
        expect(page.get_by_role("region", name="Task documentation")).to_be_visible()
        assert problems == []
        browser.close()
