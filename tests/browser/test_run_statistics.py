"""Real stored runs and logs in the run and pipeline task panels across themes."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_ui import open_page, shoot, sign_in

from etl_craft.config.targets import active_catalog
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.counts import Counts
from etl_craft.core.enums import FailureClass
from etl_craft.core.error_anchors import ErrorAnchors, ErrorEvent
from etl_craft.core.failures import Failure
from etl_craft.engine import transitions
from etl_craft.engine.attempt_resources import AttemptResources, record_resources
from etl_craft.execution.attempt_records import attempt_log_path
from etl_craft.services.retention import retaining
from etl_craft.warehouse.connection import open_warehouse
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run

pytestmark = pytest.mark.browser


@pytest.fixture
def triage(site):
    ctx, url = site
    with acting_as(SYSTEM_ACTOR), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "TRIAGE")
        tasks = {
            name: add_task(conn, pipeline, name, "PYTHON" if name == "PYTHON_JOB" else "SQL")
            for name in ("PYTHON_JOB", "COMPACT", "LIVE", "RETRY", "EXPIRED")
        }
        tasks["LOAD"] = add_task(conn, pipeline, "LOAD", TARGET_OBJECT="main.sales")
        for _ in range(2):
            historical = start_run(conn, pipeline)
            _attempt(conn, ctx, historical, tasks["COMPACT"], "COMPACT", 1, "SUCCESS", 2)
            finish_run(conn, historical)
        run = start_run(conn, pipeline)
        rss = []
        load = _attempt(conn, ctx, run, tasks["LOAD"], "LOAD", 1, "FAILED", 8)
        rss.append(load)
        task_run = conn.execute(
            text("SELECT TASK_RUN_ID FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:attempt"),
            {"attempt": load},
        ).scalar_one()
        rss.append(_attempt(conn, ctx, run, tasks["COMPACT"], "COMPACT", 1, "SUCCESS", 20))
        _attempt(conn, ctx, run, tasks["PYTHON_JOB"], "PYTHON_JOB", 1, "SUCCESS", 2)
        _attempt(conn, ctx, run, tasks["LIVE"], "LIVE", 1, "RUNNING", 2)
        _attempt(conn, ctx, run, tasks["RETRY"], "RETRY", 1, "FAILED", 2)
        _attempt(conn, ctx, run, tasks["RETRY"], "RETRY", 2, "SUCCESS", 3)
        expired = _attempt(conn, ctx, run, tasks["EXPIRED"], "EXPIRED", 1, "FAILED", 1)
        with retaining():
            conn.execute(
                text("UPDATE AUD_TASK_ATTEMPTS SET LOG_REMOVED_AT=:date WHERE ATTEMPT_ID=:id"),
                {"date": datetime.now(UTC), "id": expired},
            )
    with acting_as(SYSTEM_ACTOR):
        for attempt in rss:
            record_resources(ctx.engine, attempt, "browser", AttemptResources(220 * 1024**2, 4))
    table = f"{active_catalog(ctx.config)}.main.sales__rejects"
    with open_warehouse(ctx.config) as warehouse, warehouse.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {table} (PIPELINE_ID BIGINT, PIPELINE_RUN_ID BIGINT, "
                "TASK_RUN_ID BIGINT, REJECT_REASON VARCHAR)"
            )
        )
        conn.execute(
            text(f"INSERT INTO {table} VALUES (:pipeline,:run,:task,:reason)"),
            [
                {"pipeline": pipeline, "run": run, "task": task_run, "reason": reason}
                for reason in ["invalid integer"] * 8 + ["overflow"] * 2
            ],
        )
    return url, run


def _attempt(conn, ctx, run, task, code, number, status, duration):
    task_run = transitions.find_or_create_task_run(conn, task, run).task_run_id
    path = attempt_log_path(ctx.config, "TRIAGE", run, code, number, project_id=1)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    log = "2026-11-28T00:00:00Z INFO task: read source: 1200 row(s) (0.12s)\n"
    if status == "FAILED":
        log += (
            "2026-11-28T00:00:01Z ERROR task: [event 1] duplicate key value\n"
            "2026-11-28T00:00:01Z ERROR task: [event 2] merge aborted\n"
        )
    path.write_text(log)
    attempt = transitions.queue_attempt(conn, task_run, SYSTEM_ACTOR, log_path=str(path))
    now = datetime.now(UTC)
    transitions.claim_attempt(
        conn, attempt, SYSTEM_ACTOR, owner="browser", lease_expires_at=now + timedelta(seconds=120)
    )
    transitions.start_attempt(conn, attempt, SYSTEM_ACTOR, owner="browser")
    started = now - timedelta(seconds=duration)
    conn.execute(
        text(
            "UPDATE AUD_TASK_ATTEMPTS SET STARTED_AT=:started, QUEUED_AT=:queued "
            "WHERE ATTEMPT_ID=:attempt"
        ),
        {"started": started, "queued": started - timedelta(seconds=2), "attempt": attempt},
    )
    if status == "RUNNING":
        return attempt
    if status == "FAILED":
        first = ErrorEvent(1, "Merge", "IntegrityError", "SQL_GUARD", FailureClass.PERMANENT)
        last = ErrorEvent(2, "Merge", "SqlGuardError", "SQL_GUARD", FailureClass.PERMANENT)
        failure = Failure(FailureClass.PERMANENT, "IntegrityError", "23505")
        transitions.record_attempt_failure(
            conn, attempt, failure, anchors=ErrorAnchors(first, last)
        )
    counts = (
        Counts()
        if code == "PYTHON_JOB"
        else Counts(
            source_count=1200,
            rows_written=0 if status == "FAILED" else 1190,
            reject_count=10 if code == "LOAD" else 0,
        )
    )
    transitions.finish_attempt(conn, attempt, status, SYSTEM_ACTOR, owner="browser", counts=counts)
    return attempt


@pytest.mark.parametrize("site", ["statistics"], indirect=True)
@pytest.mark.parametrize(
    "scheme,width", [("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)]
)
def test_task_triage_and_run_statistics(triage, scheme, width):
    url, run = triage
    route = f"/ui/projects/default/runs/TRIAGE/{run}"
    with sync_playwright() as pw:
        browser, page, _ = open_page(
            pw,
            color_scheme=scheme,
            viewport={"width": width, "height": 950},
            has_touch=width == 390,
        )
        requests = []
        page.on(
            "request",
            lambda request: requests.append(request.url) if "/api/v1/" in request.url else None,
        )
        sign_in(page, url, route + "?view=statistics")
        table = page.get_by_role("table", name="Run statistics")
        expect(table.get_by_role("button", name="LOAD", exact=True)).to_be_visible()
        if width == 390:
            expect(table.locator("thead")).to_be_hidden()
            assert (
                table.locator("tbody tr").first.evaluate("(row) => getComputedStyle(row).display")
                != "table-row"
            )
        else:
            expect(table.get_by_role("columnheader", name="Duration")).to_be_visible()
        expect(table.get_by_role("button", name="Reject breakdown for LOAD")).to_be_visible()
        assert sum(path.endswith(f"/runs/{run}/statistics") for path in requests) == 1
        assert not any("/status?" in path or "/steps?" in path for path in requests)
        table.get_by_role("button", name="Earlier tries", exact=True).click()
        expect(table.get_by_role("button", name="Try 1", exact=True)).to_be_visible()
        shoot(page, f"statistics-{scheme}-{width}")
        if width == 390:
            table.get_by_role("button", name="Try 1", exact=True).evaluate(
                "(button) => button.closest('tr').scrollIntoView({block: 'center'})"
            )
            shoot(page, f"statistics-earlier-tries-{scheme}-{width}")
        table.get_by_role("button", name="Reject breakdown for LOAD").click()
        reject = page.get_by_role("dialog", name="Reject breakdown · LOAD")
        expect(reject.get_by_text("invalid integer · 8")).to_be_visible()
        expect(reject.get_by_text("overflow · 2")).to_be_visible()
        shoot(page, f"statistics-rejects-{scheme}-{width}")
        reject.get_by_role("button", name="Close").click()
        for task in ("LOAD", "PYTHON_JOB", "LIVE", "COMPACT", "RETRY", "EXPIRED"):
            page.goto(url + route + f"?view=list&task={task}")
            panel = page.get_by_role("region", name=f"Task {task}", exact=True)
            expect(panel.get_by_role("tab", name="Logs")).to_have_attribute("aria-selected", "true")
            expect(panel.get_by_role("link", name="Open in catalog")).to_have_attribute(
                "href", f"/ui/projects/default/catalog/tasks/TRIAGE.{task}?tab=mapping"
            )
            expect(panel.get_by_role("region", name="Attempt statistics")).to_be_visible()
            failure = panel.get_by_role("region", name="Failure summary")
            if task in {"LOAD", "EXPIRED"}:
                expect(failure.get_by_text("Native code 23505")).to_be_visible()
                if task == "EXPIRED":
                    expect(failure.get_by_text("log expired", exact=False).first).to_be_visible()
                else:
                    link = failure.get_by_role("button", name="Go to line 3 for last error")
                    expect(link).to_be_visible()
                    expect(panel.locator("pre[aria-label='Attempt log']")).to_be_visible()
            else:
                expect(failure).to_have_count(0)
            if task == "PYTHON_JOB":
                expect(panel.get_by_text("Read", exact=True)).to_have_count(0)
            if task == "COMPACT":
                expect(
                    panel.get_by_role("button", name="Above three times the median")
                ).to_be_visible()
            if task == "RETRY":
                expect(panel.get_by_text("Try 2", exact=True)).to_be_visible()
            expect(page.get_by_role("table", name="Run tasks")).to_be_visible()
            expect(panel.locator("pre[aria-label='Attempt log']")).to_be_visible()
            if width == 390:
                panel.evaluate("(node) => node.scrollIntoView({block: 'start'})")
            shoot(page, f"task-{task.lower()}-{scheme}-{width}")
            if task == "LOAD":
                link.click()
                expect(panel.locator("pre[aria-label='Attempt log']")).to_be_focused()
                expect(
                    panel.locator("pre").get_by_text("merge aborted", exact=False)
                ).to_be_visible()
        page.goto(url + f"/ui/projects/default/pipelines/TRIAGE?run={run}&task=LOAD")
        pipeline_task = page.get_by_role("region", name="Task LOAD", exact=True)
        expect(pipeline_task.get_by_role("region", name="Failure summary")).to_be_visible()
        expect(pipeline_task.get_by_role("tab", name="Logs")).to_have_attribute(
            "aria-selected", "true"
        )
        browser.close()
