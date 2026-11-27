"""The cross-pipeline gates and their trackers against a real Engine DB, both dialects."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft.core.actor import current_actor
from etl_craft.engine import transitions
from etl_craft.engine.repository import trackers
from etl_craft.execution.gates import (
    Clock,
    TrackedGate,
    check_pipeline_dependencies,
)
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_pipeline_dependency,
    add_task,
    finish_run,
    start_run,
    task_run,
    upstream_run,
)

NO_WAIT = Clock(sleep=lambda seconds: None)

pytestmark = pytest.mark.usefixtures("selected_default_project")


@pytest.fixture
def world(engine_db):
    """Pipeline UP with task publish; pipeline DOWN with task load depending on UP.publish."""
    engine = engine_db.engine
    ids = {}
    with engine.begin() as conn:
        ids["up"] = add_pipeline(conn, "UP")
        ids["down"] = add_pipeline(conn, "DOWN")
        ids["publish"] = add_task(conn, ids["up"], "publish")
        ids["load"] = add_task(conn, ids["down"], "load")
    return engine, ids


def depend(engine, ids, kind):
    with engine.begin() as conn:
        return add_dependency(
            conn, ids["down"], ids["load"], ids["publish"], kind, upstream_pipeline=ids["up"]
        )


def consumed_task_runs(engine, edge_id):
    """The log's rows for a task dependency, oldest first: (downstream run, upstream task run)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS run_id, CONSUMED_TASK_RUN_ID AS consumed "
                "FROM AUD_DEPENDENCY_CONSUMPTION WHERE TASK_DEPENDENCY_ID = :id "
                "ORDER BY CONSUMPTION_ID"
            ),
            {"id": edge_id},
        )
        return [(row.run_id, row.consumed) for row in rows]


def test_a_task_dependency_is_judged_on_the_upstreams_last_run_and_consumed_once(world):
    engine, ids = world
    edge = depend(engine, ids, "SUCCESS")
    gate = TrackedGate(NO_WAIT)

    never = gate.check(engine, ids["load"])
    assert never.facts == {edge: None} and never.definitive
    assert never.reasons == ("upstream task UP.publish has no finished run",)

    with engine.begin() as conn:
        _, rows = upstream_run(conn, ids["up"], {ids["publish"]: ("SUCCESS",)})
    first = gate.check(engine, ids["load"])
    assert first.facts[edge].value("SUCCESS") is True
    assert first.consumed == {edge: rows[ids["publish"]]}

    with engine.begin() as conn:
        down_run = start_run(conn, ids["down"])
        summary = transitions.find_or_create_task_run(conn, ids["load"], down_run).task_run_id
        attempt = transitions.queue_attempt(conn, summary, current_actor())
        transitions.claim_attempt(
            conn,
            attempt,
            current_actor(),
            owner="gate-test",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        trackers.record_decisions(conn, down_run, first.decisions, attempt_id=attempt)
        transitions.finish_attempt(conn, attempt, "SUCCESS", current_actor(), owner="gate-test")
    assert consumed_task_runs(engine, edge) == [(down_run, rows[ids["publish"]])]
    again = gate.check(engine, ids["load"])
    assert again.facts == {edge: None}
    assert "which was already consumed" in again.reasons[0]


def test_an_older_satisfying_run_does_not_count_once_a_newer_one_fails(world):
    engine, ids = world
    edge = depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        upstream_run(conn, ids["up"], {ids["publish"]: ("SUCCESS",)})
        _, rows = upstream_run(conn, ids["up"], {ids["publish"]: ("FAILED",)}, status="FAILED")
    check = TrackedGate(NO_WAIT).check(engine, ids["load"])
    assert check.consumed == {edge: rows[ids["publish"]]}
    assert check.facts[edge].value("SUCCESS") is False
    assert check.facts[edge].value("FAILED") is True


def test_has_data_needs_rows_written(world):
    engine, ids = world
    edge = depend(engine, ids, "HAS_DATA")
    for values, expected in (
        (("SUCCESS", 0), False),
        (("SUCCESS", 4), True),
        (("SUCCESS", 4, 0), False),
    ):
        with engine.begin() as conn:
            upstream_run(conn, ids["up"], {ids["publish"]: values})
        check = TrackedGate(NO_WAIT).check(engine, ids["load"])
        assert check.facts[edge].value("HAS_DATA") is expected


def test_a_running_upstream_is_waited_for(world):
    engine, ids = world
    depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        run_id = start_run(conn, ids["up"])
        row = task_run(conn, ids["publish"], run_id, "IN-PROGRESS")
    waits = []

    def upstream_finishes(seconds):
        waits.append(seconds)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE AUD_TASK_RUN_LOG SET STATUS = 'SUCCESS', END_DATE = START_DATE "
                    "WHERE TASK_RUN_ID = :id"
                ),
                {"id": row},
            )

    check = TrackedGate(Clock(sleep=upstream_finishes)).check(engine, ids["load"])
    assert len(waits) == 1
    assert list(check.consumed.values()) == [row]
    assert all(fact.value("SUCCESS") is True for fact in check.facts.values())


def test_a_gate_told_not_to_wait_judges_a_running_upstream_at_once(world):
    engine, ids = world
    depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        run_id = start_run(conn, ids["up"])
        task_run(conn, ids["publish"], run_id, "IN-PROGRESS")
    waits = []
    gate = TrackedGate(Clock(sleep=waits.append), wait_seconds=0)
    check = gate.check(engine, ids["load"])
    assert waits == []
    assert list(check.facts.values()) == [None]
    assert check.reasons == ("upstream task UP.publish has no finished run",)


def test_no_cross_pipeline_names_need_no_binding(world):
    engine, ids = world
    assert TrackedGate(NO_WAIT).check(engine, ids["load"]).facts == {}


def test_a_pipeline_gate_and_what_its_successful_run_consumes(world):
    engine, ids = world
    with engine.begin() as conn:
        edge = add_pipeline_dependency(conn, ids["down"], ids["up"], "SUCCESS")

    refused = check_pipeline_dependencies(engine, ids["down"], NO_WAIT)
    assert not refused.satisfied
    assert refused.reasons == ("upstream pipeline UP (SUCCESS) has no finished run",)

    with engine.begin() as conn:
        first, _ = upstream_run(conn, ids["up"], {})
    passed = check_pipeline_dependencies(engine, ids["down"], NO_WAIT)
    assert passed.satisfied and passed.consumed == {edge: first}

    # UP finishes another run while DOWN runs: DOWN consumed the one it started with.
    now = datetime.now(UTC)
    with engine.begin() as conn:
        down_run = start_run(conn, ids["down"])
        trackers.record_decisions(conn, down_run, passed.decisions)
        second = start_run(conn, ids["up"])
        for run_id, started, ended in (
            (first, now - timedelta(seconds=90), now - timedelta(seconds=80)),
            (down_run, now - timedelta(seconds=60), None),
            (second, now - timedelta(seconds=50), now - timedelta(seconds=30)),
        ):
            conn.execute(
                text(
                    "UPDATE AUD_PIPELINES_RUN_LOG SET START_DATE = :started, END_DATE = :ended, "
                    "STATUS = CASE WHEN :done = 1 THEN 'SUCCESS' ELSE STATUS END "
                    "WHERE PIPELINE_RUN_ID = :id"
                ),
                {"started": started, "ended": ended, "done": int(ended is not None), "id": run_id},
            )
        transitions.finalize_pipeline_run(conn, down_run, "SUCCESS", consume=True)
    with engine.connect() as conn:
        consumed = conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS run_id, CONSUMED_PIPELINE_RUN_ID AS consumed "
                "FROM AUD_DEPENDENCY_CONSUMPTION WHERE PIPELINE_DEPENDENCY_ID = :id"
            ),
            {"id": edge},
        ).one()
    assert (consumed.run_id, consumed.consumed) == (down_run, first)
    # The newer run is left for DOWN's next run.
    assert check_pipeline_dependencies(engine, ids["down"], NO_WAIT).consumed == {edge: second}


def backfill_run(conn, pipeline_id, task_statuses, status="SUCCESS"):
    """A run of ``pipeline_id`` that is part of a backfill, its tasks and itself ended as given."""
    run_id = start_run(conn, pipeline_id, backfill=True)
    for task_id, task_status in task_statuses.items():
        task_run(conn, task_id, run_id, task_status, target_count=1)
    if status != "IN-PROGRESS":
        finish_run(conn, run_id, status)
    return run_id


def never_sleep(seconds):
    raise AssertionError(f"the gate waited {seconds}s for a backfill run")


def test_a_finished_backfill_run_never_satisfies_a_gate(world):
    engine, ids = world
    edge = depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        add_pipeline_dependency(conn, ids["down"], ids["up"], "SUCCESS")
        backfill_run(conn, ids["up"], {ids["publish"]: "SUCCESS"})
    assert not check_pipeline_dependencies(engine, ids["down"], NO_WAIT).satisfied
    task_gate = TrackedGate(NO_WAIT).check(engine, ids["load"])
    assert task_gate.facts[edge] is None and edge not in task_gate.consumed


def test_a_failed_backfill_run_never_blocks_a_gate(world):
    engine, ids = world
    edge = depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        pipeline_edge = add_pipeline_dependency(conn, ids["down"], ids["up"], "SUCCESS")
        scheduled, rows = upstream_run(conn, ids["up"], {ids["publish"]: ("SUCCESS",)})
        backfill_run(conn, ids["up"], {ids["publish"]: "FAILED"}, status="FAILED")
    passed = check_pipeline_dependencies(engine, ids["down"], NO_WAIT)
    assert passed.satisfied and passed.consumed == {pipeline_edge: scheduled}
    task_gate = TrackedGate(NO_WAIT).check(engine, ids["load"])
    assert task_gate.consumed == {edge: rows[ids["publish"]]}


def test_a_running_backfill_run_is_never_waited_for(world):
    engine, ids = world
    depend(engine, ids, "SUCCESS")
    with engine.begin() as conn:
        add_pipeline_dependency(conn, ids["down"], ids["up"], "SUCCESS")
        upstream_run(conn, ids["up"], {ids["publish"]: ("SUCCESS",)})
        backfill_run(conn, ids["up"], {ids["publish"]: "IN-PROGRESS"}, status="IN-PROGRESS")
    clock = Clock(sleep=never_sleep)
    assert check_pipeline_dependencies(engine, ids["down"], clock).satisfied
    check = TrackedGate(clock).check(engine, ids["load"])
    assert len(check.consumed) == 1
    assert all(fact.value("SUCCESS") is True for fact in check.facts.values())
