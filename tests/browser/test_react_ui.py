"""The React interface in a real browser: Home, a pipeline's runs and one run with its recovery."""

import os
import re
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
        audit = add_task(conn, pipeline, "AUDIT")
        add_dependency(conn, pipeline, load, extract)
        good = start_run(conn, pipeline)
        task_run(conn, extract, good)
        task_run(conn, load, good)
        task_run(conn, audit, good)
        finish_run(conn, good)
        bad = start_run(conn, pipeline)
        task_run(conn, extract, bad)
        task_run(conn, load, bad, "FAILED")
        task_run(conn, audit, bad)
        finish_run(conn, bad, "FAILED")
    return ctx, url, good, bad


def sign_in(page, url, destination="/ui", name="owner"):
    page.goto(url + "/ui/signin?return_to=" + destination.replace("/", "%2F"))
    page.get_by_label("Account name", exact=True).fill(name)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url(url + destination)


def open_page(pw, **options):
    browser = pw.chromium.launch()
    page = browser.new_context(ignore_https_errors=True, **options).new_page()
    page.context.set_default_timeout(10_000)  # a loaded runner needs more than 5 s
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    return browser, page, problems


def test_home_runs_and_run_detail_lead_to_a_confirmed_recovery(scene):
    ctx, url, _, bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url)
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        page.get_by_role(
            "link", name="Runs", exact=True
        ).click()  # Operations, beside Held and paused
        page.get_by_role(
            "link", name=f"#{bad}"
        ).first.click()  # the pipeline's workspace, this run selected
        expect(page.get_by_role("heading", name="OPS")).to_be_visible()
        expect(
            page.get_by_role("table", name="Run grid").locator("[aria-current=true]")
        ).to_have_count(1)
        expect(page.get_by_label("Run identifier", exact=True)).to_contain_text(f"-{bad}")
        page.get_by_role("button", name="Graph", exact=True).click()
        graph = page.get_by_role("group", name="Task graph")
        expect(graph.get_by_text("EXTRACT")).to_be_visible()
        expect(graph.get_by_text("LOAD")).to_be_visible()
        # a click shows the lineage and opens nothing; the task's arrow opens its details
        expect(graph.locator("[data-focus=none]")).to_have_count(3)
        graph.get_by_text("LOAD", exact=True).click()
        expect(graph.locator("[data-focus=focus]")).to_have_count(1)
        expect(graph.locator("[data-focus=lineage]")).to_have_count(1)  # EXTRACT, upstream of LOAD
        expect(graph.locator("[data-focus=dim]")).to_have_count(1)  # AUDIT is unrelated
        expect(page.get_by_label("Task LOAD")).to_have_count(0)
        graph.get_by_role("button", name="Open LOAD details").click()
        expect(page.get_by_label("Task LOAD")).to_be_visible()
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
        sign_in(page, url, "/ui/projects/default/runs")
        table = page.get_by_role("table", name="Pipeline runs")
        expect(table.get_by_role("link", name=f"#{good}")).to_be_visible()
        expect(table.get_by_role("link", name=f"#{bad}")).to_be_visible()
        page.get_by_role("combobox", name="Status").select_option("FAILED")
        expect(table.get_by_role("link", name=f"#{good}")).to_have_count(0)
        expect(table.get_by_role("link", name=f"#{bad}")).to_be_visible()
        assert "status=FAILED" in page.url
        page.reload()
        expect(page.get_by_role("combobox", name="Status")).to_have_value("FAILED")
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
        sign_in(page, url, f"/ui/projects/default/runs/OPS/{bad}", name="alice")
        expect(page.get_by_label("Run identifier", exact=True)).to_contain_text(f"-{bad}")
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
        sign_in(page, url, f"/ui/projects/default/runs/OPS/{bad}")
        expect(page).to_have_title(f"PRODUCTION · default · OPS #{bad} · etl-craft")
        strip = page.get_by_role("status").filter(has_text="PRODUCTION")
        expect(strip).to_be_visible()
        expect(strip).not_to_contain_text("default")  # the project is named once, in the switcher
        expect(page.get_by_role("button", name="Switch project")).to_have_text("default")
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
        sign_in(page, url, "/ui/projects/default/runs")
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
        "home": "/ui",
        "runs": "/ui/projects/default/runs",
        "run": f"/ui/projects/default/runs/OPS/{bad}",
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


def test_a_run_offers_its_logs_and_a_running_run_offers_reconcile(scene):
    ctx, url, good, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES WHERE PIPELINE_CODE='OPS'")
        ).scalar_one()
        running = start_run(conn, pipeline)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, f"/ui/projects/default/runs/OPS/{good}")
        actions = page.get_by_role("button", name="Run actions, logs and key")
        actions.click()  # the logs are in the run's one actions menu
        link = page.get_by_role("menuitem", name="Download run log")
        expect(link).to_have_attribute(
            "href", f"/api/v1/projects/default/run-log?pipeline_code=OPS&run_id={good}"
        )
        expect(page.get_by_role("menuitem", name="Download logs (zip)")).to_be_visible()
        reconcile = page.get_by_role("menuitem").filter(has_text="Reconcile")
        expect(reconcile).to_have_count(0)  # it has ended
        page.keyboard.press("Escape")
        page.goto(url + f"/ui/projects/default/runs/OPS/{running}")
        page.get_by_role("button", name="Run actions, logs and key").click()
        page.get_by_role("menuitem").filter(has_text="Reconcile").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("fences attempts", exact=False)).to_be_visible()
        dialog.get_by_role("button", name="Cancel").click()
        page.goto(url + "/ui/projects/default/pipelines")
        expect(page.get_by_role("button", name="Refresh all")).to_be_visible()  # owner is admin
        assert problems == []
        browser.close()


def test_shortcuts_copy_run_key_and_live_status_are_offered(scene):
    _, url, good, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=url)
        sign_in(page, url, f"/ui/projects/default/runs/OPS/{good}")
        expect(page.get_by_role("status").filter(has_text="Live")).to_be_visible()
        page.get_by_role("button", name="Run actions, logs and key").click()
        page.get_by_role("menuitem", name="Copy run key").click()
        expect(page.get_by_role("status").filter(has_text="Run key copied.")).to_be_visible()
        page.keyboard.press("?")
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("Keyboard shortcuts")).to_be_visible()
        dialog.get_by_role("button", name="Close shortcuts").click()
        expect(dialog).to_have_count(0)
        page.get_by_role("button", name="Account menu").click()
        page.get_by_role("menuitem", name="Keyboard shortcuts").click()
        expect(page.get_by_role("dialog").get_by_text("opens this list")).to_be_visible()
        assert problems == []
        browser.close()


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


def test_the_project_runs_list_and_a_pipeline_share_one_layout(scene):
    _, url, good, _bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 800})
        sign_in(page, url, "/ui/projects/default/runs")
        expect(page.get_by_text("Run durations")).to_have_count(
            0
        )  # under five runs the table says it all
        expect(page.get_by_role("columnheader", name="Identifier")).to_have_count(0)
        expect(page.get_by_role("link", name=f"#{good}", exact=True)).to_have_attribute(
            "title", re.compile(r"^OPS-")
        )  # the string identifier is the run number's tooltip
        shoot(page, "runs-list")
        page.get_by_role("link", name=f"#{good}", exact=True).click()
        expect(
            page.get_by_role("table", name="Run grid")
        ).to_be_visible()  # the pipeline's workspace, this run selected
        expect(
            page.get_by_role("table", name="Run grid").locator("[aria-current=true]")
        ).to_have_count(1)
        shoot(page, "pipeline-highlight")
        assert page.url.endswith(f"?run={good}")
        assert problems == []
        browser.close()


def test_a_task_opens_in_its_row_and_the_run_shows_its_identifier(scene):
    _, url, _, bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, f"/ui/projects/default/runs/OPS/{bad}")
        identifier = page.get_by_label("Run identifier", exact=True)
        expect(identifier).to_contain_text("OPS-")
        expect(identifier).to_contain_text(f"-{bad}")
        table = page.get_by_role("table", name="Task list")
        expect(page.get_by_label("Task LOAD")).to_have_count(0)
        table.get_by_role("button", name="Show details of LOAD").click()
        details = table.get_by_label("Task LOAD")  # inside the table, directly under its row
        expect(details).to_be_visible()
        shoot(page, "run-page")
        table.get_by_role("button", name="Hide details of LOAD").click()
        expect(page.get_by_label("Task LOAD")).to_have_count(0)
        assert problems == []
        browser.close()
