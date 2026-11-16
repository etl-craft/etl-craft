"""Removed pipeline views keep their information reachable at a single destination."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_pipelines import scene as scene
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from fixtures.metadata import add_dependency, add_pipeline, add_task

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("width", [1440, 390])
def test_pipeline_overview_links_to_kept_history_instead_of_repeating_runs(scene, width):
    ctx, url, _ = scene
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION=:condition "
                "WHERE PIPELINE_CODE=:code"
            ),
            {"condition": "SUCCESS|SKIPPED", "code": "OPS"},
        )
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_text("Restarts", exact=True)).to_be_visible()
        details = page.request.get(url + "/api/v1/projects/default/pipelines/OPS").json()
        assert details["restart_note"]
        expect(page.get_by_text(details["restart_note"], exact=True)).to_be_visible()
        expect(
            page.get_by_role("link", name="About this pipeline in the catalog")
        ).to_have_attribute("href", "/ui/projects/default/catalog/pipelines/OPS")
        expect(page.get_by_role("region", name="Latest run durations")).to_have_count(0)
        expect(page.get_by_role("region", name="Recent failures")).to_have_count(0)
        page.get_by_role("link", name="Open run history", exact=True).click()
        table = page.get_by_role("table", name="Pipeline runs")
        expect(table.locator("tbody tr").first).to_be_visible()
        for name in ("Status", "Started", "Duration"):
            expect(table.locator(f'td[data-label="{name}"]').first).to_be_visible()
        expect(table.locator('td[data-label="Status"]').first).to_contain_text("Success")
        expect(table.locator('td[data-label="Started"]').first.locator("time")).to_be_visible()
        expect(table.locator('td[data-label="Duration"]').first).not_to_be_empty()
        assert not problems
        browser.close()


@pytest.mark.parametrize("removed", ["tasks", "details"])
@pytest.mark.parametrize("width", [1440, 390])
def test_removed_task_tabs_redirect_and_definitions_work_before_the_first_run(site, removed, width):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "NEW")
        first = add_task(conn, pipeline, "FIRST")
        second = add_task(
            conn,
            pipeline,
            "SECOND",
            TARGET_OBJECT="mart.new",
            DOCUMENTATION="source_column_" * 30,
        )
        add_dependency(conn, pipeline, second, first)
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url)
        page.goto(url + f"/ui/projects/default/pipelines/NEW?tab={removed}")
        page.wait_for_url(re.compile(r"\?tab=overview$"))
        for tab in ("Tasks", "Details", "Calendar"):
            expect(page.get_by_role("tab", name=tab, exact=True)).to_have_count(0)
        expect(page.get_by_text("No runs yet.", exact=True)).to_be_visible()
        expect(page.get_by_text("Loading the grid…", exact=True)).to_have_count(0)
        button = page.get_by_role("button", name="Task definition for SECOND", exact=True)
        button.click()
        dialog = page.get_by_role("dialog", name="Task definition · SECOND")
        expect(dialog.get_by_text("Handler", exact=True)).to_be_visible()
        expect(dialog.get_by_text("SQL", exact=True)).to_be_visible()
        expect(dialog.get_by_role("link", name="FIRST", exact=True)).to_be_visible()
        dialog.get_by_role("button", name="Close task definition", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(button).to_be_focused()
        button.press("Enter")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(button).to_be_focused()
        button.press("Enter")
        expect(dialog).to_be_visible()
        dialog.get_by_role("link", name="Task history, definition and parameters").click()
        expect(page.get_by_role("heading", name="SECOND", exact=True)).to_be_visible()
        expect(page.get_by_text("TARGET_OBJECT", exact=True)).to_be_visible()
        expect(page.get_by_text("mart.new", exact=True)).to_be_visible()
        parameter = page.get_by_text("source_column_" * 30, exact=True)
        expect(parameter).to_be_visible()
        assert parameter.evaluate(
            "element => element.scrollWidth <= element.clientWidth && "
            "element.getBoundingClientRect().right <= innerWidth"
        )
        assert not problems
        browser.close()


@pytest.mark.parametrize("removed", ["tasks", "details"])
def test_removed_definition_tab_keeps_the_addressed_run_and_task(scene, removed):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url)
        entries = page.request.get(
            url + "/api/v1/projects/default/history?pipeline_code=OPS&all=true"
        ).json()["entries"]
        run = entries[0]["pipeline_run_id"]
        page.goto(url + f"/ui/projects/default/pipelines/OPS?tab={removed}&run={run}&task=LOAD")
        page.wait_for_url(lambda value: "tab=overview" in value)
        assert f"run={run}" in page.url and "task=LOAD" in page.url
        expect(page.get_by_role("tab", name="Overview", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        expect(page.get_by_role("tab", name=re.compile(rf"^Run #{run} ·"))).to_be_visible()
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_old_calendar_address_leads_to_scoped_historical_days_on_scheduled_runs(scene, width):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url)
        page.goto(url + "/ui/projects/default/pipelines/OPS?tab=calendar")
        page.wait_for_url(re.compile(r"/scheduled\?pipeline=OPS$"))
        expect(page.get_by_role("heading", name="Run history by day", exact=True)).to_be_visible()
        expect(page.get_by_role("combobox", name="History pipeline", exact=True)).to_have_value(
            "OPS"
        )
        expect(page.get_by_text("1 run", exact=True)).to_be_visible()
        expect(page.get_by_role("tab", name="Calendar", exact=True)).to_have_count(0)
        expect(page.get_by_role("table", name="Next runs", exact=True)).to_be_visible()
        assert not problems
        browser.close()


@pytest.mark.parametrize("removed", ["Tasks", "Details", "Calendar"])
def test_removed_pipeline_tabs_are_not_offered_on_the_workspace(scene, removed):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        expect(page.get_by_role("table", name="Run grid", exact=True)).to_be_visible()
        expect(page.get_by_role("tab", name=removed, exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Grid", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Graph", exact=True)).to_be_visible()
        assert not problems
        browser.close()
