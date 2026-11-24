"""Pipeline actions share one flow, including the Paused page."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_pipelines import scene as scene
from test_react_ui import open_page, pause_item, sign_in

from etl_craft.core.enums import ActionName
from fixtures.actions import act


PROBE = """
window.__probe = [];
const t = () => performance.now().toFixed(0);
const orig = HTMLDialogElement.prototype.showModal;
HTMLDialogElement.prototype.showModal = function () { window.__probe.push(t() + ' showModal ' + this.getAttribute('aria-labelledby')); return orig.call(this); };
const origClose = HTMLDialogElement.prototype.close;
HTMLDialogElement.prototype.close = function () { window.__probe.push(t() + ' close() called'); return origClose.call(this); };
window.addEventListener('keydown', e => { if (e.key === 'Escape') window.__probe.push(t() + ' keydown-capture target=' + e.target.tagName + ' menus=' + document.querySelectorAll('[role=menu]').length + ' openDialogs=' + document.querySelectorAll('dialog[open]').length + ' active=' + (document.activeElement && document.activeElement.tagName)); }, true);
window.addEventListener('keydown', e => { if (e.key === 'Escape') window.__probe.push(t() + ' keydown-bubble prevented=' + e.defaultPrevented); }, false);
document.addEventListener('cancel', e => window.__probe.push(t() + ' cancel'), true);
document.addEventListener('close', e => window.__probe.push(t() + ' close-event'), true);
"""

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("width", [1440, 390])
def test_pipeline_row_pause_resume_keeps_confirmation_policy_and_header_action(scene, width):
    _, url, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        page.add_init_script(PROBE)
        sign_in(page, url, "/ui/projects/default/pipelines")
        row = (
            page.get_by_role("table", name="Pipelines", exact=True)
            .get_by_role("row")
            .filter(has=page.get_by_role("link", name="OPS", exact=True))
        )
        pause_item(row, "Pause").click()
        dialog = page.get_by_role("dialog", name="Pause OPS", exact=True)
        expect(dialog.get_by_role("button", name="Pause", exact=True)).to_be_disabled()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("row freeze")
        dialog.get_by_role("button", name="Pause", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(row).to_contain_text("row freeze")
        resume = pause_item(row, "Resume")
        expect(resume).not_to_have_attribute("aria-disabled", "true")  # enabled after the pause
        resume.click()
        dialog = page.get_by_role("dialog", name="Resume OPS", exact=True)
        policy = dialog.get_by_role("combobox", name="After resuming", exact=True)
        expect(policy).to_have_value("wait")
        for value in ("wait", "run-now", "catch-up"):
            expect(policy.locator(f'option[value="{value}"]')).to_have_count(1)
        page.keyboard.press("Escape")
        try:
            expect(dialog).not_to_be_visible()
        except AssertionError:
            print("STUCK", page.evaluate("() => window.__probe"))
            raise
        row.get_by_role("link", name="OPS", exact=True).click()
        expect(page.get_by_role("button", name="Run now", exact=True)).to_have_count(1)
        pause_item(page, "Resume").click()
        dialog = page.get_by_role("dialog", name="Resume OPS", exact=True)
        dialog.get_by_role("combobox", name="After resuming", exact=True).select_option("wait")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("header thaw")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST" and response.url.endswith("/controls")
            )
        ) as sent:
            dialog.get_by_role("button", name="Resume", exact=True).click()
        assert sent.value.request.post_data_json["then"] == "wait"
        expect(page.get_by_role("button", name="Pause options for OPS", exact=True)).to_have_count(
            1
        )
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_paused_pipeline_keeps_shared_resume_and_pipeline_link(scene, width):
    ctx, url, _ = scene
    act(ctx, ActionName.CONTROL, pipeline_code="OPS", action="PAUSE", reason="review totals")
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/held")
        paused = page.get_by_role("table", name="Paused pipelines", exact=True)
        expect(paused).to_contain_text("review totals")
        expect(paused).to_contain_text("owner")
        expect(paused.locator("time")).to_be_visible()
        expect(
            paused.get_by_role("button", name="Pause options for OPS", exact=True)
        ).to_have_count(1)
        paused.get_by_role("link", name="OPS", exact=True).click()
        page.wait_for_url(re.compile(r"/pipelines/OPS$"))
        pause_item(page, "Resume").click()
        dialog = page.get_by_role("dialog", name="Resume OPS", exact=True)
        expect(dialog.get_by_role("combobox", name="After resuming", exact=True)).to_have_value(
            "wait"
        )
        dialog.get_by_label("Reason (kept in the audit trail)").fill("checked totals")
        dialog.get_by_role("button", name="Resume", exact=True).click()
        expect(page.get_by_role("button", name="Pause options for OPS", exact=True)).to_be_visible()
        assert not problems
        browser.close()
