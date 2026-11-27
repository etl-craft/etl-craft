"""Capture the standalone review using the repository's Playwright environment."""
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).parent
URL = "http://127.0.0.1:8746/"
SCREENS = {
    "home": {"view": "Home"},
    "monitor": {"view": "Monitor"},
    "task-logs": {"view": "Task"},
    "task-sql": {"view": "Task", "tab": "SQL / script"},
    "task-details": {"view": "Task", "tab": "Details"},
    "task-attempts": {"view": "Task", "tab": "Attempts"},
    "task-python": {"view": "Task", "task": "python"},
    "task-running": {"view": "Task", "task": "running"},
    "task-waiting": {"view": "Task", "task": "waiting"},
    "statistics": {"view": "Statistics"},
    "agents": {"view": "Agents"},
    "alert": {"view": "Alert"},
}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for theme in ("light", "dark"):
        for width in (1440, 390):
            page = browser.new_page(
                color_scheme=theme, viewport={"width": width, "height": 960},
                has_touch=width == 390, reduced_motion="reduce",
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for name, query in SCREENS.items():
                page.goto(URL + "?" + urlencode(query), wait_until="networkidle")
                page.locator("main h1").wait_for()
                page.evaluate("document.fonts.ready")
                assert page.locator("html").get_attribute("data-theme") == theme
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
                assert not errors, errors
                page.screenshot(path=ROOT / f"{name}-{theme}-{width}.png", full_page=True)
            page.goto(URL + "?view=Home")
            expect(page.get_by_text("Pipelines, least healthy first")).to_be_visible()
            page.get_by_role("button", name="24 h").click()
            expect(page.get_by_text("1 of 7 runs failed")).to_be_visible()
            page.get_by_role("link", name="Failing").click()
            assert "PRIVATE_RECON" not in page.locator("main").inner_text()
            assert "NIGHTLY_LEDGER" in page.locator("main").inner_text()
            page.goto(URL + "?view=Task")
            page.get_by_role("button", name="First error").click()
            expect(page.locator("#first-error")).to_be_visible()
            page.get_by_role("tab", name="Attempts").click()
            page.get_by_role("button", name="Open archived log").click()
            expect(page.get_by_text("Attempt 1 log was archived.", exact=True)).to_be_visible()
            page.close()
    browser.close()
