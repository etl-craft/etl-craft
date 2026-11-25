"""The dense execution workspace, including exact task and attempt links."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_pipelines import shoot
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.engine import transitions
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


@pytest.fixture
def workspace(site):
    ctx, url = site
    owner = Actor("owner", ActorKind.USER)
    with acting_as(owner), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "SI_SETUP")
        order = ["a", "b", "c", "d", *(f"setup_{i:02}" for i in range(20)), "alert_a", "alert_z"]
        insertion = ["alert_z", "d", "c", "b", "a", *order[4:-2], "alert_a"]
        ids = {}
        for code in insertion:
            ids[code] = (
                add_task(conn, pipeline, code, handler="ALERT", ALERT_ON="FAILURE")
                if code.startswith("alert_")
                else add_task(conn, pipeline, code, SELECT_QUERY="SELECT 1")
            )
        for downstream, upstream in (("c", "a"), ("b", "a"), ("d", "c"), ("d", "b")):
            add_dependency(conn, pipeline, ids[downstream], ids[upstream])
        for code in order[4:-2]:
            add_dependency(conn, pipeline, ids[code], ids["d"])
        for _ in range(23):
            run = start_run(conn, pipeline)
            for code in order[:-2]:
                task_run(conn, ids[code], run)
            finish_run(conn, run)
        failed_run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, ids["b"], failed_run).task_run_id
        first = attempt(conn, summary, fail="first warehouse refusal")
        second = attempt(conn, summary, fail="second warehouse refusal", previous=first)
        finish_run(conn, failed_run, "FAILED")
        current = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, ids["a"], current).task_run_id
        live = transitions.queue_attempt(conn, summary, owner)
        transitions.claim_attempt(
            conn,
            live,
            owner,
            owner="w1",
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        transitions.start_attempt(conn, live, owner, owner="w1")
        for run_id, task, number, attempt_id, message in (
            (current, "a", 1, live, "Preparing customer staging"),
            (failed_run, "b", 1, first, "ERROR first warehouse refusal"),
            (failed_run, "b", 2, second, "ERROR second warehouse refusal"),
        ):
            path = (
                ctx.config.log_dir
                / "project-1"
                / "SI_SETUP"
                / f"run-{run_id}"
                / f"{task}.attempt-{number}.log"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(message + "\n")
            conn.execute(
                text("UPDATE AUD_TASK_ATTEMPTS SET LOG_PATH=:path WHERE ATTEMPT_ID=:id"),
                {"path": str(path), "id": attempt_id},
            )
    return url, order, current, failed_run, first, second


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_grid_order_alignment_and_exact_selection(workspace, scheme, width):
    url, order, current, failed, first, _ = workspace
    expect.set_options(timeout=12000)
    base = "/ui/projects/default/pipelines/SI_SETUP"
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        page.add_init_script(
            "Date.now = (() => { const now = Date.now; return () => now() - 40000; })();"
        )
        sign_in(page, url, base)
        grid = page.get_by_role("table", name="Run grid")
        expect(grid.get_by_role("rowheader")).to_have_text(order)
        # Ten runs by default; the newest sits at the right edge, scrolled into view.
        expect(grid.locator("thead th")).to_have_count(11)
        assert grid.evaluate(
            "(table) => { const area = table.parentElement; "
            "return area.scrollLeft + area.clientWidth >= area.scrollWidth - 1; }"
        )
        grid.evaluate(
            "(table) => { table.parentElement.scrollTop = 80; "
            "table.parentElement.scrollLeft = 90; }"
        )
        assert grid.evaluate("""table => [...table.tBodies[0].rows].every(row => {
          const [header, cell] = row.cells;
          const top = header.getBoundingClientRect().top;
          return Math.abs(top - cell.getBoundingClientRect().top) < 1;
        })""")
        grid.get_by_role("link", name=re.compile(rf"^Run #{current}(?: |$)")).click()
        instances = page.get_by_role("table", name="Task instances")
        expect(instances.get_by_role("button")).to_have_text(order)
        expect(instances.get_by_role("cell", name="When the pipeline fails")).to_have_count(2)
        # The column shows only its bar; number, start time and duration are in its hover text.
        column = grid.get_by_role("link", name=re.compile(rf"^Run #{current}(?: |$)"))
        expect(column).to_have_attribute("title", re.compile(rf"^#{current} · .*\d{{2}}:\d{{2}}"))
        expect(column).to_have_text("")
        grid.evaluate("(table) => { table.parentElement.scrollTop = 0; }")
        grid.get_by_role("button", name=re.compile(rf"^a in run {current}:")).click()
        expect(page).to_have_url(re.compile(rf"run={current}&task=a"))
        task = page.get_by_role("region", name="Task a", exact=True)
        expect(task.get_by_role("heading", name="a", exact=True)).to_be_in_viewport()
        expect(task.get_by_role("tab", name="Logs")).to_have_attribute("aria-selected", "true")
        expect(task.get_by_text("Running", exact=True)).to_be_visible()
        expect(task.locator("time").first).not_to_contain_text(re.compile(r"^in "))
        expect(task.get_by_text("Preparing customer staging")).to_be_in_viewport()
        task.get_by_role("tab", name="Details").click()
        expect(task.get_by_text("Process details", exact=True)).to_have_count(0)
        task.get_by_role("tab", name="Logs").press("Enter")
        expect(task.get_by_text("Preparing customer staging")).to_be_visible()
        shoot(page, f"si-setup-running-{scheme}-{width}")
        page.goto(url + f"/ui/projects/default/runs/SI_SETUP/{failed}/tasks/b/attempts/{first}")
        expect(page).to_have_url(re.compile(rf"/pipelines/SI_SETUP\?run={failed}&task=b&try=1$"))
        expect(page.get_by_role("heading", name="b", exact=True)).to_be_in_viewport()
        expect(page.get_by_role("combobox", name="Try")).to_have_value("1")
        page.reload()
        expect(page.get_by_role("combobox", name="Try")).to_have_value("1")
        expect(
            page.get_by_role("region", name="Task b").get_by_text("Failed", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("ERROR first warehouse refusal")).to_be_in_viewport()
        shoot(page, f"si-setup-failed-{scheme}-{width}")
        assert not problems
        browser.close()


def test_pipeline_header_distinguishes_partial_runs_and_unscheduled_triggers(site):
    from etl_craft.engine.run_scopes import TaskSelection, create_manual_run

    ctx, url = site
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        upload = add_pipeline(conn, "UPLOAD_START")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y' WHERE PIPELINE_ID=:id"),
            {"id": upload},
        )
        task = add_task(conn, upload, "LOAD")
        add_task(conn, upload, "CHECK")
        whole = start_run(conn, upload)
        finish_run(conn, whole, "SUCCESS")
        partial = create_manual_run(
            conn, upload, ctx.actor, TaskSelection((task,)), None, datetime.now(UTC).date()
        )
        finish_run(conn, partial, "FAILED")
        event = add_pipeline(conn, "EVENT_START")
        add_task(conn, event, "WAIT", handler="EVENT_WAIT")
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, f"/ui/projects/default/pipelines/UPLOAD_START?run={partial}")
        expect(page.get_by_text("On upload", exact=True)).to_be_visible()
        latest = page.get_by_text("Latest run", exact=True).locator("..")
        expect(latest).to_contain_text("Success")
        expect(page.get_by_text("1 of 2 tasks", exact=True)).to_be_visible()
        page.goto(url + "/ui/projects/default/pipelines/EVENT_START")
        expect(page.get_by_text("Waits for object events", exact=True)).to_be_visible()
        assert not problems
        browser.close()


def test_checklist_filters_pick_tasks_task_states_and_run_states(workspace):
    url, order, _current, failed, _first, _ = workspace
    expect.set_options(timeout=12000)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 900})
        sign_in(page, url, f"/ui/projects/default/pipelines/SI_SETUP?run={failed}")
        grid = page.get_by_role("table", name="Run grid")
        expect(grid.get_by_role("rowheader")).to_have_text(order)

        # Tasks: an Excel-style checklist with search and Select all.
        page.get_by_role("button", name=re.compile("^Tasks")).click()
        page.get_by_label("Search tasks").fill("setup_0")
        select_all = page.get_by_role("checkbox", name="Select all matches")
        select_all.click()  # the tick follows the URL, so wait for it rather than check()
        expect(select_all).to_be_checked()
        page.keyboard.press("Escape")
        expect(grid.get_by_role("rowheader")).to_have_text([f"setup_{i:02}" for i in range(10)])
        page.get_by_role("button", name=re.compile(r"^Tasks \(10 selected\)")).click()
        page.get_by_role("button", name="Clear").click()
        page.keyboard.press("Escape")
        expect(grid.get_by_role("rowheader")).to_have_text(order)

        # Task status reads the selected run's column: only b failed in it.
        page.get_by_role("button", name=re.compile(rf"^Task status in #{failed}")).click()
        failed_box = page.get_by_role("checkbox", name="Failed")
        failed_box.click()
        expect(failed_box).to_be_checked()
        page.keyboard.press("Escape")
        expect(grid.get_by_role("rowheader")).to_have_text(["b"])
        assert "task_status=FAILED" in page.url

        # Run status is applied by the server: only the failed run remains as a column.
        page.goto(url + "/ui/projects/default/pipelines/SI_SETUP?run_status=FAILED")
        expect(grid.locator("thead a[title]")).to_have_count(1)
        expect(grid.get_by_role("link", name=re.compile(rf"^Run #{failed}(?: |$)"))).to_be_visible()
        assert not problems
        browser.close()


def test_grid_and_selected_task_follow_the_engine_without_a_reload(site):
    ctx, url = site
    owner = Actor("owner", ActorKind.USER)
    with acting_as(owner), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "LIVE_GRID")
        load = add_task(conn, pipeline, "load", SELECT_QUERY="SELECT 1")
        run = start_run(conn, pipeline)
        task_run(conn, load, run, "IN-PROGRESS")
    expect.set_options(timeout=40000)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, f"/ui/projects/default/pipelines/LIVE_GRID?run={run}&task=load")
        grid = page.get_by_role("table", name="Run grid")
        cell = grid.get_by_role("button", name=re.compile(rf"^load in run {run}:"))
        expect(cell).to_have_accessible_name(re.compile("running$"))
        with acting_as(owner), ctx.engine.begin() as conn:
            task_run(conn, load, run, "SUCCESS")
            finish_run(conn, run)
        # No reload: the polling queries bring the new states to the grid and the task header.
        expect(cell).to_have_accessible_name(re.compile("success$"))
        task = page.get_by_role("region", name="Task load", exact=True)
        expect(task.get_by_text("Success", exact=True)).to_be_visible()
        assert not problems
        browser.close()
