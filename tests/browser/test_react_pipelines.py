"""The React pipelines, pipeline, scheduled and held pages in a real browser."""

import csv
import io
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_ui import open_page, pause_item, sign_in, wait_for_fonts

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, RunStatus
from etl_craft.engine import transitions
from etl_craft.execution.attempt_records import attempt_log_path
from fixtures.actions import act
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_pipeline_dependency,
    add_task,
    finish_run,
    start_run,
    task_run,
)
from fixtures.run_scene import attempt

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
        page.screenshot(path=f"{shots}/{name}.png", animations="disabled")


def test_filter_by_tag_select_pause_and_export(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines")
        table = page.get_by_role("table", name="Pipelines")
        expect(table.get_by_role("link", name="OPS")).to_be_visible()
        expect(table.get_by_role("link", name="SALES")).to_be_visible()
        page.get_by_role("group", name="Filter by tag").get_by_role("button", name="Tags").click()
        page.get_by_role("checkbox", name="team:ops").click()
        page.keyboard.press("Escape")
        expect(table.get_by_role("link", name="SALES")).to_have_count(0)
        assert "tag=team%3Aops" in page.url
        page.reload()
        expect(
            page.get_by_role("group", name="Filter by tag").get_by_role(
                "button", name="Tags (1 selected)"
            )
        ).to_be_visible()
        page.get_by_role("group", name="Filter by tag").get_by_role(
            "button", name="Tags (1 selected)"
        ).click()
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
        exported = csv.DictReader(io.StringIO(content))
        assert {
            "pipeline",
            "name",
            "description",
            "tags",
            "schedule",
            "dependencies",
            "last_run",
            "next_run",
            "automatic_runs",
            "paused_tasks",
        } <= set(exported.fieldnames or ())
        assert next(exported)["last_run"]
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
        expect(page.get_by_text("Active", exact=True).first).to_be_visible()
        expect(page.get_by_role("table", name="Run grid")).to_be_visible()
        shoot(page, "pipeline-runs")
        pause_item(page, "Pause").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("investigate")
        dialog.get_by_role("button", name="Pause", exact=True).click()
        expect(page.get_by_text("by owner: investigate").first).to_be_visible()
        pause_item(page, "Resume").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("fixed")
        dialog.get_by_role("button", name="Resume", exact=True).click()
        expect(page.get_by_text("Active", exact=True).first).to_be_visible()

        page.get_by_role("button", name="Graph", exact=True).click()
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("EXTRACT")).to_be_visible()
        load = graph.locator('[data-id="LOAD"]')
        header = load.get_by_role("button", name="Expand LOAD", exact=True)
        header.click()
        expect(load.get_by_role("button", name="Collapse LOAD", exact=True)).to_be_visible()
        load.click(position={"x": 2, "y": 2})
        expect(graph.locator("[data-focus=focus]")).to_have_count(1)
        expect(graph.locator("[data-focus=lineage]")).to_have_count(1)
        shoot(page, "pipeline-tasks")
        assert problems == []
        browser.close()


def test_run_now_allows_an_optional_reason_and_names_the_project(scene):
    ctx, url, _ = scene
    act(
        ctx,
        ActionName.PROJECT_SET,
        project="default",
        governance="RELAXED",
        reason="set test policy",
    )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        page.get_by_role("button", name="Run now").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("default")).to_be_visible()
        expect(dialog.get_by_role("button", name="Run now")).to_be_enabled()
        dialog.get_by_label("Reason (kept in the audit trail) (optional)").fill("rerun")
        expect(dialog.get_by_role("button", name="Run now")).to_be_enabled()
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_a_full_refresh_warns_before_emptying_a_target_and_waits_for_acceptance(
    scene, scheme, width
):
    ctx, url, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "REFRESHED")
        add_task(
            conn,
            pipeline,
            "load",
            "SQL",
            TARGET_OBJECT="mart.orders",
            SQL_ACTION="APPEND_TABLE",
            WATERMARK_COLUMN="id",
            WATERMARK_TYPE="NUMBER",
            WATERMARK_START="0",
            SELECT_QUERY="SELECT 1 AS id",
        )
    act(ctx, ActionName.PROJECT_SET, project="default", governance="RELAXED", reason="test")
    with sync_playwright() as pw:
        browser, page, _ = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 1000}
        )
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/REFRESHED")
        page.get_by_role("button", name="Run now").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("switch", name="Full refresh, once").click()
        dialog.get_by_label("Reason (kept in the audit trail) (optional)").fill("profile fixed")
        submit = dialog.get_by_role("button", name="Run now")
        submit.click()
        # The server names what would be emptied; nothing was run, and the switch is now needed.
        warning = dialog.get_by_role("alert")
        expect(warning).to_contain_text("mart.orders")
        expect(warning).to_contain_text("cannot restore")
        expect(warning).not_to_contain_text("--yes")  # the CLI's wording stays out of the page
        accept = dialog.get_by_role("switch", name="Empty mart.orders first, then load it again")
        expect(submit).to_be_disabled()
        shoot(page, f"full-refresh-warning-{scheme}-{width}")
        accept.click()
        expect(submit).to_be_enabled()
        # Wait for the answer: closing the browser first can abort the request before it commits.
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/runs")
        ) as sent:
            submit.click()
        body = sent.value.request.post_data_json
        assert body["full_refresh"] is True and body["empty_targets"] == ["mart.orders"]
        assert body["reason"] == "profile fixed" and "task_code" not in body
        browser.close()
    with ctx.engine.connect() as conn:
        plan = conn.execute(
            text(
                "SELECT l.FULL_REFRESH_PLAN AS plan FROM AUD_PIPELINES_RUN_LOG l "
                "JOIN CFG_PIPELINES p ON p.PIPELINE_ID=l.PIPELINE_ID "
                "WHERE p.PIPELINE_CODE='REFRESHED'"
            )
        ).scalar_one_or_none()
    # Whatever happened to execution, the confirmed plan is what was recorded.
    assert plan is not None and json.loads(plan)["empty_targets"] == ["mart.orders"]


def test_scheduled_and_paused_pages_list_work_and_resume_a_pause(scene):
    ctx, url, _ = scene
    act(
        ctx,
        ActionName.CONTROL,
        pipeline_code="SALES",
        action="PAUSE",
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
        held = page.get_by_role("table", name="Paused pipelines")
        expect(held.get_by_text("check totals")).to_be_visible()
        shoot(page, "held")
        pause_item(held, "Resume", pipeline="SALES").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("totals checked")
        dialog.get_by_role("button", name="Resume").click()
        expect(page.get_by_text("No pipeline is paused.")).to_be_visible()
        assert problems == []
        browser.close()


def test_a_viewer_can_read_the_pipelines_but_not_change_them(scene):
    ctx, url, _ = scene
    act(
        ctx,
        ActionName.ACCESS_GRANT,
        project="default",
        account="alice",
        role="CAN_VIEW",
        reason="read",
    )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines", name="alice")
        table = page.get_by_role("table", name="Pipelines")
        expect(table.get_by_role("link", name="OPS")).to_be_visible()
        for name in (
            "Pause selected",
            "Resume selected",
        ):  # selecting rows is allowed; bulk actions are not
            expect(page.get_by_role("button", name=name, exact=True)).to_be_disabled()
        page.goto(url + "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("heading", name="OPS")).to_be_visible()
        expect(
            page.get_by_role("button", name="Run now", exact=True)
        ).to_be_disabled()  # grayed out, not hidden
        pause_menu = page.get_by_role("button", name="Pause options for OPS", exact=True)
        pause_menu.click()  # the Pause menu is open to a viewer; its actions are grayed out
        for name in ("Pause", "Resume", "Replace pause"):
            expect(page.get_by_role("menuitem", name=name, exact=True)).to_have_attribute(
                "aria-disabled", "true"
            )
        page.keyboard.press("Escape")
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_pipeline_pages_render_cleanly_in_both_themes_and_on_a_phone(scene, scheme, width):
    ctx, url, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipelines = dict(
            conn.execute(text("SELECT PIPELINE_CODE, PIPELINE_ID FROM CFG_PIPELINES"))
            .tuples()
            .all()
        )
        add_pipeline_dependency(conn, pipelines["OPS"], pipelines["SALES"], "HAS_DATA")
    act(
        ctx,
        ActionName.CONTROL,
        pipeline_code="SALES",
        action="PAUSE",
        reason="check totals",
    )
    pages = {
        "pipelines": "/ui/projects/default/pipelines",
        "pipeline": "/ui/projects/default/pipelines/OPS",
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
            if name == "pipeline":
                expect(page.get_by_text("Starts when", exact=True)).to_be_visible()
                expect(page.get_by_text("SALES.HAS_DATA", exact=True)).to_be_visible()
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


def test_a_pipeline_keeps_task_definitions_and_catalog_links_in_the_grid(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("tab", name="Overview", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        expect(page.get_by_text("Failed runs", exact=True)).to_be_visible()
        page.get_by_role("button", name="Task definition for EXTRACT", exact=True).click()
        dialog = page.get_by_role("dialog", name="Task definition · EXTRACT")
        expect(dialog.get_by_text("Handler", exact=True)).to_be_visible()
        expect(
            dialog.get_by_role("link", name="Task history, definition and parameters")
        ).to_have_attribute("href", "/ui/projects/default/pipelines/OPS/tasks/EXTRACT")
        page.keyboard.press("Escape")
        expect(
            page.get_by_role("link", name="About this pipeline in the catalog")
        ).to_have_attribute("href", "/ui/projects/default/catalog/pipelines/OPS")
        for name in ("Tasks", "Details", "Calendar", "Docs"):
            expect(page.get_by_role("tab", name=name, exact=True)).to_have_count(0)
        crumbs = page.get_by_role("navigation", name="Breadcrumb")
        crumbs.get_by_role("link", name="Pipelines").click()
        expect(page.get_by_role("table", name="Pipelines")).to_be_visible()
        back = page.get_by_role("banner").get_by_role("button", name="Back", exact=True)
        back.click()
        expect(page).to_have_url(url + "/ui/projects/default/pipelines/OPS")
        back.click()  # the app was opened on OPS: Back goes up to the project's home
        expect(page).to_have_url(url + "/ui/projects/default")
        expect(back).to_be_disabled()
        assert problems == []
        browser.close()


def test_a_narrow_grid_hides_the_oldest_runs_never_the_newest(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1100, "height": 800})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/SALES")
        divider = page.get_by_role("separator", name="Resize the panes")
        divider.focus()
        for _ in range(30):
            page.keyboard.press("ArrowLeft")  # the grid pane at its narrowest
        grid = page.get_by_role("table", name="Run grid")
        headers = grid.locator("thead th a")
        headers.first.wait_for()  # the runs are drawn once their history has loaded
        assert headers.count() >= 2
        area = grid.locator("xpath=parent::div").bounding_box()
        newest = headers.last.bounding_box()
        assert newest["x"] + newest["width"] <= area["x"] + area["width"] + 1, (
            "the newest run is cut off"
        )
        assert newest["x"] >= area["x"], "the newest run is outside the grid"
        task = page.get_by_role("table", name="Run grid").locator("tbody th").first.bounding_box()
        assert task["x"] >= 0 and task["width"] >= 120  # the task list keeps a readable width
        assert problems == []
        browser.close()


@pytest.mark.parametrize("method", ["keyboard", "pointer"])
@pytest.mark.parametrize("labels", ["id", "time"])
def test_one_grid_divider_fits_names_and_keeps_the_latest_run_visible(site, method, labels):
    ctx, url = site
    name = "load_customer_and_product_relationship_history"
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "RESIZE")
        task = add_task(conn, pipeline, name)
        for _ in range(12):
            run = start_run(conn, pipeline)
            task_run(conn, task, run)
            finish_run(conn, run)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 800})
        sign_in(page, url, f"/ui/projects/default/pipelines/RESIZE?columns={labels}")
        outer = page.get_by_role("separator", name="Resize the panes")
        grid = page.get_by_role("table", name="Run grid")
        task_cell = grid.get_by_role("rowheader").filter(has_text=name)
        area = grid.locator("xpath=parent::div")
        expect(grid.locator("thead th a").first).to_be_visible()
        expect(page.get_by_role("separator")).to_have_count(1)

        def resize_grid(wide):
            if method == "keyboard":
                for _ in range(30):
                    outer.press("ArrowRight" if wide else "ArrowLeft")
            else:
                box = outer.bounding_box()
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 30)
                page.mouse.down()
                page.mouse.move(1100 if wide else 250, box["y"] + 30, steps=8)
                page.mouse.up()

        def latest_visible():
            # Inner widths follow the outer divider through ResizeObserver.
            page.wait_for_function(
                """([viewport, latest]) => {
                    const box = viewport.getBoundingClientRect();
                    const item = latest.getBoundingClientRect();
                    return viewport.isConnected && latest.isConnected
                        && box.width > 0 && item.width > 0
                        && item.left >= box.left - 1 && item.right <= box.right + 1;
                }""",
                arg=[area.element_handle(), grid.locator("thead th a").last.element_handle()],
                timeout=5000,
            )

        resize_grid(False)
        expect(task_cell).to_have_attribute("title", name)
        latest_visible()
        resize_grid(True)
        expect(task_cell).to_be_visible()
        latest_visible()
        shoot(page, f"grid-expanded-{method}-{labels}")
        resize_grid(False)
        expect(task_cell).to_have_attribute("title", name)
        latest_visible()
        shoot(page, f"grid-narrowed-{method}-{labels}")
        assert problems == []
        browser.close()


def test_the_top_search_groups_matches_as_you_type_and_opens_one(scene):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines")
        box = page.get_by_role("combobox", name="Search pipelines, tasks, tables and runs")
        box.fill("OPS")
        matches = page.get_by_role("listbox", name="Matches")
        expect(matches.get_by_role("group", name="Pipelines")).to_be_visible()
        box.press("ArrowDown")
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"/pipelines/OPS"))
        # Enter with nothing picked lists every result
        box.fill("SALES")
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"/search\?q=SALES"))
        assert problems == []
        browser.close()


def test_the_newest_grid_run_is_on_the_right_with_readable_status_symbols(scene):
    _, url, active = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        histories = []
        page.on(
            "request",
            lambda request: (
                histories.append(request.url)
                if "/projects/default/history?" in request.url
                else None
            ),
        )
        sign_in(page, url, "/ui/projects/default/pipelines/SALES")
        newest = page.get_by_role("table", name="Run grid").locator("thead th a").last
        expect(newest).to_have_attribute("href", re.compile(rf"/runs/SALES/{active}$"))
        square = (
            page.get_by_role("table", name="Run grid")
            .get_by_role("img", name=re.compile("success$"))
            .first
        )
        expect(square).to_be_visible()
        assert len(histories) == 1 and "cells=true" in histories[0]
        size = square.bounding_box()
        assert size["width"] == 14 and size["height"] == 14
        assert problems == []
        browser.close()


def test_run_and_task_history_show_stored_labels_with_numeric_links(scene):
    ctx, url, _ = scene
    with ctx.engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS id, RUN_LABEL AS label FROM AUD_PIPELINES_RUN_LOG "
                "WHERE PIPELINE_ID=(SELECT PIPELINE_ID FROM CFG_PIPELINES "
                "WHERE PIPELINE_CODE='OPS')"
            )
        ).one()
        task = conn.execute(
            text(
                "SELECT TASK_RUN_ID AS id, TASK_RUN_LABEL AS label FROM AUD_TASK_RUN_LOG "
                "WHERE PIPELINE_RUN_ID=:id ORDER BY TASK_RUN_ID"
            ),
            {"id": run.id},
        ).first()
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS/tasks/EXTRACT")
        table = page.get_by_role("table", name="Task runs")
        expect(table.get_by_text(run.label, exact=True)).to_be_visible()
        expect(table.get_by_text(task.label, exact=True)).to_be_visible()
        link = table.get_by_role("link", name=f"#{run.id}", exact=True)
        expect(link).to_have_attribute("href", re.compile(rf"/runs/OPS/{run.id}$"))
        link.click()
        heading = page.get_by_role("heading", name=f"Run #{run.id}", exact=True)
        expect(heading.locator("[title]")).to_have_attribute("title", run.label)
        page.evaluate(
            "navigator.clipboard.writeText = async (text) => { window.copiedLabel = text; }"
        )
        page.get_by_role("button", name="Copy id", exact=True).click()
        import shlex

        assert shlex.split(page.evaluate("window.copiedLabel")) == [run.label]
        assert page.evaluate("window.copiedLabel").startswith("'")
        page.goto(f"{url}/ui/projects/default/runs")
        expect(
            page.get_by_role("table", name="Runs").get_by_text(run.label, exact=True)
        ).to_be_visible()
        assert not problems
        browser.close()


def test_fit_view_keeps_task_labels_readable_after_zooming_out(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "LEGIBLE")
        previous = None
        for number in range(12):
            task = add_task(conn, pipeline, f"TASK_{number:02d}")
            if previous is not None:
                add_dependency(conn, pipeline, task, previous)
            previous = task
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        sign_in(page, url, "/ui/projects/default/pipelines/LEGIBLE?view=graph&flow=lr")
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("TASK_00", exact=True)).to_have_count(1)
        zoom = (
            "() => new DOMMatrixReadOnly(getComputedStyle("
            "document.querySelector('.react-flow__viewport')).transform).a"
        )
        page.wait_for_function(f"{zoom} >= 0.699")
        for _ in range(
            2
        ):  # the readable fit starts at 100%, so one 1.2x step stays above the floor
            graph.get_by_role("button", name="Zoom out", exact=True).click()
        page.wait_for_function(f"{zoom} < 0.699")
        graph.get_by_role("button", name="Fit view", exact=True).click()
        page.wait_for_function(f"{zoom} >= 0.699")
        shoot(page, "graph-readable-fit")
        assert not problems
        browser.close()


def test_run_dialog_follows_governance_and_keeps_production_confirmation(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "REASONS")
        add_task(conn, pipeline, "T", "PYTHON")
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines/REASONS")
        expect(page.get_by_role("button", name="Run now", exact=True)).to_be_visible()
        wait_for_fonts(page)
        for environment, governance in (("DEV", "STRICT"), ("DEV", "RELAXED"), ("PROD", "STRICT")):
            act(
                ctx,
                ActionName.PROJECT_SET,
                project="default",
                environment_type=environment,
                governance=governance,
                reason="set test governance",
            )
            page.goto(url + "/ui/projects/default/pipelines/REASONS")
            wait_for_fonts(page)
            page.get_by_role("button", name="Run now", exact=True).click()
            dialog = page.get_by_role("dialog")
            reason = dialog.get_by_label("Reason", exact=False)
            submit = dialog.get_by_role("button", name="Run now", exact=True)
            if governance == "RELAXED":
                expect(reason).not_to_have_attribute("required", "")
                expect(submit).to_be_enabled()
            else:
                expect(reason).to_have_attribute("required", "")
                expect(submit).to_be_disabled()
                reason.fill("start the approved load")
                if environment == "PROD":
                    expect(submit).to_be_disabled()
                    dialog.get_by_label("This is PRODUCTION.", exact=False).fill("default")
                expect(submit).to_be_enabled()
            shoot(page, f"reason-{environment}-{governance}")
            dialog.get_by_role("button", name="Cancel").click()
        assert problems == []
        browser.close()


@pytest.mark.parametrize(
    "appearance,width", [("light", 1280), ("dark", 1280), ("light", 390), ("dark", 390)]
)
def test_run_now_records_task_inputs_through_the_shared_operation(scene, appearance, width):
    ctx, url, _ = scene
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "PARAMETERS")
        add_task(conn, pipeline, "load", "PYTHON", INPUT_PARAMS='{"day":1}')
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 900})
        page.emulate_media(color_scheme=appearance)
        sign_in(page, url, "/ui/projects/default/pipelines/PARAMETERS")
        page.get_by_role("button", name="Run now", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Task input overrides (optional)").fill('load.INPUT_PARAMS={"day":2}')
        dialog.get_by_label("Submission key").fill("browser-inputs")
        dialog.get_by_label(re.compile("Reason")).fill("one-off input")
        shoot(page, f"run-overrides-{appearance}-{width}")
        with page.expect_response(
            lambda response: response.url.endswith("/runs") and response.request.method == "POST"
        ) as response:
            dialog.get_by_role("button", name="Run now", exact=True).click()
        assert response.value.ok, response.value.text()
        run = response.value.json()["run"]
        assert run["parameter_overrides"] == {"load": {"INPUT_PARAMS": '{"day":2}'}}
        with ctx.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT REQUEST_KEY AS key,CREATED_BY AS actor FROM "
                    "AUD_RUN_PARAMETER_OVERRIDES WHERE PIPELINE_RUN_ID=:run"
                ),
                {"run": run["pipeline_run_id"]},
            ).one()
            assert row.key == "browser-inputs" and row.actor == "owner"
        page.goto(f"{url}/ui/projects/default/runs/PARAMETERS/{run['pipeline_run_id']}")
        expect(page.get_by_role("region", name="Recorded task inputs")).to_be_visible()
        expect(page.get_by_text("load.INPUT_PARAMS", exact=True)).to_be_visible()
        shoot(page, f"run-input-values-{appearance}-{width}")
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_pipeline_manager_delegates_only_here_and_revokes_with_audit(scene, scheme, width):
    ctx, url, _ = scene
    baseline = act(ctx, ActionName.ACCESS_LIST, project="default").bindings
    for target, permission in ((None, "CAN_VIEW"), ("OPS", "CAN_MANAGE")):
        act(
            ctx,
            ActionName.ACCESS_GRANT,
            project="default",
            account="alice",
            pipeline=target,
            role=permission,
            reason="Delegate pipeline management",
        )
    with sync_playwright() as pw:
        browser, page, _ = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        sign_in(page, url, "/ui/projects/default/pipelines/OPS?tab=access", name="alice")
        expect(page.get_by_role("tab", name="Access", exact=True)).to_be_visible()
        page.get_by_role("button", name="Grant access", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("default", exact=True)).to_be_visible()
        expect(dialog.get_by_text("All projects", exact=True)).to_have_count(0)
        expect(dialog.get_by_label("Pipeline", exact=True)).to_have_count(0)
        expect(dialog.get_by_label("Tag", exact=True)).to_have_count(0)
        dialog.get_by_label("Every account with role", exact=False).select_option("operator")
        dialog.get_by_label(re.compile(r"^Role")).select_option("CAN_RUN")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Operations team")
        shoot(page, f"pipeline-grant-dialog-{scheme}-{width}")
        dialog.get_by_role("button", name="Grant access", exact=True).click()
        table = page.get_by_role("table", name="Access bindings")
        row = table.get_by_role("row").filter(has_text="every operator")
        expect(row).to_contain_text("CAN_RUN")
        expect(row).to_contain_text("pipeline OPS")
        shoot(page, f"pipeline-grants-{scheme}-{width}")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        heading = page.get_by_role("heading", name=re.compile("Access to OPS"))
        assert heading.bounding_box()["x"] >= 0

        # A forged target still goes to the real operation; its refusal stays in the dialog.
        for target in ("SALES", None):

            def forge(route, request, selected=target):
                payload = request.post_data_json
                payload.pop("pipeline", None)
                if selected is not None:
                    payload["pipeline"] = selected
                route.continue_(post_data=json.dumps(payload))

            page.route("**/api/v1/access/grants", forge)
            page.get_by_role("button", name="Grant access", exact=True).click()
            dialog.get_by_label("Every account with role", exact=False).select_option("operator")
            dialog.get_by_label(re.compile(r"^Role")).select_option("CAN_RUN")
            dialog.get_by_label("Reason (kept in the audit trail)").fill("Forged target")
            dialog.get_by_role("button", name="Grant access", exact=True).click()
            expect(dialog.get_by_role("alert")).to_contain_text(target or "default")
            expect(dialog.get_by_role("alert")).to_contain_text("CAN_MANAGE")
            expect(dialog.get_by_role("alert")).to_contain_text("administrator")
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            page.unroute("**/api/v1/access/grants", forge)

        row.get_by_role("button", name="Revoke", exact=True).click()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Handover ended")
        dialog.get_by_role("button", name="Revoke", exact=True).click()
        expect(row).to_have_count(0)
        with ctx.engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT ACTOR AS actor, ACTIVE_FLAG AS active_flag "
                    "FROM AUD_CFG_ACCESS_BINDINGS_HISTORY "
                    "WHERE GRANTEE_ROLE='operator' AND PIPELINE_CODE='OPS' "
                    "AND CURRENT_FLAG='Y'"
                )
            ).one()
            assert audit.actor == "alice" and audit.active_flag == "N"
        untouched = act(ctx, ActionName.ACCESS_LIST, project="default").bindings
        assert [g for g in untouched if g.audience == "operator" and g.pipeline != "OPS"] == [
            g for g in baseline if g.audience == "operator" and g.pipeline != "OPS"
        ]
        page.goto(url + "/ui/projects/default/pipelines/SALES?tab=access")
        expect(page.get_by_role("heading", name=re.compile("Access to SALES"))).to_be_visible()
        # grayed out, with the reason, for a delegated manager of another pipeline
        expect(page.get_by_role("button", name="Grant access", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="Revoke", exact=True)).to_have_count(
            0
        )  # no binding row
        page.context.clear_cookies()
        sign_in(page, url, "/ui/admin?tab=access")
        expect(page.get_by_role("heading", name=re.compile("Access to default"))).to_be_visible()
        expect(
            page.get_by_role("table", name="Access bindings")
            .get_by_role("row")
            .filter(has_text="every viewer")
        ).to_be_visible()
        shoot(page, f"admin-grants-{scheme}-{width}")
        page.get_by_role("button", name="Grant access", exact=True).click()
        expect(dialog.get_by_label("Pipeline (optional)", exact=True)).to_be_visible()
        expect(dialog.get_by_label("Tag (optional)", exact=True)).to_be_visible()
        expect(dialog.get_by_text("All projects", exact=True)).to_be_visible()
        shoot(page, f"admin-grant-dialog-{scheme}-{width}")
        browser.close()


@pytest.mark.parametrize(
    "appearance,width", [("light", 1280), ("dark", 1280), ("light", 390), ("dark", 390)]
)
def test_alert_history_on_pipeline_and_project_has_status_time_and_no_secrets(
    site, appearance, width
):
    from fixtures.alerts import failed_delivery

    ctx, url = site
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ALERTED")
        add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="load.py")
        source = start_run(conn, pipeline)
    failed_delivery(ctx, pipeline, source)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 900})
        page.emulate_media(color_scheme=appearance)
        sign_in(page, url, "/ui/projects/default/pipelines/ALERTED")
        page.get_by_role("tab", name="Overview", exact=True).click()
        history = page.get_by_role("region", name="Alert delivery history")
        expect(history.get_by_text("ops", exact=True)).to_have_count(1)
        history.get_by_text("Delivery details", exact=True).click()
        expect(history.get_by_text(re.compile(r"Attempt 1.*Failed"))).to_be_visible()
        expect(history.get_by_text("Failed", exact=True)).to_be_visible()
        expect(history.get_by_text("503", exact=True)).to_be_visible()
        assert "ALERT_URL" not in history.inner_text() and "ALERT_KEY" not in history.inner_text()
        shoot(page, f"alert-history-pipeline-{appearance}-{width}")
        page.goto(url + "/ui/admin?tab=projects")
        expect(
            page.get_by_role("region", name="Alert delivery history").get_by_text("503", exact=True)
        ).to_be_visible()
        shoot(page, f"alert-history-project-{appearance}-{width}")
        held = []
        page.route("**/api/v1/project-health", lambda route: held.append(route))
        with page.expect_request("**/api/v1/project-health"):
            page.goto(url + "/ui/admin?tab=alert-channels")
        expect(page.get_by_role("heading", name="Administration", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Set channel", exact=True)).to_have_count(0)
        assert held
        for route in held:
            route.continue_()
        page.unroute("**/api/v1/project-health")
        page.get_by_role("button", name="Set channel", exact=True).click()
        dialog = page.locator("dialog[open]")
        dialog.get_by_label("Channel name", exact=True).fill("team")
        dialog.get_by_role("combobox", name="Kind", exact=True).select_option("WEBHOOK")
        dialog.get_by_label("URL variable name", exact=False).fill("TEAM_URL")
        dialog.get_by_label("Signing key variable name", exact=False).fill("TEAM_KEY")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Approve team receiver")
        shoot(page, f"alert-channel-dialog-{appearance}-{width}")
        page.route(
            "**/dialog-transition.css",
            lambda route: route.fulfill(
                content_type="text/css",
                body="dialog:not([open]) { transition-duration: 60s; }",
            ),
        )
        page.add_style_tag(url=url + "/dialog-transition.css")
        reparses = []
        page.route("**/api/v1/project-health", lambda route: reparses.append(route))
        with page.expect_request("**/api/v1/project-health"):
            dialog.get_by_role("button", name="Set channel", exact=True).click()
        channels = page.get_by_role("table", name="Alert channels")
        team = channels.get_by_role("row").filter(has_text="TEAM_URL")
        expect(team).to_contain_text("TEAM_KEY")
        shoot(page, f"alert-channel-admin-{appearance}-{width}")
        team.get_by_role("button", name="Disable", exact=True).click()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Retire team route")
        assert reparses
        with page.expect_response("**/api/v1/project-health"):
            for route in reparses:
                response = route.fetch()
                payload = response.json()
                payload["projects"].append({**payload["projects"][0], "project": "secondary"})
                route.fulfill(response=response, json=payload)
        page.unroute("**/api/v1/project-health")
        expect(page.locator("main select option").filter(has_text="secondary")).to_have_count(1)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label("Reason (kept in the audit trail)")).to_have_value(
            "Retire team route"
        )
        dialog.get_by_role("button", name="Disable", exact=True).click()
        expect(team).to_contain_text("Disabled")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_run_grid_and_the_run_graph_float_a_key_that_names_their_marks(scene, scheme, width):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        page.context.set_default_timeout(8000)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        grid = page.get_by_role("table", name="Run grid")
        expect(grid).to_be_visible()
        view = page.locator("div[tabindex='0']").filter(has=grid).last
        for place, scope in (("grid", view), ("graph", page)):
            if place == "graph":
                page.get_by_role("button", name="Graph", exact=True).click()
                expect(page.get_by_role("group", name="Task graph")).to_be_visible()
            shoot(page, f"pipeline-{place}-{scheme}-{width}")
            toggle = scope.get_by_role("button", name="Key", exact=True)
            panel = scope.get_by_role("region", name="View key", exact=True)
            if toggle.get_attribute("aria-expanded") == "true":
                toggle.click()
            expect(panel).not_to_be_visible()
            toggle.click()
            expect(panel).to_be_visible()
            # The key names the marks on screen with the same words the status badges use.
            expect(panel.get_by_role("rowheader", name="Success", exact=True)).to_be_visible()
            expect(panel).to_contain_text("Finished without an error")
            shoot(page, f"pipeline-{place}-key-{scheme}-{width}")
            panel.press("Escape")
            expect(panel).not_to_be_visible()
            expect(toggle).to_be_focused()
        assert problems == []
        browser.close()


@pytest.mark.parametrize("width", [1023, 1024])
def test_workspace_order_breakpoint_and_run_selection_round_trip(scene, width):
    ctx, url, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE='OPS'")
        ).scalar_one()
        for _ in range(5):
            run = start_run(conn, pipeline)
            finish_run(conn, run)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 900})
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        wait_for_fonts(page)
        grid = page.get_by_role("table", name="Run grid")
        headers = grid.locator("thead th a")
        expect(headers).not_to_have_count(0)
        ids = [int(link.get_attribute("href").rsplit("/", 1)[1]) for link in headers.all()]
        assert ids == sorted(ids), "the newest run must be on the right"
        page.wait_for_function(
            """stacked => {
                const panes = document.querySelectorAll('[data-pane]');
                const [left, right] = [...panes].map(el => el.getBoundingClientRect());
                return stacked ? right.top >= left.bottom - 1 : right.left >= left.right;
            }""",
            arg=width < 1024,
        )
        panes = page.locator("[data-pane]")
        left, right = panes.evaluate_all(
            "panes=>panes.map(element=>element.getBoundingClientRect().toJSON())"
        )
        if width < 1024:
            assert right["y"] >= left["y"] + left["height"] - 1
            expect(page.get_by_role("separator", name="Resize the panes")).to_be_hidden()
        else:
            assert right["x"] >= left["x"] + left["width"]
            expect(page.get_by_role("separator", name="Resize the panes")).to_be_visible()
        run = ids[0]
        page.goto(url + f"/ui/projects/default/runs/OPS/{run}?task=LOAD&view=graph")
        expect(page.get_by_label("Task LOAD", exact=True)).to_be_visible()
        assert (
            f"/runs/OPS/{run}" in page.url and "task=LOAD" in page.url and "view=graph" in page.url
        )
        wait_for_fonts(page)
        page.reload()
        expect(page.get_by_label("Task LOAD", exact=True)).to_be_visible()
        assert problems == []
        browser.close()


def test_pipeline_list_shows_dependencies_and_links_the_latest_run(scene):
    ctx, url, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipelines = {
            row.code: row.id
            for row in conn.execute(
                text("SELECT PIPELINE_CODE AS code, PIPELINE_ID AS id FROM CFG_PIPELINES")
            )
        }
        add_pipeline_dependency(conn, pipelines["OPS"], pipelines["SALES"], "HAS_DATA")
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        capabilities = []
        page.on(
            "request",
            lambda request: (
                capabilities.append(request.url)
                if "/projects/default/capabilities?" in request.url
                else None
            ),
        )
        sign_in(page, url, "/ui/projects/default/pipelines")
        table = page.get_by_role("table", name="Pipelines")
        for column in ("Description", "Schedule", "Waits for", "Last run", "Recent success"):
            expect(
                table.get_by_role(
                    "columnheader", name=re.compile(r"^" + re.escape(column) + r"(?: |$)")
                )
            ).to_be_visible()
        row = table.get_by_role("row").filter(has=page.get_by_role("link", name="OPS", exact=True))
        expect(row.get_by_text("SALES (HAS_DATA)", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Re-parse all")).to_have_accessible_description(
            re.compile("standalone pipeline re-parse requires RELAXED")
        )
        assert len(capabilities) == 1 and "pipeline_codes=" in capabilities[0]
        latest = row.get_by_role("link", name=re.compile(r"^#\d+$"))
        expect(latest).to_have_attribute("href", re.compile(r"/runs/OPS/\d+$"))
        wait_for_fonts(page)
        latest.click()
        expect(page.get_by_role("heading", name=re.compile(r"^Run #"))).to_be_visible()
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_run_page_opens_from_pipeline_grid_and_run_links(scene, scheme, width):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        grid = page.get_by_role("table", name="Run grid")
        column = (
            grid.get_by_role("columnheader").get_by_role("link", name=re.compile(r"^Run #")).last
        )
        address = column.get_attribute("href")
        assert address and "/runs/OPS/" in address
        with page.context.expect_page() as opened:
            column.click(modifiers=["Control"])
        other = opened.value
        expect(other.get_by_role("heading", name=re.compile(r"^Run #"))).to_be_visible()
        other.close()

        column.click()
        page.get_by_role("link", name="Open run", exact=True).last.click()
        expect(page).to_have_url(f"{url}{address}")
        page.get_by_role("tab", name="List", exact=True).click()
        tasks = page.get_by_role("table", name="Run tasks")
        for label in ("Rows in", "Rows written", "Rows rejected"):
            expect(tasks.get_by_role("columnheader", name=label)).to_be_visible()
        tasks.get_by_role("columnheader", name="Task").get_by_role("button").click()
        tasks.get_by_role("columnheader", name="Task").get_by_role("button").click()
        expect(tasks.get_by_role("row").nth(1)).to_contain_text("LOAD")
        page.get_by_role("searchbox", name="Search tasks by name").fill("extract")
        expect(tasks.get_by_role("button", name="EXTRACT", exact=True)).to_be_visible()
        expect(tasks.get_by_role("button", name="LOAD", exact=True)).to_have_count(0)
        tasks.get_by_role("button", name="EXTRACT", exact=True).click()
        expect(page.get_by_role("region", name="Task EXTRACT")).to_be_visible()

        page.goto(f"{url}/ui/projects/default/runs?pipeline=OPS")
        page.get_by_role("table", name="Pipeline runs").get_by_role(
            "link", name=re.compile(r"#\d+")
        ).first.click()
        expect(page.get_by_role("heading", name=re.compile(r"^Run #"))).to_be_visible()
        assert problems == []
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_run_page_shows_retry_error_and_events(site, scheme, width):
    ctx, url = site
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ORDERS")
        extract = add_task(conn, pipeline, "EXTRACT")
        load = add_task(conn, pipeline, "LOAD")
        add_dependency(conn, pipeline, load, extract)
        audit_task = add_task(conn, pipeline, "AUDIT")
        for i in range(23):
            add_dependency(conn, pipeline, add_task(conn, pipeline, f"EXPORT_{i:02}"), load)
        run = start_run(conn, pipeline)
        audit_summary = transitions.find_or_create_task_run(conn, audit_task, run).task_run_id
        attempt(conn, audit_summary)
        transitions.finish_task_run(conn, audit_summary, status=RunStatus.SUCCESS)
        summary = transitions.find_or_create_task_run(conn, extract, run).task_run_id
        extract_summary = summary
        prior = attempt(conn, summary, fail="source reset the connection")
        attempt(conn, summary, previous=prior, not_before=datetime.now(UTC))
        transitions.finish_task_run(conn, summary, status=RunStatus.SUCCESS)
        summary = transitions.find_or_create_task_run(conn, load, run).task_run_id
        log = attempt_log_path(ctx.config, "ORDERS", run, "LOAD", 1, project_id=1)
        log.parent.mkdir(parents=True)
        log.write_text(
            "INFO connecting to warehouse\nERROR connection refused\n" + "INFO cleanup\n" * 430,
            encoding="utf-8",
        )
        attempt(conn, summary, fail="connection refused", log_path=str(log))
        transitions.finish_task_run(
            conn, summary, status=RunStatus.FAILED, error_message="connection refused"
        )
        finish_run(conn, run, "FAILED")
        ended = datetime.now(UTC)
        for summary_id, duration in ((audit_summary, 1), (extract_summary, 8), (summary, 5)):
            conn.execute(
                text(
                    "UPDATE AUD_TASK_RUN_LOG SET START_DATE=:start, END_DATE=:end "
                    "WHERE TASK_RUN_ID=:task"
                ),
                {"start": ended - timedelta(seconds=duration), "end": ended, "task": summary_id},
            )
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        sign_in(page, url, f"/ui/projects/default/runs/ORDERS/{run}")
        failures = page.get_by_role("region", name="Failed tasks")
        expect(failures).to_contain_text("connection refused")
        expect(failures).to_contain_text("Try 1 of 1")
        expect(page.get_by_role("group", name="Task graph")).to_be_visible()
        expect(
            page.get_by_role("group", name="Task graph").get_by_text("LOAD", exact=True)
        ).to_be_attached()
        shoot(page, f"run-graph-{scheme}-{width}")
        failures.get_by_role("button", name="Show task LOAD").click()
        log_view = page.get_by_label("Attempt log", exact=True)
        expect(log_view.get_by_text("ERROR connection refused", exact=True)).to_be_visible()
        shoot(page, f"run-failed-log-{scheme}-{width}")
        page.get_by_role("tab", name="List", exact=True).click()
        page.get_by_role("button", name="Task status", exact=True).click()
        page.get_by_role("checkbox", name="Failed", exact=True).check()
        page.keyboard.press("Escape")
        tasks = page.get_by_role("table", name="Run tasks")
        expect(tasks.get_by_role("button", name="LOAD", exact=True)).to_be_visible()
        expect(tasks.get_by_role("button", name="EXTRACT", exact=True)).to_have_count(0)
        page.get_by_role("tab", name="Gantt", exact=True).click()
        page.get_by_role("checkbox", name="Critical path").check()
        critical = page.locator('[data-critical="true"]')
        expect(critical.first).to_be_visible()
        names = {bar.get_attribute("aria-label").split(",", 1)[0] for bar in critical.all()}
        assert names == {"EXTRACT", "LOAD"}
        page.get_by_role("tab", name="Events", exact=True).click()
        page.get_by_role("combobox", name="Kind", exact=True).select_option("Task retried")
        expect(page.get_by_role("list", name="Run events")).to_contain_text(
            "Task retried · EXTRACT"
        )
        assert problems == []
        browser.close()


@pytest.mark.parametrize(
    "choice,endpoint,command",
    [
        ("Recover failed tasks", "controls", "control"),
        ("Recover from a task", "runs", "run"),
        ("Rerun the whole run", "controls", "control"),
    ],
)
def test_run_page_confirms_server_preview_then_audits_reason(site, choice, endpoint, command):
    ctx, url = site
    scripts = ctx.config.python_scripts_dir
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "load.py").write_text(
        "from etl_craft.scripting import ScriptResult\ndef run(task):\n    return ScriptResult()\n",
        encoding="utf-8",
    )
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "RECOVERY")
        upstream = add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="load.py")
        downstream = add_task(conn, pipeline, "publish", "PYTHON", SCRIPT_FILE="load.py")
        add_dependency(conn, pipeline, downstream, upstream)
        run = start_run(conn, pipeline)
        task_run(conn, upstream, run, RunStatus.FAILED)
        finish_run(conn, run, RunStatus.FAILED)

    def audit():
        with ctx.engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT ACTOR AS actor, ARGUMENTS AS arguments FROM AUD_ACTIONS "
                    "WHERE COMMAND=:command ORDER BY ACTION_ID"
                ),
                {"command": command},
            ).all()

    reason = f"Operator approved {choice.lower()}"
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, f"/ui/projects/default/runs/RECOVERY/{run}?task=load")
        page.get_by_role("button", name="Recover", exact=True).click()
        page.get_by_role("menuitem", name=choice, exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label(re.compile("^Reason")).fill(reason)
        before = audit()
        dialog.get_by_role("button", name="Preview recovery", exact=True).click()
        expect(dialog.get_by_role("heading", name="Will run", exact=True)).to_be_visible()
        expect(dialog.get_by_role("heading", name="Will skip", exact=True)).to_be_visible()
        expect(
            dialog.get_by_role("heading", name="Depends on upstream", exact=True)
        ).to_be_visible()
        expect(dialog.get_by_text("load", exact=True).last).to_be_visible()
        assert audit() == before
        with page.expect_response(
            lambda response: (
                response.url.endswith(f"/{endpoint}") and response.request.method == "POST"
            )
        ) as submitted:
            dialog.get_by_role("button", name=choice, exact=True).click()
        assert submitted.value.ok, submitted.value.text()
        expect(dialog).not_to_be_visible()
        new_rows = audit()[len(before) :]
        requests = [
            (row.actor, arguments)
            for row in new_rows
            if "_request_action_id" not in (arguments := json.loads(row.arguments))
        ]
        assert [(actor, arguments["reason"]) for actor, arguments in requests] == [
            ("owner", reason)
        ]
        assert problems == []
        browser.close()


def test_run_page_follows_an_active_run_to_its_end(scene):
    ctx, url, run = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, f"/ui/projects/default/runs/SALES/{run}")
        header = page.get_by_role("heading", name=f"Run #{run}", exact=True).locator("../..")
        expect(header.get_by_text("Running", exact=True)).to_be_visible()
        with acting_as(ctx.actor), ctx.engine.begin() as conn:
            finish_run(conn, run, RunStatus.SUCCESS)
        expect(header.get_by_text("Success", exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_role("button", name="Cancel", exact=True)).to_have_count(0)
        assert problems == []
        browser.close()
