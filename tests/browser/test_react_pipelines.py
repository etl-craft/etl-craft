"""The React pipelines, pipeline, scheduled and held pages in a real browser."""

import json
import os
import re
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
        assert content.startswith(
            "pipeline,name,description,tags,schedule,next_run,automatic_runs,paused_tasks"
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
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/runs")) as sent:
            submit.click()
        body = sent.value.post_data_json
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


def test_a_pipeline_has_an_overview_tasks_and_details_and_a_way_back(scene):
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
        expect(page.get_by_role("region", name="Task definitions")).to_be_visible()
        expect(
            page.get_by_role("link", name="Open the documentation in the catalog")
        ).to_be_visible()
        expect(page.get_by_role("tab", name="Docs")).to_have_count(
            0
        )  # documented once, in the catalog
        page.get_by_role("link", name="Back to Pipelines").click()
        expect(page.get_by_role("table", name="Pipelines")).to_be_visible()
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
        area = grid.locator("xpath=parent::div/parent::div").bounding_box()
        newest = headers.first.bounding_box()
        assert newest["x"] + newest["width"] <= area["x"] + area["width"] + 1, (
            "the newest run is cut off"
        )
        assert newest["x"] >= area["x"], "the newest run is outside the grid"
        task = page.get_by_role("table", name="Tasks").locator("tbody th").first.bounding_box()
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
        task_cell = page.get_by_role("table", name="Tasks").get_by_role("rowheader", name=name)
        grid = page.get_by_role("table", name="Run grid")
        area = grid.locator("xpath=parent::div/parent::div")
        expect(grid.locator("thead th a").first).to_be_visible()
        expect(page.get_by_role("separator")).to_have_count(1)
        full = task_cell.evaluate("""el => {
            const range = document.createRange();
            range.selectNodeContents(el);
            const style = getComputedStyle(el);
            return Math.ceil(range.getBoundingClientRect().width
                + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight));
        }""")

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
                arg=[area.element_handle(), grid.locator("thead th a").first.element_handle()],
                timeout=5000,
            )

        resize_grid(False)
        assert task_cell.bounding_box()["width"] < full
        latest_visible()
        resize_grid(True)
        expect(task_cell).to_have_js_property("clientWidth", full)
        latest_visible()
        shoot(page, f"grid-expanded-{method}-{labels}")
        resize_grid(False)
        assert task_cell.bounding_box()["width"] < full
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


def test_the_newest_grid_run_is_next_to_task_names(scene):
    _, url, active = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines/SALES")
        first = page.get_by_role("table", name="Run grid").locator("thead th a").first
        expect(first).to_have_attribute("href", re.compile(rf"/pipelines/SALES\?run={active}$"))
        square = (
            page.get_by_role("table", name="Run grid")
            .get_by_role("img", name=re.compile("success$"))
            .first
        )
        expect(square).to_be_visible()
        size = square.bounding_box()
        assert size["width"] >= 24 and size["height"] >= 24
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
        expect(link).to_have_attribute("href", re.compile(rf"[?&]run={run.id}(?:$|&)"))
        link.click()
        expect(page.get_by_label("Run identifier", exact=True)).to_contain_text(run.label)
        page.evaluate(
            "navigator.clipboard.writeText = async (text) => { window.copiedLabel = text; }"
        )
        page.get_by_role("button", name="Copy the run identifier", exact=True).click()
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
        page.evaluate("() => document.fonts.ready.then(() => true)")
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
            page.evaluate("() => document.fonts.ready.then(() => true)")
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
    baseline = act(ctx, ActionName.ACCESS_LIST, project="default").grants
    for target, permission in ((None, "CAN_VIEW"), ("OPS", "CAN_MANAGE")):
        act(
            ctx,
            ActionName.ACCESS_GRANT,
            project="default",
            account="alice",
            pipeline=target,
            permission=permission,
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
        dialog.get_by_label("Role", exact=False).select_option("operator")
        dialog.get_by_label("Permission", exact=False).select_option("CAN_RUN")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Operations team")
        shoot(page, f"pipeline-grant-dialog-{scheme}-{width}")
        dialog.get_by_role("button", name="Grant access", exact=True).click()
        table = page.get_by_role("table", name="Access grants")
        row = table.get_by_role("row").filter(has_text="role operator")
        expect(row).to_contain_text("Can run")
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
            dialog.get_by_label("Role", exact=False).select_option("operator")
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
                    "FROM AUD_CFG_PIPELINE_GRANTS_HISTORY "
                    "WHERE GRANTEE_ROLE='operator' AND PIPELINE_CODE='OPS' "
                    "AND CURRENT_FLAG='Y'"
                )
            ).one()
            assert audit.actor == "alice" and audit.active_flag == "N"
        untouched = act(ctx, ActionName.ACCESS_LIST, project="default").grants
        assert [g for g in untouched if g.role == "operator" and g.pipeline != "OPS"] == [
            g for g in baseline if g.role == "operator" and g.pipeline != "OPS"
        ]
        page.goto(url + "/ui/projects/default/pipelines/SALES?tab=access")
        expect(page.get_by_role("heading", name=re.compile("Access to SALES"))).to_be_visible()
        expect(page.get_by_role("button", name="Grant access", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Revoke", exact=True)).to_have_count(0)
        page.context.clear_cookies()
        sign_in(page, url, "/ui/admin?tab=access")
        expect(page.get_by_role("heading", name=re.compile("Access to default"))).to_be_visible()
        expect(
            page.get_by_role("table", name="Access grants")
            .get_by_role("row")
            .filter(has_text="role viewer")
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
        expect(history.get_by_text("ops", exact=True).first).to_be_visible()
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
        refreshes = []
        page.route("**/api/v1/project-health", lambda route: refreshes.append(route))
        with page.expect_request("**/api/v1/project-health"):
            dialog.get_by_role("button", name="Set channel", exact=True).click()
        channels = page.get_by_role("table", name="Alert channels")
        team = channels.get_by_role("row").filter(has_text="TEAM_URL")
        expect(team).to_contain_text("TEAM_KEY")
        shoot(page, f"alert-channel-admin-{appearance}-{width}")
        team.get_by_role("button", name="Disable", exact=True).click()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Retire team route")
        assert refreshes
        with page.expect_response("**/api/v1/project-health"):
            for route in refreshes:
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
