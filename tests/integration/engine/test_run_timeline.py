"""The run read's timeline comes only from recorded attempts, gate waits and decisions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import ResourceNotFoundError
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import RunId
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_pipeline_dependency,
    add_task,
    finish_run,
    insert,
    start_run,
    task_run,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def attempt(conn, task_run_id, number, status, queued, started=None, ended=None):
    insert(
        conn,
        "INSERT INTO AUD_TASK_ATTEMPTS (TASK_RUN_ID,ATTEMPT_NUMBER,STATUS,QUEUED_AT,STARTED_AT,"
        "ENDED_AT) VALUES (:task,:number,:status,:queued,:started,:ended)",
        "ATTEMPT_ID",
        task=task_run_id,
        number=number,
        status=status,
        queued=queued,
        started=started,
        ended=ended,
    )


def wait(conn, run, task, kind, first, *, open_until=None, deadline=None):
    conn.execute(
        text(
            "INSERT INTO AUD_GATE_WAITS (PIPELINE_RUN_ID,TASK_ID,FIRST_CHECK_AT,NEXT_CHECK_AT,"
            "LOOKS,WAIT_UNTIL,WAIT_KIND) VALUES (:run,:task,:first,:next,1,:deadline,:kind)"
        ),
        {
            "run": run,
            "task": task,
            "first": first,
            "next": open_until,
            "deadline": deadline,
            "kind": kind,
        },
    )


def decide(conn, run, result, decided, *, task_dependency=None, pipeline_dependency=None):
    conn.execute(
        text(
            "INSERT INTO AUD_GATE_DECISIONS (PIPELINE_RUN_ID,TASK_DEPENDENCY_ID,"
            "PIPELINE_DEPENDENCY_ID,RESULT,REASON,DECIDED_AT) "
            "VALUES (:run,:task,:pipeline,:result,'recorded',:decided)"
        ),
        {
            "run": run,
            "task": task_dependency,
            "pipeline": pipeline_dependency,
            "result": result,
            "decided": decided,
        },
    )


@pytest.fixture
def recorded(engine_db):
    with acting_as(SYSTEM_ACTOR), engine_db.engine.begin() as conn:
        upstream = add_pipeline(conn, "UP")
        pipeline = add_pipeline(conn, "P")
        load, timed, bypassed, refused, event = (
            add_task(conn, pipeline, code)
            for code in ("LOAD", "TIMED", "BYPASS", "REFUSE", "EVENT")
        )
        on_up = add_pipeline_dependency(conn, pipeline, upstream)
        deps = {
            task: add_dependency(conn, pipeline, task, load) for task in (timed, bypassed, refused)
        }
        run = start_run(conn, pipeline)
        loaded = task_run(conn, load, run, "IN-PROGRESS")
        attempt(conn, loaded, 1, "FAILED", at(0), at(5), at(60))
        attempt(conn, loaded, 2, "QUEUED", at(70))
        wait(conn, run, None, "DEPENDENCY", at(-30), deadline=at(300))
        decide(conn, run, "SATISFIED", at(-1), pipeline_dependency=on_up)
        wait(conn, run, timed, "DEPENDENCY", at(1), deadline=at(600))
        decide(conn, run, "UNSATISFIED", at(600), task_dependency=deps[timed])
        wait(conn, run, bypassed, "DEPENDENCY", at(2), deadline=at(600))
        decide(conn, run, "BYPASSED", at(65), task_dependency=deps[bypassed])
        wait(conn, run, refused, "DEPENDENCY", at(3), deadline=at(600))
        decide(conn, run, "UNSATISFIED", at(61), task_dependency=deps[refused])
        # An event wait overlapping the load attempt is still open.
        wait(conn, run, event, "EVENT", at(10), open_until=at(900))
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    return ctx, run, pipeline


def test_segments_match_the_recorded_rows(recorded):
    ctx, run, _ = recorded
    timeline = invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run)).timeline
    got = {
        (s.task_code, s.kind, s.attempt_number): (s.started_at, s.ended_at, s.outcome)
        for s in timeline
    }
    assert got == {
        (None, "GATE", None): (at(-30), at(-1), "SATISFIED"),
        ("LOAD", "QUEUE", 1): (at(0), at(5), "FAILED"),
        ("LOAD", "EXECUTION", 1): (at(5), at(60), "FAILED"),
        ("LOAD", "QUEUE", 2): (at(70), None, "QUEUED"),
        ("TIMED", "GATE", None): (at(1), at(600), "TIMED_OUT"),
        ("BYPASS", "GATE", None): (at(2), at(65), "BYPASSED"),
        ("REFUSE", "GATE", None): (at(3), at(61), "REFUSED"),
        ("EVENT", "EVENT", None): (at(10), None, "OPEN"),
    }
    assert [s.started_at for s in timeline] == sorted(s.started_at for s in timeline)
    deadline = next(s for s in timeline if s.task_code == "TIMED").deadline
    assert deadline == at(600)


def test_a_wait_stopped_with_its_run_ends_and_a_run_with_no_rows_has_none(recorded, engine_db):
    ctx, run, pipeline = recorded
    with acting_as(SYSTEM_ACTOR), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE AUD_GATE_WAITS SET NEXT_CHECK_AT=NULL WHERE WAIT_KIND='EVENT'"))
        finish_run(conn, run, "CANCELLED")
        quiet = start_run(conn, pipeline)
    timeline = invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run)).timeline
    event = next(s for s in timeline if s.kind == "EVENT")
    assert (event.ended_at, event.outcome) == (None, "ENDED")
    assert invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=quiet)).timeline == ()


def test_event_and_child_waits_end_with_their_task(recorded, engine_db):
    ctx, run, pipeline = recorded
    with acting_as(SYSTEM_ACTOR), engine_db.engine.begin() as conn:
        event = conn.execute(
            text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE='EVENT'")
        ).scalar_one()
        conn.execute(text("UPDATE AUD_GATE_WAITS SET NEXT_CHECK_AT=NULL WHERE WAIT_KIND='EVENT'"))
        task_run(conn, event, run, "SKIPPED")
        child = add_task(conn, pipeline, "CHILD")
        wait(conn, run, child, "PIPELINE_RUN", at(20))
        task_run(conn, child, run, "SUCCESS")
    timeline = invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run)).timeline
    outcomes = {s.task_code: s.outcome for s in timeline if s.kind in {"EVENT", "CHILD_RUN"}}
    assert outcomes == {"EVENT": "TIMED_OUT", "CHILD": "SATISFIED"}
    assert all(s.ended_at is not None for s in timeline if s.kind in {"EVENT", "CHILD_RUN"})


def test_lists_and_status_reads_carry_no_timeline_and_hidden_runs_stay_hidden(recorded):
    from etl_craft.services.operations.requests import HistoryInput

    ctx, run, _ = recorded
    history = invoke(ctx, ActionName.HISTORY, HistoryInput(pipeline_code="P", all=True))
    assert all(entry.timeline == () for entry in history.entries)
    with pytest.raises(ResourceNotFoundError):
        invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run + 1000))
