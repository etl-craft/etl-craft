"""Catalog lineage in the new interface: refresh it, rebuild the catalog, read the traced paths."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from fixtures.metadata import add_pipeline, add_task

pytestmark = pytest.mark.browser


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        page.wait_for_function("""() => [...document.querySelectorAll('.diagram-body')]
            .every(element=>element.getAnimations().every(animation=>animation.playState==='finished'))
        """)
        Path(shots).mkdir(parents=True, exist_ok=True)
        if name.startswith("catalog-flow"):
            page.get_by_role("group", name="Task graph", exact=True).screenshot(
                path=f"{shots}/{name}.png"
            )
        else:
            page.screenshot(path=f"{shots}/{name}.png", full_page=True)


@pytest.fixture
def chain(site):
    """INGEST stages raw orders, SALES converts them to dollars, MART sums them."""
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        from fixtures.metadata import add_source_column

        for table, columns in [
            ("raw.orders", [("id", "BIGINT"), ("amt", "BIGINT"), ("currency", "VARCHAR")]),
            ("ref.rates", [("currency", "VARCHAR"), ("rate", "BIGINT")]),
        ]:
            for position, (name, data_type) in enumerate(columns, 1):
                add_source_column(conn, table, name, data_type, position)
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
        summary = page.locator("dl").filter(has=page.get_by_text("Open gaps", exact=True))
        expect(summary.get_by_text("Last written", exact=True)).to_be_visible()
        expect(summary.get_by_text("Open gaps", exact=True)).to_be_visible()
        page.get_by_role("tab", name="Object lineage", exact=True).click()
        page.get_by_role("button", name="List", exact=True).click()
        expect(
            page.get_by_role("table", name="Upstream and downstream tables").get_by_role(
                "link", name="sales.orders"
            )
        ).to_be_visible()
        assert [p for p in problems if "status of 404" not in p] == []
        browser.close()


@pytest.fixture
def mappings(site):
    from etl_craft.services.catalog.collect import build_catalog
    from etl_craft.services.catalog.site import write_site
    from etl_craft.services.operations.documents import docs_folder
    from fixtures.metadata import add_dependency, add_pipeline_dependency, add_source_column

    ctx, url = site
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        upstream = add_pipeline(conn, "EXTRACT")
        pipeline = add_pipeline(conn, "ORDERS")
        from sqlalchemy import text

        conn.execute(
            text("UPDATE CFG_PIPELINES SET RUN_SCHEDULE='0 6 * * *' WHERE PIPELINE_ID=:pipeline"),
            {"pipeline": pipeline},
        )
        downstream = add_pipeline(conn, "REPORT")
        add_pipeline_dependency(conn, pipeline, upstream, "HAS_DATA")
        add_pipeline_dependency(conn, downstream, pipeline)
        for table, names in [
            ("raw.orders", ["id", "amount"]),
            ("mart.orders", ["id", "amount"]),
            ("raw.accounts", ["id"]),
            ("ref.rates", ["id", "factor"]),
        ]:
            for position, name in enumerate(names, 1):
                add_source_column(conn, table, name, "BIGINT", position)
        for position in range(3, 13):
            add_source_column(conn, "raw.orders", f"extra_{position}", "BIGINT", position)
        extract = add_task(
            conn,
            pipeline,
            "extract",
            "PYTHON",
            TARGET_OBJECT="raw.accounts",
            SCRIPT_FILE="extract.py",
            LINEAGE_SOURCE="salesforce.Account",
            LINEAGE_COLUMNS="Id:id",
        )
        load = add_task(
            conn,
            pipeline,
            "load",
            SQL_ACTION="SCD2_MERGE",
            TARGET_OBJECT="mart.orders",
            SELECT_QUERY=(
                "SELECT o.id, o.amount * r.factor AS amount FROM raw.orders o "
                "JOIN ref.rates r ON o.id=r.id WHERE o.amount > 0"
            ),
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="amount",
            RETRIES="3",
            TASK_TIMEOUT_SECONDS="1800",
        )
        add_task(
            conn,
            pipeline,
            "cleanup",
            "PYTHON",
            SCRIPT_KIND="UTILITY",
            SCRIPT_FILE="cleanup.py",
            TARGET_OBJECT="mart.orders",
        )
        add_dependency(conn, pipeline, load, extract, "HAS_DATA")
        disabled = add_task(
            conn, pipeline, "disabled", "PYTHON", SCRIPT_KIND="UTILITY", SCRIPT_FILE="disabled.py"
        )
        conn.execute(
            text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N' WHERE TASK_ID=:task"), {"task": disabled}
        )
        from etl_craft.core.enums import RunStatus
        from etl_craft.engine import transitions
        from fixtures.metadata import start_run

        run = start_run(conn, pipeline)
        conn.execute(
            text(
                "INSERT INTO AUD_TASK_RUN_LOG(PIPELINE_RUN_ID,TASK_ID,STATUS,START_DATE,END_DATE) "
                "VALUES(:run,:task,'SUCCESS',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"run": run, "task": load},
        )
        transitions.finalize_pipeline_run(conn, run, RunStatus.SUCCESS)
    with acting_as(ctx.actor):
        write_site(build_catalog(ctx.engine, ctx.config), ctx.config, docs_folder(ctx.config))
    return ctx, url


def uniform_graph_nodes(page, expanded=False):
    try:
        page.wait_for_function(
            """expanded => {
            const canvas=document.querySelector('[aria-label="Task graph"] .react-flow');
            const nodes=[...canvas.querySelectorAll('.react-flow__node')];
            const pane=canvas.getBoundingClientRect();
            return nodes.length>1 && nodes.every(node=>{
                const box=node.getBoundingClientRect();
                return box.left>=pane.left-1 && box.right<=pane.right+1
                    && box.top>=pane.top-1 && box.bottom<=pane.bottom+1;
            });
        }""",
            arg=expanded,
        )
    except BrowserTimeout:
        page.screenshot(path="/tmp/catalog-flow/fit-failure.png")
        pytest.fail(
            str(
                page.evaluate("""() => {
            const canvas=document.querySelector('[aria-label="Task graph"] .react-flow');
            const pane=canvas.getBoundingClientRect();
            return {pane:pane.toJSON(),nodes:[...canvas.querySelectorAll(".react-flow__node")]
                .map(node=>({id:node.dataset.id,box:node.getBoundingClientRect().toJSON()}))};
        }""")
            )
        )


@pytest.mark.parametrize(
    "appearance,width", [("light", 1280), ("dark", 1280), ("light", 390), ("dark", 390)]
)
def test_native_flow_mapping_provenance_and_keyboard(mappings, appearance, width):
    _, url = mappings
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": width, "height": 1000})
        page.emulate_media(color_scheme=appearance)
        sign_in(page, url, "/ui/projects/default/catalog/pipelines/ORDERS?tab=lineage")
        expect(page.get_by_role("group", name="Task graph")).to_be_visible()
        expect(page.get_by_text("Succeeded", exact=True)).to_be_visible()
        expect(page.locator('[data-id="load"]')).to_be_visible()
        expect(page.locator('[data-id="disabled"] [data-focus]')).to_have_css("opacity", "0.4")
        uniform_graph_nodes(page)
        load_node = page.locator('[data-id="load"]')
        expect(load_node.locator(".lucide-history")).to_be_visible()
        expect(page.locator('[data-id^="Schedule:"] .lucide-calendar-clock')).to_be_visible()
        expect(page.locator('[data-id^="Schedule:"] strong')).to_have_attribute(
            "title", "0 6 * * *"
        )
        page.get_by_role("button", name="Expand cleanup", exact=True).click()
        page.wait_for_function("""() => {
            const graph=document.querySelector('[aria-label="Task graph"]');
            const nodes=[...graph.querySelectorAll('.react-flow__node')];
            const bounds=nodes.map(node=>node.getBoundingClientRect());
            return bounds.every((box,index)=>bounds.slice(index+1).every(other=>
                box.right<=other.left+1 || other.right<=box.left+1
                || box.bottom<=other.top+1 || other.bottom<=box.top+1));
        }""")
        page.get_by_role("button", name="Collapse cleanup", exact=True).click()
        page.get_by_role("button", name="Expand all", exact=True).click()
        uniform_graph_nodes(page, expanded=True)
        expect(
            page.locator('[data-id="disabled"]').get_by_text("Inactive", exact=True)
        ).to_be_visible()
        shoot(page, f"catalog-flow-expanded-{appearance}-{width}")
        expect(load_node.get_by_text("mart.orders", exact=True)).to_be_visible()
        page.get_by_role("button", name="Collapse all", exact=True).click()
        expect(load_node.get_by_text("mart.orders", exact=True)).to_have_count(0)
        page.get_by_role("button", name="Expand load", exact=True).click()
        expect(load_node.get_by_text("mart.orders", exact=True)).to_be_visible()
        page.get_by_role("button", name="Collapse load", exact=True).click()
        page.get_by_role("switch", name="Show last-run status", exact=True).check()
        expect(load_node.locator(".lucide-history")).to_be_visible()
        expect(page.locator('[data-id="load"]')).to_contain_text("Success")
        load_node.focus()
        load_node.press("ArrowRight")
        load_node.focus()
        expect(load_node).to_be_focused()
        expect(load_node).to_have_css("outline-style", "solid")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        shoot(page, f"catalog-flow-{appearance}-{width}")
        load_node.press("Enter")
        expect(page.get_by_role("complementary", name="Task definition")).to_be_visible()
        page.get_by_role("link", name="Open mapping", exact=True).click()
        if width == 390:
            expect(page.get_by_role("table", name="Task mapping")).to_be_visible()
            shoot(page, f"catalog-mapping-derived-{appearance}-{width}")
            page.get_by_role("button", name="Diagram", exact=True).click()
        diagram = page.get_by_label("Task mapping diagram")
        expect(diagram).to_be_visible()
        expect(diagram.locator("path.react-flow__edge-path").first).to_have_attribute(
            "marker-end", re.compile("url")
        )
        expect(
            diagram.locator('[data-id="step:0"] [data-port="raw.orders.amount"]')
        ).to_be_attached()
        page.get_by_role("button", name="Collapse all", exact=True).click()
        expect(diagram.locator("[data-port]")).to_have_count(0)
        shoot(page, f"catalog-mapping-collapsed-{appearance}-{width}")
        page.get_by_role("button", name="Expand raw.orders", exact=True).click()
        expect(
            diagram.locator('[data-id="source:raw.orders"] [data-port="amount"]')
        ).to_be_visible()
        expect(diagram.locator('[data-id="target:mart.orders"] [data-port]')).to_have_count(0)
        page.get_by_role("button", name="Expand all", exact=True).click()
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.wait_for_function("""() => {
            const canvas=document.querySelector('[aria-label="Task mapping diagram"] .react-flow');
            const pane=canvas.getBoundingClientRect();
            return [...canvas.querySelectorAll('.react-flow__node')].every(node=>{
                const box=node.getBoundingClientRect();
                return box.left>=pane.left-1 && box.right<=pane.right+1
                    && box.top>=pane.top-1 && box.bottom<=pane.bottom+1;
            });
        }""")
        page.get_by_role("button", name="Reset zoom", exact=True).click()
        expect(diagram.locator(".react-flow__viewport")).to_have_css(
            "transform", re.compile(r"matrix\(1, 0, 0, 1,")
        )
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.get_by_role("button", name="Show all columns", exact=True).click()
        page.wait_for_function("""() => {
            const first = document.querySelector('[data-id="source:raw.orders"]');
            const second = document.querySelector('[data-id="source:ref.rates"]');
            return first && second
                && first.getBoundingClientRect().bottom <= second.getBoundingClientRect().top;
        }""")
        page.get_by_role("button", name="Used columns", exact=True).click()
        page.get_by_role("button", name="Fit view", exact=True).click()
        target = diagram.locator('[data-id="target:mart.orders"]').get_by_role(
            "button", name="amount", exact=False
        )
        target.click()
        page.wait_for_function("""() => {
            const canvas=document.querySelector('[aria-label="Task mapping diagram"] .react-flow');
            const pane=canvas.getBoundingClientRect();
            return [...canvas.querySelectorAll('.react-flow__node')].every(node=>{
                const box=node.getBoundingClientRect();
                return box.left>=pane.left-1 && box.right<=pane.right+1
                    && box.top>=pane.top-1 && box.bottom<=pane.bottom+1;
            });
        }""")
        expect(
            diagram.locator('[data-id="source:raw.orders"]').get_by_role(
                "button", name="amount", exact=False
            )
        ).to_have_class(re.compile("ring-2"))
        expect(diagram.locator('[data-id="expression"] button.ring-2')).to_have_count(3)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        shoot(
            page,
            f"catalog-mapping-derived{'-diagram' if width == 390 else ''}-{appearance}-{width}",
        )
        page.get_by_role("textbox", name="Find a column", exact=True).fill("factor")
        expect(
            diagram.locator('[data-id="source:ref.rates"]').get_by_role(
                "button", name="factor", exact=False
            )
        ).to_be_visible()
        expect(target).to_be_visible()
        page.get_by_role("textbox", name="Find a column", exact=True).fill("")
        page.goto(url + "/ui/projects/default/catalog/tasks/ORDERS.extract?tab=mapping")
        expect(page.get_by_role("note")).to_contain_text("doesn't verify")
        if width == 390:
            expect(page.get_by_role("table", name="Task mapping")).to_be_visible()
            shoot(page, f"catalog-mapping-declared-{appearance}-{width}")
            page.get_by_role("button", name="Diagram", exact=True).click()
        expect(
            page.get_by_label("Task mapping diagram").get_by_text("Declared", exact=True).first
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        shoot(
            page,
            f"catalog-mapping-declared{'-diagram' if width == 390 else ''}-{appearance}-{width}",
        )
        page.goto(url + "/ui/projects/default/catalog/tasks/ORDERS.cleanup?tab=mapping")
        expect(page.get_by_role("note")).to_contain_text("arbitrary code")
        expect(page.get_by_role("toolbar")).to_have_count(0)
        expect(page.get_by_label("Task mapping diagram")).to_have_count(0)
        expect(page.get_by_role("alert")).to_have_count(0)
        shoot(page, f"catalog-mapping-unavailable-{appearance}-{width}")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert problems == []
        browser.close()
