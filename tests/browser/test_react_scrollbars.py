"""Application-painted tracks remain usable when native scrollbar chrome is hidden."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_lineage import mappings as mappings
from test_react_ui import sign_in

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage", "graph"])
def test_application_scrollbars_work_without_native_browser_chrome(mappings, width, scheme, view):
    _, url = mappings
    engine = os.environ.get("ETL_CRAFT_REVIEW_BROWSER", "chromium")
    routes = {
        "mapping": "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping",
        "lineage": "/ui/projects/default/catalog/tables/mart.orders?tab=lineage",
        "graph": "/ui/projects/default/pipelines/ORDERS?view=graph",
    }
    with sync_playwright() as pw:
        browser = getattr(pw, engine).launch()
        page = browser.new_page(
            ignore_https_errors=True, viewport={"width": width, "height": 1000}, color_scheme=scheme
        )
        problems = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        sign_in(page, url, routes[view])
        canvas = page.locator(".react-flow__viewport")
        expect(page.locator(".diagram-node").first).to_be_visible()
        bars = [
            page.get_by_role("scrollbar", name=f"Diagram {axis} scrollbar", exact=True)
            for axis in ("horizontal", "vertical")
        ]
        for bar in bars:
            expect(bar).to_be_visible()
            thumb = bar.locator(".app-scrollbar-thumb")
            expect(thumb).to_be_visible()
            assert thumb.evaluate(
                """e=>getComputedStyle(e).backgroundColor !==
                getComputedStyle(e.parentElement).backgroundColor"""
            )
            assert bar.get_attribute("aria-controls")
            before = canvas.get_attribute("style")
            bar.focus()
            page.keyboard.press("Shift+Tab")
            page.keyboard.press("Tab")
            expect(bar).to_be_focused()
            page.keyboard.press("ArrowRight")
            expect(canvas).not_to_have_attribute("style", before)
            assert bar.evaluate("e=>e.matches(':focus-visible')")
            before = canvas.get_attribute("style")
            box = thumb.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            horizontal = bar.get_attribute("aria-orientation") == "horizontal"
            page.mouse.move(
                box["x"] + box["width"] / 2 + (20 if horizontal else 0),
                box["y"] + box["height"] / 2 + (0 if horizontal else 20),
                steps=5,
            )
            page.mouse.up()
            expect(canvas).not_to_have_attribute("style", before)
            before = canvas.get_attribute("style")
            bar.hover()
            page.mouse.wheel(0, 80)
            expect(canvas).not_to_have_attribute("style", before)
        page.get_by_role("button", name="Fit view", exact=True).click()
        if view == "mapping":
            page.get_by_role("button", name="Show all columns", exact=True).click()
        elif view == "lineage":
            page.get_by_role("button", name="Expand all", exact=True).click()
        else:
            header = page.locator(".diagram-node .mapping-drag-handle > button").first
            if header.get_attribute("aria-expanded") == "false":
                header.click()
        window = page.locator(".scroll-window").first
        expect(window).to_be_visible()
        viewport = window.locator(".app-scrollport")
        assert viewport.evaluate("e=>getComputedStyle(e).scrollbarWidth") == "none"
        for axis in ("horizontal", "vertical"):
            expect(window.get_by_role("scrollbar", name=f"Window {axis} scrollbar")).to_be_visible()
        if view != "graph":
            scrollbar = window.get_by_role("scrollbar", name="Window vertical scrollbar")
            expect(scrollbar).not_to_have_attribute("aria-disabled", "true")
            titlebar = page.locator(".diagram-node").first.locator(".mapping-drag-handle")
            relative_top = """e=>e.getBoundingClientRect().top-
                e.closest('.diagram-node').getBoundingClientRect().top"""
            header = titlebar.evaluate(relative_top)
            transform = canvas.get_attribute("style")
            scrollbar.focus()
            page.keyboard.press("End")
            page.wait_for_function(
                "e=>e.scrollTop>0 && e.scrollTop+e.clientHeight>=e.scrollHeight-1",
                arg=viewport.element_handle(),
            )
            assert canvas.get_attribute("style") == transform
            assert titlebar.evaluate(relative_top) == header
            page.keyboard.press("Home")
            page.wait_for_function("e=>e.scrollTop===0", arg=viewport.element_handle())
            viewport.hover()
            page.mouse.wheel(0, 100)
            page.wait_for_function("e=>e.scrollTop>0", arg=viewport.element_handle())
            assert canvas.get_attribute("style") == transform
        shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=f"{shots}/scrollbars-{engine}-{view}-{scheme}-{width}.png", full_page=True
            )
            page.locator(".diagram-frame").screenshot(
                path=f"{shots}/scrollbars-{engine}-{view}-{scheme}-{width}-canvas.png"
            )
        assert not problems
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        browser.close()


def test_touch_thumb_drag_and_column_swipe_do_not_pan_the_canvas(mappings):
    _, url = mappings
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            ignore_https_errors=True,
            viewport={"width": 390, "height": 1000},
            has_touch=True,
            is_mobile=True,
        )
        sign_in(page, url, "/ui/projects/default/catalog/tables/mart.orders?tab=lineage")
        bar = page.get_by_role("scrollbar", name="Diagram horizontal scrollbar", exact=True)
        expect(page.locator(".diagram-node").first).to_be_visible()
        canvas = page.locator(".react-flow__viewport")
        before = canvas.get_attribute("style")
        bar.scroll_into_view_if_needed()
        expect(bar.locator(".app-scrollbar-thumb")).to_be_in_viewport()
        thumb = bar.locator(".app-scrollbar-thumb").bounding_box()
        x, y = thumb["x"] + thumb["width"] / 2, thumb["y"] + thumb["height"] / 2
        touch = page.context.new_cdp_session(page)
        touch.send(
            "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]}
        )
        touch.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x + 35, "y": y}]},
        )
        touch.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        expect(canvas).not_to_have_attribute("style", before)
        page.get_by_role("button", name="Fit view", exact=True).tap()
        page.get_by_role("button", name="Expand all", exact=True).tap()
        body = page.locator('[data-id="raw.orders"] .app-scrollport')
        expect(body).to_be_visible()
        body.scroll_into_view_if_needed()
        box = body.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] - 20
        before = canvas.get_attribute("style")
        touch.send(
            "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]}
        )
        for delta in (20, 40, 60, 80):
            touch.send(
                "Input.dispatchTouchEvent",
                {"type": "touchMove", "touchPoints": [{"x": x, "y": y - delta}]},
            )
        touch.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function("e=>e.scrollTop>0", arg=body.element_handle())
        assert canvas.get_attribute("style") == before
        browser.close()
