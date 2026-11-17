"""Shared interaction targets and keyboard behavior without changing the visual frame."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_lineage import mappings as mappings
from test_react_ui import open_page, sign_in
from test_react_ui import scene as scene

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("destination", ["/ui/projects/default", "/ui/admin"])
def test_phone_tabs_use_arrow_keys_and_keep_a_scroll_cue_inside_the_gutter(site, destination):
    _, url = site
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 390, "height": 900})
        sign_in(page, url, destination)
        tabs = page.get_by_role("tablist").first
        first, last = tabs.get_by_role("tab").first, tabs.get_by_role("tab").last
        first.focus()
        page.keyboard.press("End")
        expect(last).to_be_focused()
        expect(last).to_have_attribute("aria-selected", "true")
        expect(page.get_by_test_id("tabs-scroll-start")).to_be_visible()
        page.wait_for_function(
            """element => {
            const last = element.querySelector('[role=tab]:last-child').getBoundingClientRect();
            const box = element.getBoundingClientRect();
            return last.left >= box.left && last.right <= box.right + 1;
        }""",
            arg=tabs.element_handle(),
        )
        page.keyboard.press("Home")
        expect(first).to_be_focused()
        expect(first).to_have_attribute("aria-selected", "true")
        expect(page.get_by_test_id("tabs-scroll-end")).to_be_visible()
        page.keyboard.press("ArrowRight")
        expect(tabs.get_by_role("tab").nth(1)).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert problems == []
        browser.close()


def test_table_and_pane_resize_targets_work_away_from_the_exact_border(scene):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1440, "height": 1000})
        sign_in(page, url, "/ui/projects/default/pipelines")
        # The header is drawn before the rows; their arrival moves it, so drag after they load.
        expect(page.get_by_role("link", name="OPS", exact=True).first).to_be_visible()
        grip = page.get_by_role("separator", name="Resize the Pipeline column", exact=True)
        grip.hover(position={"x": 2, "y": 12})
        box = grip.bounding_box()
        assert box["width"] >= 24
        before = int(grip.get_attribute("aria-valuenow"))
        page.mouse.down()
        page.mouse.move(box["x"] + 42, box["y"] + 12, steps=8)
        page.mouse.up()
        expect(grip).not_to_have_attribute("aria-valuenow", str(before))
        grip.focus()
        current = int(grip.get_attribute("aria-valuenow"))
        page.keyboard.press("ArrowLeft")
        expect(grip).to_have_attribute("aria-valuenow", str(current - 16))
        page.goto(url + "/ui/projects/default/pipelines/OPS")
        divider = page.get_by_role("separator", name="Resize the panes", exact=True)
        expect(divider).to_be_visible()
        box = divider.bounding_box()
        before = divider.get_attribute("aria-valuenow")
        x, y = box["x"] - 4, box["y"] + box["height"] / 2
        assert divider.evaluate("(e, point) => e === document.elementFromPoint(...point)", [x, y])
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 50, y, steps=8)
        page.mouse.up()
        expect(divider).not_to_have_attribute("aria-valuenow", before)
        divider.focus()
        page.keyboard.press("ArrowLeft")
        expect(divider).to_be_focused()
        assert problems == []
        browser.close()


def test_touch_selection_and_breadcrumbs_work_outside_the_visible_glyph(scene):
    _, url, _, _ = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": 390, "height": 900}, has_touch=True, is_mobile=True
        )
        sign_in(page, url, "/ui/projects/default/pipelines")
        checkbox = page.get_by_role("checkbox", name="Select OPS", exact=True)
        box = checkbox.bounding_box()
        page.mouse.click(box["x"] - 3, box["y"] + box["height"] / 2)
        expect(checkbox).to_be_checked()
        page.goto(url + "/ui/projects/default/pipelines/OPS")
        breadcrumb = page.get_by_role("navigation", name="Breadcrumb").get_by_role(
            "link", name="Pipelines", exact=True
        )
        box = breadcrumb.bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] - 3)
        expect(page).to_have_url(url + "/ui/projects/default/pipelines")
        assert len(page.context.pages) == 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert problems == []
        browser.close()


def test_recent_run_strip_has_one_touch_target_and_a_keyboard_run_chooser(scene):
    _, url, _, bad = scene
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": 390, "height": 900}, has_touch=True, is_mobile=True
        )
        sign_in(page, url, "/ui/projects/default/pipelines")
        chooser = page.get_by_role("button", name="Recent runs for OPS", exact=True)
        expect(chooser).to_be_visible()
        box = page.wait_for_function(
            """() => {
                const r = document.querySelector('[aria-label="Recent runs for OPS"]')
                    ?.getBoundingClientRect();
                return r && r.width >= 24 && r.height >= 24 && {width: r.width, height: r.height};
            }"""
        ).json_value()
        chooser.tap(position={"x": box["width"] / 2, "y": 1})
        expect(page.get_by_role("menu")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("menu")).not_to_be_visible()
        expect(chooser).to_be_focused()
        chooser.focus()
        page.keyboard.press("Enter")
        item = page.get_by_role("menuitem", name=re.compile(rf"#{bad}\b"))
        expect(item).to_have_count(1)
        expect(item).to_be_focused()
        expect(item).not_to_have_attribute("target", "_blank")
        page.keyboard.press("Enter")
        expect(page).to_have_url(re.compile(rf"/pipelines/OPS\?run={bad}$"))
        assert len(page.context.pages) == 1
        assert problems == []
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_mapping_resize_grips_and_scrollbars_do_not_cover_column_controls(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": width, "height": 1000}, show_scrollbars=True
        )
        sign_in(page, url, "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping")
        page.get_by_role("button", name="Show all columns", exact=True).click()
        source = page.locator('[data-id="source:raw.orders"]')
        page.mouse.move(0, 0)
        grip = source.locator(".handle.bottom.right.window-corner")
        expect(grip).to_be_visible()
        assert grip.evaluate("e=>getComputedStyle(e,'::after').boxShadow") != "none"
        box = grip.bounding_box()
        assert box["width"] == 12 and box["height"] == 12
        list_box = source.locator(".nowheel").bounding_box()
        assert box["x"] >= list_box["x"] + list_box["width"] - 14
        assert box["y"] >= list_box["y"] + list_box["height"] - 14
        collisions = source.evaluate("""node => {
            const grips = [...node.querySelectorAll('.react-flow__resize-control')]
                .filter(e=>getComputedStyle(e).display!=='none').map(e=>e.getBoundingClientRect());
            const buttons = [...node.querySelectorAll('button')].map(e=>{
                const r=e.getBoundingClientRect(), list=e.closest('.nowheel');
                if(!list)return r;
                const clip=list.getBoundingClientRect();
                const right=clip.left+list.clientLeft+list.clientWidth;
                const bottom=clip.top+list.clientTop+list.clientHeight;
                return {left:Math.max(r.left,clip.left),right:Math.min(r.right,right),
                    top:Math.max(r.top,clip.top),bottom:Math.min(r.bottom,bottom)};
            });
            const overlaps=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>0.5 &&
                Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>0.5;
            return grips.flatMap((g,i)=>[
                ...buttons.flatMap((b,j)=>overlaps(g,b)?[{grip:i,button:j,g,b}]:[]),
                ...grips.slice(i+1).flatMap((other,j)=>overlaps(g,other)?[{grip:i,other:i+1+j,g,otherBox:other}]:[])
            ]);
        }""")
        assert not collisions, collisions
        resize = source.get_by_role("separator", name="Resize raw.orders width", exact=True)
        # Make room for growth without deliberately overlapping the next node.
        drag = source.locator(".mapping-drag-handle").bounding_box()
        page.mouse.move(drag["x"] + 5, drag["y"] + 5)
        page.mouse.down()
        page.mouse.move(drag["x"] - 59, drag["y"] + 5, steps=8)
        page.mouse.up()
        before = int(resize.get_attribute("aria-valuenow"))
        target = resize.bounding_box()
        x, y = target["x"] + target["width"] - 2, target["y"] + target["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 32, y, steps=8)
        page.mouse.up()
        expect(resize).not_to_have_attribute("aria-valuenow", str(before))
        before = int(resize.get_attribute("aria-valuenow"))
        resize.focus()
        page.keyboard.press("ArrowRight")
        expect(resize).to_have_attribute("aria-valuenow", str(before + 16))
        height = source.get_by_role("separator", name="Resize raw.orders height", exact=True)
        before_height = int(height.get_attribute("aria-valuenow"))
        bezel = grip.bounding_box()
        x, y = bezel["x"] + bezel["width"] / 2, bezel["y"] + bezel["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 12, y + 24, steps=8)
        page.mouse.up()
        expect(height).not_to_have_attribute("aria-valuenow", str(before_height))
        assert int(height.get_attribute("aria-valuenow")) > before_height
        before_height = int(height.get_attribute("aria-valuenow"))
        height.focus()
        page.keyboard.press("ArrowDown")
        expect(height).to_have_attribute("aria-valuenow", str(before_height + 16))
        columns = source.locator(".nowheel")
        columns.scroll_into_view_if_needed()
        box = columns.bounding_box()
        header = source.locator(".mapping-drag-handle").bounding_box()
        transform = page.locator(".react-flow__viewport").get_attribute("style")
        point = [box["x"] + box["width"] - 3, box["y"] + box["height"] / 2]
        assert page.evaluate(
            "point=>!document.elementFromPoint(...point).closest('.react-flow__resize-control')",
            point,
        )
        page.mouse.move(*point)
        page.mouse.wheel(0, 160)
        page.wait_for_function("e=>e.scrollTop>0", arg=columns.element_handle())
        assert page.locator(".react-flow__viewport").get_attribute("style") == transform
        assert abs(source.locator(".mapping-drag-handle").bounding_box()["y"] - header["y"]) < 1
        assert columns.evaluate("""e=>{
            const frame=e.closest('.scroll-window');
            return frame.clientWidth-e.clientWidth===14 && frame.clientHeight-e.clientHeight===14;
        }""")
        expect(source.get_by_role("scrollbar", name="Window vertical scrollbar")).to_be_visible()
        # Collapse changes geometry; expanding restores the chosen size and its scrollable rows.
        source.get_by_role("button", name="Collapse raw.orders", exact=True).click()
        page.wait_for_function(
            "e=>e.getBoundingClientRect().height<80", arg=source.element_handle()
        )
        source.get_by_role("button", name="Expand raw.orders", exact=True).click()
        page.wait_for_function(
            "(args)=>args[0].getBoundingClientRect().height>args[1]",
            arg=[source.element_handle(), before_height],
        )
        assert problems == []
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage", "graph"])
def test_diagram_view_moves_with_buttons_without_dragging(mappings, width, view):
    _, url = mappings
    routes = {
        "mapping": "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping",
        "lineage": "/ui/projects/default/catalog/tables/mart.orders?tab=lineage",
        "graph": "/ui/projects/default/pipelines/ORDERS?view=graph",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, routes[view])
        viewport = page.locator(".react-flow__viewport")
        expect(viewport).to_be_visible()
        for direction in ("right", "down", "left", "up"):
            before = viewport.get_attribute("style")
            button = page.get_by_role("button", name=f"Move view {direction}", exact=True)
            button.focus()
            page.keyboard.press("Enter")
            expect(viewport).not_to_have_attribute("style", before)
        assert problems == []
        browser.close()
