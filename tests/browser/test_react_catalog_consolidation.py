"""Catalog removals retain their information at one accessible destination."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_lineage import mappings as mappings
from test_react_ui import open_page, sign_in

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("width", [1440, 390])
def test_mapping_is_a_diagram_and_column_sources_keeps_its_logic(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/tasks/ORDERS.load?tab=mapping")
        expect(page.get_by_label("Task mapping diagram", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Table view", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Full width", exact=True)).to_have_count(0)
        page.get_by_role("tab", name="Column sources", exact=True).click()
        sources = page.get_by_role("table", name="Column sources", exact=True)
        expect(sources).to_contain_text("raw.orders.amount")
        expect(sources).to_contain_text("Derived")
        document = page.request.get(
            url + "/api/v1/projects/default/catalog/page?path=catalog.json"
        ).json()
        task = next(task for task in document["tasks"] if task["label"] == "ORDERS.load")
        for edge in task["mapping"]["edges"]:
            expect(sources).to_contain_text(edge["target_column"])
            expect(sources).to_contain_text(edge["transformation"])
        logic = page.get_by_role("table", name="Task logic", exact=True)
        for step in task["mapping"]["steps"]:
            for row in step.get("logic", []):
                expect(logic).to_contain_text(row["expression"])
        expect(logic).to_contain_text("Filter")
        expect(page.get_by_role("tab", name="Runs", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_table_overview_is_the_only_writer_reader_fact_location(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/tables/mart.orders")
        expect(page.get_by_text("Written by", exact=True)).to_have_count(1)
        expect(page.get_by_text("Read by", exact=True)).to_have_count(1)
        about = page.get_by_role("complementary", name="About this table", exact=True)
        expect(about.get_by_role("link", name="ORDERS.load", exact=True)).to_be_visible()
        expect(page.get_by_role("table", name="Columns", exact=True)).to_contain_text("amount")
        page.get_by_role("tab", name="Column sources", exact=True).click()
        expect(page.get_by_text("Written by", exact=True)).to_have_count(0)
        expect(page.get_by_role("table", name="Column sources", exact=True)).to_contain_text(
            "ORDERS.load"
        )
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_catalog_pipeline_runs_link_and_old_address_reach_scoped_live_history(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/pipelines/ORDERS")
        expect(page.get_by_role("tab", name="Runs", exact=True)).to_have_count(0)
        page.get_by_role("link", name="Open pipeline runs", exact=True).click()
        page.wait_for_url(re.compile(r"/runs\?pipeline=ORDERS$"))
        expect(page.get_by_role("table", name="Pipeline runs", exact=True)).to_contain_text(
            "Success"
        )
        expect(page.get_by_role("combobox", name="Pipeline", exact=True)).to_have_value("ORDERS")
        page.goto(url + "/ui/projects/default/catalog/pipelines/ORDERS?tab=runs")
        page.wait_for_url(re.compile(r"/runs\?pipeline=ORDERS$"))
        expect(page.get_by_role("table", name="Pipeline runs", exact=True)).to_be_visible()
        assert not problems
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_catalog_sidebar_toggle_is_universal_and_independent_of_main_navigation(mappings, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog/tables/mart.orders")
        toggle = page.get_by_role("button", name=re.compile(r"^(Expand|Collapse) catalog sidebar$"))
        if toggle.get_attribute("aria-expanded") == "true":
            toggle.click()
        expect(page.get_by_role("tree", name="Catalog objects")).not_to_be_visible()
        toggle.press("Enter")
        expect(page.get_by_role("tree", name="Catalog objects")).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        controlled = toggle.get_attribute("aria-controls")
        expect(page.locator(f'[id="{controlled}"]')).to_be_visible()
        toggle.press("Enter")
        page.get_by_role("tab", name="Lineage diagram", exact=True).click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(page.get_by_role("button", name="Full width", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Restore tree", exact=True)).to_have_count(0)
        page.get_by_role("link", name="Catalog", exact=True).first.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.click()
        expect(page.get_by_role("tree", name="Catalog objects")).to_be_visible()
        if width == 1440:
            expect(page.get_by_role("navigation", name="Main", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not problems
        browser.close()
