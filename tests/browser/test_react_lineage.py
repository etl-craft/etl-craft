"""Catalog lineage in the new interface: refresh it, rebuild the catalog, read the traced paths."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from fixtures.metadata import add_pipeline, add_task

pytestmark = pytest.mark.browser


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


@pytest.fixture
def chain(site):
    """INGEST stages raw orders, SALES converts them to dollars, MART sums them."""
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        ingest = add_pipeline(conn, "INGEST")
        add_task(
            conn,
            ingest,
            "stage",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="staging.orders",
            SELECT_QUERY="SELECT id, amt AS amount, currency FROM raw.orders",
        )
        sales = add_pipeline(conn, "SALES")
        add_task(
            conn,
            sales,
            "convert",
            SQL_ACTION="OVERWRITE_TABLE",
            TARGET_OBJECT="sales.orders",
            SELECT_QUERY=(
                "SELECT o.id, o.amount * r.rate AS amount_usd "
                "FROM staging.orders o JOIN ref.rates r ON r.currency = o.currency"
            ),
        )
        mart = add_pipeline(conn, "MART")
        add_task(
            conn,
            mart,
            "daily",
            SQL_ACTION="OVERWRITE_TABLE",
            TARGET_OBJECT="mart.daily",
            SELECT_QUERY="SELECT SUM(amount_usd) AS total FROM sales.orders",
        )
    return ctx, url


def rebuild(page):
    page.get_by_role("button", name="Rebuild catalog").click()
    page.get_by_role("dialog").get_by_role("button", name="Rebuild catalog").click()
    expect(page.get_by_role("tree", name="Catalog objects")).to_be_visible()


def squashed(locator):
    return " ".join(locator.inner_text().split())


def test_refreshing_and_rebuilding_shows_the_traced_chain_and_the_api_agrees(chain):
    _, url = chain
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog")
        page.get_by_role("button", name="More catalog actions").click()
        page.get_by_role("menuitem").filter(has_text="Refresh lineage").click()
        page.get_by_role("dialog").get_by_role("button", name="Refresh lineage").click()
        done = page.get_by_role("status").filter(has_text="Lineage refreshed: 3 task(s) traced.")
        expect(done).to_be_visible()
        expect(page.get_by_text("3 of 3 task(s) traced")).to_be_visible()
        rebuild(page)

        # the explorer names the same writers and readers
        tree = page.get_by_role("tree", name="Catalog objects")
        expect(tree.get_by_text("Warehouse (", exact=False)).to_be_visible()
        expect(page.get_by_text("Untraced", exact=False)).to_have_count(0)
        tree.get_by_role("treeitem", name=re.compile("^sales")).click()
        tree.get_by_role("treeitem", name="orders", exact=True).click()
        expect(page.get_by_role("heading", name="orders")).to_be_visible()
        about = page.get_by_label("About this table")
        expect(about.get_by_role("link", name="SALES.convert")).to_be_visible()
        expect(about.get_by_role("link", name="MART.daily")).to_be_visible()
        page.get_by_role("tab", name="Object lineage", exact=True).click()
        graph = page.get_by_role("group", name="Task graph")
        expect(graph).to_be_visible()
        # narrowing the graph redraws it: no leftover edge to a table that is no longer drawn
        page.get_by_label("Direction").select_option("down")
        page.get_by_label("Depth").select_option("1")
        expect(graph.locator("[data-focus]")).to_have_count(2)
        expect(graph.locator(".react-flow__edge")).to_have_count(1)
        page.get_by_role("tab", name="Column lineage").click()
        lineage = page.get_by_role("table", name="Column lineage")
        expect(lineage).to_contain_text("staging.orders.amount")
        expect(lineage).to_contain_text("ref.rates.rate")
        expect(lineage).to_contain_text("SALES.convert")
        shoot(page, "catalog-table")

        # the same trace through the action the command line uses, column by column
        api = url + "/api/v1/projects/default/lineage"
        column = page.request.get(api + "?table=mart.daily&column=total&direction=UPSTREAM").json()
        edges = {
            (depth, e["target_object"], e["target_column"], e["source_object"], e["source_column"])
            for depth, e in column["upstream_columns"]
        }
        assert edges == {
            (1, "mart.daily", "total", "sales.orders", "amount_usd"),
            (2, "sales.orders", "amount_usd", "ref.rates", "rate"),
            (2, "sales.orders", "amount_usd", "staging.orders", "amount"),
            (3, "staging.orders", "amount", "raw.orders", "amt"),
        }
        assert column["failed"] is False
        tables = page.request.get(api + "?table=raw.orders&direction=DOWNSTREAM").json()
        assert tables["downstream_tables"] == [
            [1, "staging.orders", "INGEST.stage"],
            [2, "sales.orders", "SALES.convert"],
            [3, "mart.daily", "MART.daily"],
        ]
        upstream = page.request.get(api + "?table=mart.daily&direction=UPSTREAM").json()
        assert {(depth, name) for depth, name, _ in upstream["upstream_tables"]} == {
            (1, "sales.orders"),
            (2, "staging.orders"),
            (2, "ref.rates"),
            (3, "raw.orders"),
        }
        # the only console noise allowed is the server saying the catalog is not generated yet
        assert [p for p in problems if "status of 404" not in p] == []
        browser.close()


def test_a_task_that_cannot_be_traced_is_named_with_its_reason_and_counted(chain):
    ctx, url = chain
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        broken = add_pipeline(conn, "BROKEN")
        add_task(
            conn,
            broken,
            "oops",
            SQL_ACTION="OVERWRITE_TABLE",
            TARGET_OBJECT="bad.t",
            SELECT_QUERY="SELEC FROM WHERE",
        )
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog")
        page.get_by_role("button", name="More catalog actions").click()
        page.get_by_role("menuitem").filter(has_text="Refresh lineage").click()
        page.get_by_role("dialog").get_by_role("button", name="Refresh lineage").click()
        said = page.get_by_role("status").filter(has_text="Lineage refreshed with errors")
        expect(said).to_contain_text("3 of 4 task(s) traced; 1 could not be traced")
        untraced = page.get_by_role("list", name="Tasks that could not be traced")
        expect(untraced).to_contain_text("BROKEN.oops")
        expect(untraced).to_contain_text("must be a read-only SELECT")
        shoot(page, "catalog-lineage-errors")
        rebuild(page)
        expect(page.get_by_role("tree", name="Catalog objects")).to_be_visible()
        browser.close()


def test_all_tables_lists_every_table_and_filters_by_name(chain):
    _, url = chain
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/catalog")
        page.get_by_role("button", name="More catalog actions").click()
        page.get_by_role("menuitem").filter(has_text="Refresh lineage").click()
        page.get_by_role("dialog").get_by_role("button", name="Refresh lineage").click()
        expect(page.get_by_role("status").filter(has_text="Lineage refreshed")).to_be_visible()
        rebuild(page)
        page.get_by_role("tree", name="Catalog objects").get_by_role(
            "treeitem", name="All tables"
        ).click()
        table = page.get_by_role("table", name="All tables")
        expect(table.get_by_role("link", name="sales.orders")).to_be_visible()
        expect(table.get_by_role("link", name="mart.daily")).to_be_visible()
        page.get_by_label("Find a table").fill("mart")
        expect(table.get_by_role("link", name="sales.orders")).to_have_count(0)
        expect(table.get_by_role("link", name="mart.daily")).to_be_visible()
        # a table's page leads with how fresh and how checked it is
        table.get_by_role("link", name="mart.daily").click()
        expect(page.get_by_text("Last written")).to_be_visible()
        expect(page.get_by_text("Open gaps")).to_be_visible()
        page.get_by_role("tab", name="Object lineage", exact=True).click()
        page.get_by_role("button", name="List", exact=True).click()
        expect(
            page.get_by_role("table", name="Upstream and downstream tables").get_by_role(
                "link", name="sales.orders"
            )
        ).to_be_visible()
        assert [p for p in problems if "status of 404" not in p] == []
        browser.close()
