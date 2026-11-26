"""Shared search, page entry focus and readable action feedback in a real browser."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, pause_item, sign_in
from test_react_ui import scene as scene

pytestmark = pytest.mark.browser


def test_search_keyboard_selection_is_announced_and_scrolls_inside_the_popup(scene):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 500})
        sign_in(page, url, "/ui/projects/default/pipelines")
        page.keyboard.press("Control+k")
        box = page.get_by_role("combobox", name="Search pipelines, tasks, tables and runs")
        expect(box).to_be_focused()
        box.press("ArrowUp")
        selected = page.get_by_role("option", name="Settings", exact=True)
        expect(selected).to_have_attribute("aria-selected", "true")
        active = selected.get_attribute("id")
        assert active, "Every selected search result needs an accessible identity"
        expect(box).to_have_attribute("aria-activedescendant", active)
        page.wait_for_function(
            """() => {
                const box = document.querySelector('[role=combobox]');
                const option = document.getElementById(box.getAttribute('aria-activedescendant'));
                if (!option) return false;
                const list = option.closest('[role=listbox]').parentElement;
                const a = option.getBoundingClientRect(), b = list.getBoundingClientRect();
                return a.top >= b.top && a.bottom <= b.bottom;
            }"""
        )
        expect(box).to_be_focused()
        box.press("Escape")
        expect(box).to_have_attribute("aria-expanded", "false")
        assert not problems
        browser.close()


def test_search_failure_can_be_retried_with_keyboard_and_keeps_local_navigation(scene):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines")
        page.route(
            "**/api/v1/projects/default/search?*",
            lambda route: route.fulfill(
                status=503, json={"message": "Search index unavailable; restore the index."}
            ),
        )
        box = page.get_by_role("combobox", name="Search pipelines, tasks, tables and runs")
        box.fill("Pipelines")
        alert = page.get_by_role("alert")
        expect(alert).to_contain_text("Search for “Pipelines” failed:")
        expect(alert).to_contain_text("Search index unavailable; restore the index.")
        expect(page.get_by_role("option", name="Pipelines", exact=True)).to_be_visible()
        long_query = "x" * 200
        box.fill(long_query)
        expect(alert).to_contain_text(long_query)
        assert alert.evaluate("el => el.scrollWidth <= el.clientWidth")
        box.fill("Pipelines")
        expect(alert).to_contain_text("Search for “Pipelines” failed:")
        page.unroute("**/api/v1/projects/default/search?*")
        box.press("Tab")
        retry = page.get_by_role("button", name="Retry search")
        expect(retry).to_be_focused()
        retry.press("Escape")
        expect(box).to_be_focused()
        expect(box).to_have_attribute("aria-expanded", "false")
        box.press("ArrowDown")
        box.press("Tab")
        retry.press("Enter")
        expect(alert).to_have_count(0)
        expect(box).to_be_focused()
        box.press("Tab")
        expect(box).to_have_attribute("aria-expanded", "false")
        assert all("503" in problem for problem in problems), problems
        browser.close()


def test_page_navigation_focuses_content_but_workspace_selection_keeps_focus(scene):
    _, url, _, bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw)
        sign_in(page, url, "/ui/projects/default/pipelines")
        link = page.get_by_role("navigation", name="Main").get_by_role(
            "link", name="Runs", exact=True
        )
        link.focus()
        link.press("Enter")
        expect(page.get_by_role("heading", name="Runs", exact=True)).to_be_visible()
        expect(page.get_by_role("main", name="Page content")).to_be_focused()
        page.get_by_role("link", name=f"#{bad}", exact=True).first.click()
        expect(page).to_have_url(re.compile(rf"/runs/OPS/{bad}$"))
        expect(page.get_by_role("main", name="Page content")).to_be_focused()
        graph = page.get_by_role("tab", name="Graph", exact=True)
        graph.focus()
        graph.press("Enter")
        expect(graph).to_be_focused()
        expect(page.get_by_role("group", name="Task graph")).to_be_visible()
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_action_feedback_has_a_usable_close_target_and_remains_keyboard_dismissible(scene, width):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": width, "height": 900}, has_touch=width == 390
        )
        sign_in(page, url, "/ui/projects/default/pipelines/OPS")
        pause_item(page, "Pause").click()
        dialog = page.get_by_role("dialog", name="Pause OPS", exact=True)
        dialog.get_by_label("Reason (kept in the audit trail)").fill("review feedback")
        dialog.get_by_role("button", name="Pause", exact=True).click()
        expect(dialog).not_to_be_visible()
        dismiss = page.get_by_role("button", name="Dismiss", exact=True)
        expect(dismiss).to_be_visible()
        size = dismiss.bounding_box()
        minimum = 44 if width == 390 else 24
        assert size and size["width"] >= minimum and size["height"] >= minimum
        dismiss.focus()
        dismiss.press("Enter")
        expect(dismiss).to_have_count(0)
        assert not problems
        browser.close()
