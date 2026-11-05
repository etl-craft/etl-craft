"""Catalog lineage in the new interface: refresh it, rebuild the catalog, read the traced paths."""

import os
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
    expect(page.get_by_title("default generated catalog")).to_be_visible()


def squashed(locator):
    return " ".join(locator.inner_text().split())


def test_refreshing_and_rebuilding_shows_the_traced_chain_and_the_api_agrees(chain):
    _, url = chain
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/app/projects/default/catalog")
        page.get_by_role("button", name="Refresh lineage").click()
        page.get_by_role("dialog").get_by_role("button", name="Refresh lineage").click()
        done = page.get_by_role("status").filter(has_text="Lineage refreshed: 3 task(s) traced.")
        expect(done).to_be_visible()
        expect(page.get_by_text("3 of 3 task(s) traced")).to_be_visible()
        rebuild(page)

        # the catalog's own pages, inside the frame, name the same writers and readers
        frame = page.frame_locator("iframe[title='default generated catalog']")
        expect(frame.get_by_text("Untraced SQL tasks")).to_be_visible()
        frame.get_by_role("link", name="Warehouse").first.click()
        expect(frame.get_by_text("Read by").first).to_be_visible()
        warehouse = squashed(frame.locator("body"))
        for table in (
            "mart Table Columns Written by Read by Pipelines Rules daily 6 MART.daily MART",
            "raw Table Columns Written by Read by Pipelines Rules orders 3 INGEST.stage INGEST",
            "ref Table Columns Written by Read by Pipelines Rules rates 1 SALES.convert SALES",
            "sales Table Columns Written by Read by Pipelines Rules orders 7 SALES.convert"
            " MART.daily MART, SALES",
            "staging Table Columns Written by Read by Pipelines Rules orders 7 INGEST.stage"
            " SALES.convert INGEST, SALES",
        ):
            assert table in warehouse, table
        frame.locator("a[href='tables/sales.orders.html']").first.click()
        expect(frame.get_by_text("Table rule results")).to_be_visible()
        table = squashed(frame.locator("body"))
        assert "Written by SALES.convert Read by MART.daily" in table
        assert "staging.orders.id copy (SALES.convert)" in table
        assert "ref.rates.rate o.amount * r.rate (SALES.convert)" in table
        assert "staging.orders.amount o.amount * r.rate (SALES.convert)" in table
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
        sign_in(page, url, "/app/projects/default/catalog")
        page.get_by_role("button", name="Refresh lineage").click()
        page.get_by_role("dialog").get_by_role("button", name="Refresh lineage").click()
        said = page.get_by_role("status").filter(has_text="Lineage refreshed with errors")
        expect(said).to_contain_text("3 of 4 task(s) traced; 1 could not be traced")
        untraced = page.get_by_role("list", name="Tasks that could not be traced")
        expect(untraced).to_contain_text("BROKEN.oops")
        expect(untraced).to_contain_text("must be a read-only SELECT")
        shoot(page, "catalog-lineage-errors")
        rebuild(page)
        frame = page.frame_locator("iframe[title='default generated catalog']")
        expect(frame.get_by_text("1 task(s)")).to_be_visible()  # Untraced SQL tasks
        browser.close()
