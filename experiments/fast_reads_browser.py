"""Measure the bundled UI against a scratch HTTPS fixture in Chromium."""

import os
import shutil
import sys
import tempfile
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from playwright.sync_api import Error, sync_playwright
from sqlalchemy import event

from browser import conftest
from browser.test_react_ui import open_page, sign_in
from fixtures.catalog_scale import seed_catalog
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.services.catalog.collect import collect_catalog
from etl_craft.services.operations import catalog_pages
from fast_reads import encode, index_triggers

measurement = ContextVar("measurement", default=None)
metrics = []


def instrument(ctx, **kwargs):
    app = real_app(ctx, **kwargs)

    def before(*args):
        sample = measurement.get()
        if sample is not None:
            sample[2] += 1
            sample[4] = perf_counter()

    def after(*args):
        sample = measurement.get()
        if sample is not None:
            sample[3] += perf_counter() - sample[4]

    event.listen(ctx.engine, "before_cursor_execute", before)
    event.listen(ctx.engine, "after_cursor_execute", after)

    async def measured(scope, receive, send):
        if not scope.get("path", "").startswith("/api/v1/"):
            return await app(scope, receive, send)
        sample = [scope["path"].removeprefix("/api/v1/"), 0, 0, 0.0, 0.0, 0]
        token = measurement.set(sample)
        start = perf_counter()

        async def capture(message):
            if message["type"] == "http.response.start":
                sample[5] = message["status"]
            if message["type"] == "http.response.body":
                sample[1] += len(message.get("body", b""))
            await send(message)

        try:
            await app(scope, receive, capture)
        finally:
            metrics.append((*sample[:4], sample[5], perf_counter() - start))
            measurement.reset(token)

    return measured


real_app = conftest.create_app
conftest.create_app = instrument


def run(size, demo):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        seed_database = os.environ.get("FAST_READS_SEED_DB")
        if seed_database:
            shutil.copy2(seed_database, root / "engine.db")
        if not size:
            shutil.copy2(demo / "engine.db", root / "engine.db")
            shutil.copytree(demo / "catalog", root / "catalog")
        init = conftest.init_db
        if not size or seed_database:
            conftest.init_db = lambda engine: None
        original_folder = catalog_pages._folder
        catalog_pages._folder = lambda ctx: root / "catalog"
        fixture = conftest.site.__wrapped__(root, SimpleNamespace())
        try:
            ctx, base = next(fixture)
        finally:
            conftest.init_db = init
        try:
            if size:
                with acting_as(SYSTEM_ACTOR):
                    with ctx.engine.begin() as conn:
                        if not seed_database:
                            seed_catalog(conn, prefix="SCALE", pipelines=size, tasks=10, runs=25)
                        conn.exec_driver_sql("UPDATE AUD_PIPELINES_RUN_LOG SET RUN_DATE = date(START_DATE) WHERE RUN_DATE IS NULL")
                    if size == 5000:
                        from fast_reads_runs import benchmark
                        benchmark(ctx.engine)
                    if size < 5000 or os.environ.get("FAST_READS_LARGE_CATALOG"):
                        catalog = collect_catalog(ctx.engine, ctx.config, record_lineage=False)
                        output = root / "catalog"
                        output.mkdir(parents=True, exist_ok=True)
                        (output / ".etl-craft-catalog").write_text('{"project":"default"}')
                        (output / "catalog.json").write_bytes(encode(index_triggers(catalog)))
            pipeline = "SCALE_0" if size else "DEMO"
            with ctx.engine.connect() as conn:
                run_id = conn.exec_driver_sql(
                    "SELECT max(r.PIPELINE_RUN_ID) FROM AUD_PIPELINES_RUN_LOG r "
                    "JOIN CFG_PIPELINES p ON p.PIPELINE_ID = r.PIPELINE_ID WHERE p.PIPELINE_CODE = ?",
                    (pipeline,),
                ).scalar_one()
            project = f"{base}/ui/projects/default"
            with sync_playwright() as pw:
                for name, relative in (
                    ("home", ""), ("history", "/runs"), ("grid", f"/pipelines/{pipeline}"),
                    ("graph", f"/pipelines/{pipeline}"), ("run", f"/runs/{pipeline}/{run_id}"),
                    ("task", f"/pipelines/{pipeline}?run={run_id}"), ("catalog", "/catalog"),
                    ("lineage", "/catalog/tables/scale.scale_t_0?tab=lineage" if size else "/catalog"),
                ):
                    if os.environ.get("FAST_READS_CATALOG_ONLY") and name not in {"catalog", "lineage"}:
                        continue
                    if size == 5000 and not os.environ.get("FAST_READS_LARGE_CATALOG") and name in {"catalog", "lineage"}:
                        continue
                    if not size and name == "lineage":
                        continue
                    browser, page, _ = open_page(pw, viewport={"width": 1440, "height": 950})
                    try:
                        sign_in(page, base, "/ui/agents")
                        page.wait_for_load_state("networkidle")
                        for phase in ("fresh route", "reload"):
                            metrics.clear()
                            requests = []
                            def requested(req):
                                if "/api/v1/" in req.url:
                                    requests.append(req.url.split("/api/v1/", 1)[1].split("?")[0])
                            page.on("request", requested)
                            start = perf_counter()
                            try:
                                page.goto(project + relative, wait_until="domcontentloaded", timeout=20000)
                                if name in {"grid", "graph", "task"}:
                                    page.get_by_role("table", name="Run grid").wait_for(timeout=10000)
                                if name == "graph":
                                    page.get_by_role("button", name="Graph", exact=True).click(timeout=10000)
                                    page.get_by_role("group", name="Task graph").wait_for(timeout=10000)
                                elif name == "task":
                                    table = page.get_by_role("table", name="Task instances")
                                    button = table.get_by_role("button").first
                                    task_code = button.inner_text(timeout=10000)
                                    button.click(timeout=10000)
                                    page.get_by_role("region", name=f"Task {task_code}").wait_for(timeout=10000)
                                elif name == "home":
                                    page.get_by_role("heading", name="Home", exact=True).wait_for(timeout=10000)
                                elif name in {"catalog", "lineage"}:
                                    page.get_by_role("tree", name="Catalog objects").wait_for(timeout=10000)
                                elif name == "run":
                                    page.get_by_role("heading", name=f"Run #{run_id}", exact=True).wait_for(timeout=10000)
                                else:
                                    page.get_by_role("table").first.wait_for(timeout=10000)
                                print(size, name, phase, "usable", round(perf_counter()-start, 3), flush=True)
                                page.wait_for_load_state("networkidle", timeout=12000)
                            except Error:
                                print(size, name, phase, "readiness selector missed", flush=True)
                            finally:
                                page.remove_listener("request", requested)
                            print("requests", requests, flush=True)
                            for path, count_bytes, sql, db, status, elapsed in metrics:
                                print(path, status, count_bytes, sql, round(db*1000, 1), round(elapsed*1000, 1), flush=True)
                    finally:
                        browser.close()
        finally:
            fixture.close()
            catalog_pages._folder = original_folder


if __name__ == "__main__":
    run(int(sys.argv[1]), Path(sys.argv[2]))
