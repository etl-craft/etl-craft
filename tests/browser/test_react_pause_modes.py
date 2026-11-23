"""Pause modes and task outcomes work through the shared browser entry points."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, pause_item, sign_in
from test_react_ui import scene as scene

from etl_craft.core.actor import acting_as
from fixtures.metadata import start_run

pytestmark = pytest.mark.browser


def capture(page, name, scheme, width):
    directory = os.getenv("ETL_CRAFT_SCREENSHOT_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(path / f"{name}-{scheme}-{width}.png"), full_page=True, animations="disabled"
        )


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_paused_page_redirect_modes_outcomes_and_resume_use_the_same_controls(scene, scheme, width):
    ctx, url, _, _ = scene
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        run = start_run(conn, 1)
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw,
            viewport={"width": width, "height": 1000},
            color_scheme=scheme,
            has_touch=width == 390,
        )
        held_reads = []
        page.on(
            "request",
            lambda request: (
                held_reads.append(request.url) if request.url.endswith("/holds") else None
            ),
        )
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        pause_item(page, "Pause").click()
        dialog = page.get_by_role("dialog", name="Pause OPS", exact=True)
        mode = dialog.get_by_role("combobox", name="Active runs", exact=True)
        expect(mode).to_have_value("DRAIN")
        expect(mode.locator('option[value="DRAIN"]')).to_have_text(
            "Stop active runs at the next task"
        )
        expect(mode.locator('option[value="FINISH"]')).to_have_text("Let active runs finish")
        capture(page, "pause-dialog", scheme, width)
        dialog.get_by_label("Reason (kept in the audit trail)").fill("maintenance drain")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/controls") and response.request.method == "POST"
            )
        ) as sent:
            dialog.get_by_role("button", name="Pause", exact=True).click()
        assert sent.value.request.post_data_json["active_runs"] == "DRAIN"
        expect(dialog).not_to_be_visible()
        page.goto(url + "/ui/projects/default/pipelines/OPS/tasks/EXTRACT")
        page.get_by_role("button", name="Pause task", exact=True).click()
        task_dialog = page.get_by_role("dialog", name="Pause task EXTRACT", exact=True)
        expect(task_dialog.get_by_role("combobox", name="Task outcome")).to_have_value("SKIPPED")
        capture(page, "task-pause-dialog", scheme, width)
        task_dialog.get_by_label("Reason (kept in the audit trail)").fill("omit unavailable source")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/controls") and response.request.method == "POST"
            )
        ) as sent:
            task_dialog.get_by_role("button", name="Pause task", exact=True).click()
        assert sent.value.request.post_data_json["outcome"] == "SKIPPED"
        assert "active_runs" not in sent.value.request.post_data_json
        page.goto(url + "/ui/projects/default/held?from=old")
        expect(page).to_have_url(re.compile(r"/paused\?from=old$"))
        expect(page.get_by_role("heading", name="Paused", exact=True)).to_be_visible()
        pipelines = page.get_by_role("table", name="Paused pipelines", exact=True)
        expect(pipelines).to_contain_text("DRAIN")
        expect(pipelines.get_by_role("link", name=f"#{run}", exact=True)).to_be_visible()
        tasks = page.get_by_role("table", name="Paused tasks", exact=True)
        expect(tasks.get_by_text("Skipped", exact=True)).to_be_visible()
        expect(tasks).to_contain_text("Runs where this task has not started")
        expect(page.get_by_role("button", name="Hold", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Release", exact=True)).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        capture(page, "paused", scheme, width)
        pause_item(pipelines, "Replace pause").click()
        replacement = page.get_by_role("dialog", name="Replace pause OPS", exact=True)
        select = replacement.get_by_role("combobox", name="Active runs", exact=True)
        select.focus()
        select.press("ArrowDown")
        select.press("Tab")
        expect(select).to_have_value("FINISH")
        capture(page, "replace-pause-dialog", scheme, width)
        replacement.get_by_label("Reason (kept in the audit trail)").fill("allow admitted work")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/controls") and response.request.method == "POST"
            )
        ) as sent:
            replacement.get_by_role("button", name="Replace pause", exact=True).click()
        body = sent.value.request.post_data_json
        assert body["replace"] is True and body["active_runs"] == "FINISH"
        expect(pipelines).to_contain_text("FINISH")
        expect(pipelines.get_by_role("link", name=f"#{run}", exact=True)).to_have_count(0)
        tasks.get_by_role("button", name="Resume", exact=True).click()
        resume = page.get_by_role("dialog", name="Resume task EXTRACT", exact=True)
        resume.get_by_label("Reason (kept in the audit trail)").fill("source restored")
        resume.get_by_role("button", name="Resume", exact=True).click()
        expect(page.get_by_text("No task is paused.", exact=True)).to_be_visible()
        pause_item(pipelines, "Resume").click()
        resume = page.get_by_role("dialog", name="Resume OPS", exact=True)
        resume.get_by_label("Reason (kept in the audit trail)").fill("maintenance complete")
        resume.get_by_role("button", name="Resume", exact=True).click()
        expect(page.get_by_text("No pipeline is paused.", exact=True)).to_be_visible()
        assert not held_reads
        assert not problems
        browser.close()
