"""The run page's timeline shows recorded waits apart from execution, by mouse and keyboard."""

from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_platform import shoot
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, acting_as
from etl_craft.core.enums import ActorKind
from fixtures.metadata import add_dependency, add_pipeline, add_task, finish_run, insert, start_run
from fixtures.metadata import task_run as bind_task

pytestmark = pytest.mark.browser

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def waited(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "TIMED")
        extract = add_task(conn, pipeline, "EXTRACT")
        load = add_task(conn, pipeline, "LOAD")
        dependency = add_dependency(conn, pipeline, load, extract)
        run = start_run(conn, pipeline)
        for task, (queued, started, ended) in (
            (extract, (0, 4, 40)),
            (load, (95, 100, 160)),
        ):
            bound = bind_task(conn, task, run)
            insert(
                conn,
                "INSERT INTO AUD_TASK_ATTEMPTS (TASK_RUN_ID,ATTEMPT_NUMBER,STATUS,QUEUED_AT,"
                "STARTED_AT,ENDED_AT) VALUES (:task,1,'SUCCESS',:q,:s,:e)",
                "ATTEMPT_ID",
                task=bound,
                q=at(queued),
                s=at(started),
                e=at(ended),
            )
        conn.execute(
            text(
                "INSERT INTO AUD_GATE_WAITS (PIPELINE_RUN_ID,TASK_ID,FIRST_CHECK_AT,LOOKS,"
                "WAIT_UNTIL,WAIT_KIND) VALUES (:run,:task,:first,2,:until,'DEPENDENCY')"
            ),
            {"run": run, "task": load, "first": at(1), "until": at(600)},
        )
        conn.execute(
            text(
                "INSERT INTO AUD_GATE_DECISIONS (PIPELINE_RUN_ID,TASK_DEPENDENCY_ID,RESULT,"
                "REASON,DECIDED_AT) VALUES (:run,:dep,'SATISFIED','recorded',:decided)"
            ),
            {"run": run, "dep": dependency, "decided": at(90)},
        )
        finish_run(conn, run)
    return url, run


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_timeline_bars_name_their_wait_and_outcome_by_keyboard(waited, scheme, width):
    url, run = waited
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 1000}
        )
        sign_in(page, url, f"/ui/projects/default/pipelines/TIMED?run={run}")
        timeline = page.get_by_role("region", name="Timeline")
        gate = timeline.get_by_role("button", name="LOAD: Dependency gate", exact=False)
        expect(gate).to_have_attribute("aria-label", "LOAD: Dependency gate" + gate_tail(page))
        rows = timeline.get_by_role("list", name="Tasks on the run's time axis")
        expect(rows.get_by_role("listitem")).to_have_count(2)
        gate.scroll_into_view_if_needed()
        gate.focus()
        expect(gate).to_be_focused()
        expect(gate).to_have_attribute("aria-pressed", "true")
        expect(timeline.locator("p[aria-live]")).to_contain_text("Dependency gate")
        expect(timeline.locator("p[aria-live]")).to_contain_text("Satisfied.")
        page.keyboard.press("Tab")
        expect(timeline.locator("p[aria-live]")).not_to_contain_text("Dependency gate")
        execution = timeline.get_by_role("button", name="LOAD, attempt 1: Running", exact=False)
        assert execution.evaluate("e => e.getBoundingClientRect().width > 0")
        shoot(page, f"run-timeline-{scheme}-{width}")
        assert problems == []
        browser.close()


def gate_tail(page):
    """The recorded gate runs from the first check to the decision, in the viewer's zone (UTC)."""
    return (
        " from 01 Mar, 09:00:01 UTC to 01 Mar, 09:01:30 UTC, 1m 29s, "
        "deadline 01 Mar, 09:10:00 UTC. Satisfied."
    )
