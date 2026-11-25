"""Framed working objects and native canvas scrollbars share the diagram viewport."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import expect, sync_playwright
from test_react_lineage import mappings as mappings
from test_react_ui import open_page, sign_in

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage", "graph"])
def test_diagram_scrollbars_move_the_view_and_follow_its_controls(mappings, width, view, scheme):
    _, url = mappings
    routes = {
        "mapping": "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping",
        "lineage": "/ui/projects/default/catalog/tables/mart.orders?tab=lineage",
        "graph": "/ui/projects/default/pipelines/ORDERS?view=graph",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": width, "height": 1000}, color_scheme=scheme, show_scrollbars=True
        )
        sign_in(page, url, routes[view])
        assert page.evaluate("""() => {
            const sample=document.createElement('span');document.body.append(sample);
            const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
            const context=canvas.getContext('2d');
            const luminance=token=>{
                sample.style.color=`var(${token})`;context.fillStyle=getComputedStyle(sample).color;
                context.fillRect(0,0,1,1);
                const channels=[...context.getImageData(0,0,1,1).data].slice(0,3).map(v=>{
                    const s=v/255;return s<=0.04045?s/12.92:((s+0.055)/1.055)**2.4;
                });
                return channels[0]*0.2126+channels[1]*0.7152+channels[2]*0.0722;
            };
            const a=luminance('--muted'),b=luminance('--surface-2');sample.remove();
            return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)>=3;
        }""")
        canvas = page.locator(".react-flow__viewport")
        expect(page.locator(".diagram-frame")).to_have_attribute("data-fitted", "true")
        horizontal = page.get_by_role("scrollbar", name="Diagram horizontal scrollbar", exact=True)
        vertical = page.get_by_role("scrollbar", name="Diagram vertical scrollbar", exact=True)
        page.wait_for_function(
            """() => {
                const handles = [...document.querySelectorAll('.react-flow__handle')];
                return handles.length && handles.every(e => getComputedStyle(e).opacity === '0');
            }"""
        )
        node = page.locator(".diagram-node").first
        grips = page.locator(".react-flow__node").first.locator(
            ".react-flow__resize-control.handle"
        )
        header = node.locator(".mapping-drag-handle > button").first
        if header.get_attribute("aria-expanded") == "true":
            header.click()
        expect(header).to_have_attribute("aria-expanded", "false")
        if view == "graph":
            expect(node).to_have_attribute("data-collapsed-tile", "true")
            assert header.evaluate(
                """e=>{
                    const icon=e.querySelector('.diagram-object-icon').getBoundingClientRect();
                    const label=e.querySelector('strong').getBoundingClientRect();
                    return label.top>=icon.bottom;
                }"""
            )
        assert (
            node.locator(".diagram-object-icon").evaluate("e=>getComputedStyle(e).boxShadow")
            != "none"
        )
        shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=f"{shots}/frames-{view}-{scheme}-{width}-collapsed.png", full_page=True
            )
        header.click()
        expect(header).to_have_attribute("aria-expanded", "true")
        expect(node.locator(".diagram-body")).to_be_visible()
        if grips.count():
            corner = page.locator(".react-flow__node").first.locator(
                ".handle.bottom.right.window-corner"
            )
            expect(corner).to_be_visible()
            page.wait_for_function(
                """node => [...node.querySelectorAll('.react-flow__resize-control.handle')]
                    .filter(e => getComputedStyle(e, '::after').content !== 'none').length === 1""",
                arg=page.locator(".react-flow__node").first.element_handle(),
            )
            page.wait_for_function(
                """e => {
                    const dots = getComputedStyle(e, '::after');
                    return dots.width === '2px' && dots.height === '2px' &&
                        dots.transform === 'none' && dots.boxShadow !== 'none';
                }""",
                arg=corner.element_handle(),
            )
            columns = node.locator(".nowheel")
            assert columns.evaluate("e=>getComputedStyle(e).overflowY") == "auto"
            assert (
                node.get_by_role("scrollbar", name="Window vertical scrollbar").evaluate(
                    "e=>e.offsetWidth"
                )
                == 14
            )
            expect(node.locator(".scroll-window-corner")).to_be_visible()
        if view == "graph":
            expect(node).to_have_attribute("data-collapsed-tile", "false")
            expect(node.get_by_role("scrollbar", name="Window vertical scrollbar")).to_be_visible()
            assert (
                node.locator(".app-scrollport").evaluate("e=>getComputedStyle(e).overflowY")
                == "auto"
            )
        assert (
            node.locator(".mapping-drag-handle").evaluate(
                "e=>getComputedStyle(e).borderBottomStyle"
            )
            == "solid"
        )
        if shots:
            page.screenshot(
                path=f"{shots}/frames-{view}-{scheme}-{width}-expanded.png", full_page=True
            )
        for control, axis in ((horizontal, "x"), (vertical, "y")):
            expect(control).to_be_visible()
            assert control.evaluate("(e,axis)=>axis==='x'?e.offsetHeight:e.offsetWidth", axis) >= 23
            before = control.get_attribute("aria-valuenow")
            transform = canvas.get_attribute("style")
            control.hover()
            page.mouse.wheel(120 if axis == "x" else 0, 120 if axis == "y" else 0)
            expect(control).not_to_have_attribute("aria-valuenow", before)
            expect(canvas).not_to_have_attribute("style", transform)
        before = float(horizontal.get_attribute("aria-valuenow"))
        page.get_by_role("button", name="Move view right", exact=True).click()
        page.wait_for_function(
            "([e,before])=>Number(e.getAttribute('aria-valuenow'))>before",
            arg=[horizontal.element_handle(), before],
        )
        horizontal.focus()
        before = float(horizontal.get_attribute("aria-valuenow"))
        page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "([e,before])=>Number(e.getAttribute('aria-valuenow'))<before",
            arg=[horizontal.element_handle(), before],
        )
        horizontal.scroll_into_view_if_needed()
        box = horizontal.bounding_box()
        before = horizontal.get_attribute("aria-valuenow")
        page.mouse.click(box["x"] + box["width"] - 5, box["y"] + box["height"] - 5)
        expect(horizontal).not_to_have_attribute("aria-valuenow", before)
        thumb = horizontal.locator(".app-scrollbar-thumb").bounding_box()
        before = float(horizontal.get_attribute("aria-valuenow"))
        x, y = thumb["x"] + thumb["width"] / 2, thumb["y"] + thumb["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 24, y, steps=8)
        page.mouse.up()
        page.wait_for_function(
            "([e,before])=>Number(e.getAttribute('aria-valuenow'))<before",
            arg=[horizontal.element_handle(), before],
        )
        page.get_by_role("button", name="Fit view", exact=True).click()
        expect(horizontal).to_be_visible()
        expect(vertical).to_be_visible()
        try:
            page.wait_for_function(
                """e=>{
                const frame=e.closest('.diagram-frame').getBoundingClientRect();
                const box=e.getBoundingClientRect();
                return box.left>=frame.left && box.right<=frame.right &&
                    box.top>=frame.top && box.bottom<=frame.bottom;
            }""",
                arg=header.element_handle(),
            )
        except BrowserTimeout as error:
            raise AssertionError(
                header.evaluate(
                    """e=>({header:e.getBoundingClientRect().toJSON(),frame:e.closest('.diagram-frame').getBoundingClientRect().toJSON(),viewport:e.closest('.react-flow').querySelector('.react-flow__viewport').style.transform})"""
                )
            ) from error
        zoom = canvas.evaluate("e=>new DOMMatrix(getComputedStyle(e).transform).a")
        extent = float(horizontal.get_attribute("aria-valuemax"))
        page.get_by_role("button", name="Zoom in", exact=True).click()
        page.wait_for_function(
            "([e,before])=>new DOMMatrix(getComputedStyle(e).transform).a>before",
            arg=[canvas.element_handle(), zoom],
        )
        page.wait_for_function(
            "([e,before])=>Number(e.getAttribute('aria-valuemax'))>before",
            arg=[horizontal.element_handle(), extent],
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert problems == []
        browser.close()


@pytest.mark.parametrize("labels", ["id", "time"])
def test_native_grid_scrollbar_keeps_the_latest_run_clickable(mappings, labels):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": 1100, "height": 400}, show_scrollbars=True
        )
        sign_in(page, url, f"/ui/projects/default/pipelines/ORDERS?columns={labels}")
        divider = page.get_by_role("separator", name="Resize the panes", exact=True)
        divider.focus()
        for _ in range(30):
            page.keyboard.press("ArrowLeft")
        grid = page.get_by_role("table", name="Run grid")
        latest = grid.locator("thead th").last
        expect(latest).to_be_visible()
        area = grid.locator("xpath=parent::div/parent::div")
        page.wait_for_function("e=>e.offsetWidth>e.clientWidth", arg=area.element_handle())
        page.wait_for_function(
            """([area,latest])=>{
            const box=area.getBoundingClientRect(),item=latest.getBoundingClientRect();
            const left=box.left+area.clientLeft;
            return item.left>=left && item.right<=left+area.clientWidth+1;
        }""",
            arg=[area.element_handle(), latest.element_handle()],
        )
        grid.get_by_role("img", name=re.compile(r"^load in run .*: success$")).click()
        expect(page.get_by_label("Task load", exact=True)).to_be_visible()
        assert problems == []
        browser.close()


def test_phone_task_graph_starts_with_its_complete_root_before_parallel_waves(site):
    from etl_craft.core.actor import Actor, ActorKind, acting_as
    from fixtures.metadata import (
        add_dependency,
        add_pipeline,
        add_task,
        finish_run,
        start_run,
        task_run,
    )

    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "PARALLEL")
        root = add_task(conn, pipeline, "ROOT")
        tasks = [root]
        for number in range(4):
            branch = add_task(conn, pipeline, f"BRANCH_{number}")
            add_dependency(conn, pipeline, branch, root)
            tasks.append(branch)
        run = start_run(conn, pipeline)
        for task in tasks:
            task_run(conn, task, run)
        finish_run(conn, run)
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": 390, "height": 1000}, show_scrollbars=True
        )
        sign_in(page, url, "/ui/projects/default/pipelines/PARALLEL?view=graph&flow=lr")
        first = page.locator('[data-id="ROOT"] .diagram-node')
        expect(first).to_be_visible()
        page.wait_for_function(
            """()=>{
                const frame=document.querySelector('.react-flow').getBoundingClientRect();
                const root=document.querySelector('[data-id="ROOT"] .diagram-node');
                const box=root.getBoundingClientRect();
                return box.left>=frame.left&&box.top>=frame.top&&
                    box.right<=frame.right&&box.bottom<=frame.bottom;
            }"""
        )
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage"])
def test_expanded_window_scrolls_long_columns_without_moving_its_header_or_canvas(
    mappings, width, view
):
    from etl_craft.core.actor import acting_as
    from etl_craft.services.catalog.collect import build_catalog
    from etl_craft.services.catalog.site import write_site
    from etl_craft.services.operations.documents import docs_folder
    from fixtures.metadata import add_source_column

    ctx, url = mappings
    name = "extremely_long_source_column_name_that_needs_horizontal_scrolling_without_clipping"
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        add_source_column(conn, "raw.orders", name, "VARCHAR", 13)
    with acting_as(ctx.actor):
        write_site(build_catalog(ctx.engine, ctx.config), ctx.config, docs_folder(ctx.config))
    route = (
        "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping"
        if view == "mapping"
        else "/ui/projects/default/catalog/tables/mart.orders?tab=lineage"
    )
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, viewport={"width": width, "height": 1000}, show_scrollbars=True
        )
        sign_in(page, url, route)
        expect(page.locator(".diagram-frame")).to_have_attribute("data-fitted", "true")
        if view == "mapping":
            page.get_by_role("button", name="Show all columns", exact=True).click()
        else:
            page.get_by_role("button", name="Expand all", exact=True).click()
        identity = "source:raw.orders" if view == "mapping" else "raw.orders"
        node = page.locator(f'[data-id="{identity}"]')
        body = node.locator(".nowheel")
        expect(body).to_be_visible()
        assert body.evaluate("e=>e.scrollWidth>e.clientWidth")
        body.scroll_into_view_if_needed()
        header = node.locator(".mapping-drag-handle")
        before = header.bounding_box()
        canvas = page.locator(".react-flow__viewport")
        transform = canvas.get_attribute("style")
        body.hover()
        page.mouse.wheel(0, 900)
        page.wait_for_function("e=>e.scrollTop>0", arg=body.element_handle())
        page.mouse.wheel(1200, 0)
        page.wait_for_function(
            "e=>e.scrollLeft>0&&e.scrollLeft+e.clientWidth>=e.scrollWidth-1",
            arg=body.element_handle(),
        )
        last = node.locator(f'[data-port="{name}"] button > span > span').first
        expect(last).to_have_text(name)
        assert last.evaluate("e=>getComputedStyle(e).textOverflow") != "ellipsis"
        assert abs(header.bounding_box()["x"] - before["x"]) < 1
        assert abs(header.bounding_box()["y"] - before["y"]) < 1
        expect(canvas).to_have_attribute("style", transform)
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_mouse_resizing_stays_on_the_frame_instead_of_the_surrounding_canvas(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping")
        expect(page.locator(".diagram-frame")).to_have_attribute("data-fitted", "true")
        node = page.locator('[data-id="source:raw.orders"]')
        frame = node.locator(".diagram-node")
        resize = node.get_by_role("separator", name="Resize raw.orders width", exact=True)
        before = resize.get_attribute("aria-valuenow")
        box = frame.bounding_box()
        point = [box["x"] + box["width"] + 10, box["y"] + 8]
        assert page.evaluate(
            "p=>!document.elementFromPoint(...p).closest('.react-flow__resize-control')", point
        )
        canvas = page.locator(".react-flow__viewport")
        transform = canvas.get_attribute("style")
        page.mouse.move(*point)
        page.mouse.down()
        page.mouse.move(point[0] + 24, point[1], steps=8)
        page.mouse.up()
        expect(resize).to_have_attribute("aria-valuenow", before)
        expect(canvas).not_to_have_attribute("style", transform)
        box = frame.bounding_box()
        x, y = box["x"] + box["width"] - 1, box["y"] + 8
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 24, y, steps=8)
        page.mouse.up()
        expect(resize).not_to_have_attribute("aria-valuenow", before)
        assert int(resize.get_attribute("aria-valuenow")) > int(before)
        assert not problems
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", ["mapping", "lineage"])
def test_boundary_column_selection_ring_stays_inside_the_scrollport(mappings, width, view, scheme):
    _, url = mappings
    route = (
        "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping"
        if view == "mapping"
        else "/ui/projects/default/catalog/tables/mart.orders?tab=lineage"
    )
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw,
            viewport={"width": width, "height": 1000},
            color_scheme=scheme,
            show_scrollbars=True,
        )
        sign_in(page, url, route)
        expect(page.locator(".diagram-frame")).to_have_attribute("data-fitted", "true")
        if view == "mapping":
            page.get_by_role("button", name="Show all columns", exact=True).click()
        else:
            page.get_by_role("button", name="Expand all", exact=True).click()
        identity = "source:raw.orders" if view == "mapping" else "raw.orders"
        node = page.locator(f'[data-id="{identity}"]')
        rows = node.locator("[data-port] > button")
        expect(rows.first).to_be_visible()
        for boundary in ("first", "last"):
            row = rows.first if boundary == "first" else rows.last
            row.scroll_into_view_if_needed()
            row.click()
            expect(row).to_have_class(re.compile(r"ring-accent"))
            assert row.evaluate("""e=>{
                const style=getComputedStyle(e);
                const ring=style.getPropertyValue('--tw-ring-shadow');
                return ring.includes('inset') && style.boxShadow.includes('inset');
            }"""), "Selection must paint inside the row, including at either scroll boundary"
            shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                node.screenshot(path=f"{shots}/selection-{view}-{scheme}-{width}-{boundary}.png")
        assert not problems
        browser.close()
