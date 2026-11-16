"""Connection activation reveals real endpoints instead of selecting an inert stroke."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_lineage import mappings as mappings
from test_react_ui import open_page, sign_in

pytestmark = pytest.mark.browser


def click_connection(page, connection):
    path = connection.locator(".react-flow__edge-path")
    identity = connection.get_attribute("data-id")
    for fraction in (0.5, 0.3, 0.7, 0.15, 0.85):
        point = path.evaluate(
            """(path,fraction)=>{
            const point=path.getPointAtLength(path.getTotalLength()*fraction);
            const screen=new DOMPoint(point.x,point.y).matrixTransform(path.getScreenCTM());
            return {x:screen.x,y:screen.y};
        }""",
            fraction,
        )
        exposed = page.evaluate(
            """({point,identity})=>document.elementFromPoint(point.x,point.y)
                ?.closest('.diagram-connection')?.getAttribute('data-id')===identity""",
            {"point": point, "identity": identity},
        )
        if exposed:
            page.mouse.click(point["x"], point["y"])
            return
    pytest.fail(f"Connection {identity} has no exposed pointer target at readable zoom")


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage", "graph", "definition"])
def test_connection_click_and_keyboard_highlight_its_recorded_endpoints(mappings, width, view):
    _, url = mappings
    routes = {
        "mapping": "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping",
        "lineage": "/ui/projects/default/catalog/tables/mart.orders?tab=lineage",
        "graph": "/ui/projects/default/pipelines/ORDERS?view=graph",
        "definition": "/ui/projects/default/catalog/pipelines/ORDERS?tab=lineage",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, routes[view])
        if view == "mapping" and width == 390:
            page.get_by_role("button", name="Diagram", exact=True).click()
        if view == "lineage":
            page.get_by_role("button", name="Expand all", exact=True).click()
        page.wait_for_load_state("networkidle")
        if view in ("mapping", "lineage"):
            connection = page.get_by_role(
                "button", name=re.compile(r"^Highlight path: raw\.orders\.id →")
            ).first
        else:
            connection = page.locator('.diagram-connection[data-id="extract->load"]')
        expect(connection).to_have_attribute("aria-pressed", "false")
        if view == "definition" and width == 390:
            page.get_by_role("button", name="Fit view", exact=True).click()
            page.wait_for_function(
                """()=>{
                    const canvas=document.querySelector('.react-flow__viewport');
                    return new DOMMatrix(getComputedStyle(canvas).transform).a<1;
                }"""
            )
        canvas = page.locator(".react-flow__viewport")
        transform, address = canvas.get_attribute("style"), page.url
        click_connection(page, connection)
        expect(connection).to_have_attribute("aria-pressed", "true")
        expect(canvas).to_have_attribute("style", transform)
        expect(page).to_have_url(address)
        if view in ("mapping", "lineage"):
            source = "source:raw.orders" if view == "mapping" else "raw.orders"
            target = "target:mart.orders" if view == "mapping" else "mart.orders"
            for node in (source, target):
                row = page.locator(f'[data-id="{node}"] [data-port="id"] button')
                expect(row).to_have_class(re.compile(r"\bring-2\b"))
        else:
            expect(page.locator('[data-id="extract"] [data-focus]')).to_have_attribute(
                "data-focus", "lineage"
            )
            expect(page.locator('[data-id="load"] [data-focus]')).to_have_attribute(
                "data-focus", "focus"
            )
        click_connection(page, connection)
        expect(connection).to_have_attribute("aria-pressed", "false")
        connection.focus()
        page.keyboard.press("Enter")
        expect(connection).to_have_attribute("aria-pressed", "true")
        expect(connection).to_be_focused()
        page.keyboard.press("Escape")
        expect(connection).to_have_attribute("aria-pressed", "false")
        connection.focus()
        page.keyboard.press("Space")
        expect(connection).to_have_attribute("aria-pressed", "true")
        page.keyboard.press("Space")
        expect(connection).to_have_attribute("aria-pressed", "false")
        assert problems == []
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_object_connection_marks_both_frames_without_claiming_column_lineage(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/tables/mart.orders?tab=lineage")
        page.wait_for_load_state("networkidle")
        connection = page.get_by_role(
            "button", name=re.compile(r"^Highlight path: raw\.orders feeds mart\.orders")
        )
        click_connection(page, connection)
        expect(connection).to_have_attribute("aria-pressed", "true")
        for node in ("raw.orders", "mart.orders"):
            expect(page.locator(f'[data-id="{node}"] .diagram-node')).to_have_class(
                re.compile(r"\bring-2\b")
            )
        assert page.locator("[data-port] button.ring-2").count() == 0
        expect(connection).to_be_focused()
        page.keyboard.press("Escape")
        expect(connection).to_have_attribute("aria-pressed", "false")
        expect(page.locator(".diagram-node.ring-2")).to_have_count(0)
        assert problems == []
        browser.close()
