"""Judging an upstream's last run, and pacing the wait for a running one."""

from datetime import UTC, datetime, timedelta

import pytest

from etl_craft.core.conditions import Facts, Scope, evaluate, parse
from etl_craft.engine.repository.trackers import ConsumedRun, FinishedRun, LatestRun
from etl_craft.execution import gates
from etl_craft.execution.gates import Clock, WaitBudget, fresh, next_look_delay

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("kind", "status", "has_data", "expected"),
    [
        ("SUCCESS", "SUCCESS", False, True),
        ("SUCCESS", "FAILED", False, False),
        ("FAILURE", "FAILED", False, True),
        ("FAILURE", "SUCCESS", False, False),
        ("ALWAYS", "SKIPPED", False, True),
        ("HAS_DATA", "SUCCESS", True, True),
        ("HAS_DATA", "SUCCESS", False, False),
        ("HAS_DATA", "FAILED", True, False),
    ],
)
def test_start_condition_flag(kind, status, has_data, expected):
    fact = {"SUCCESS": "SUCCESS", "FAILURE": "FAILED", "ALWAYS": "FINISHED", "HAS_DATA": "HAS_DATA"}
    condition = parse(f"upstream.{fact[kind]}", Scope.PIPELINE)
    facts = Facts(status, {"ROWS_WRITTEN": int(has_data)}, scope=Scope.PIPELINE)
    assert evaluate(condition, lambda _, facts=facts: facts) is expected


def test_the_last_finished_run_decides():
    assert fresh(None, None) == (None, "has no finished run")
    assert fresh(FinishedRun(5, "SUCCESS", False), None) == (
        5,
        "last finished run 5 ended SUCCESS",
    )
    assert fresh(FinishedRun(5, "SUCCESS", False), 5) == (
        None,
        "has no run since run 5, which was already consumed",
    )
    assert fresh(FinishedRun(6, "FAILED", False), 5) == (6, "last finished run 6 ended FAILED")


def test_look_delays():
    # Due at 70% of a 100 s average: 30 s in, the look is 40 s away.
    assert next_look_delay(100, 30, 0.7, 3600) == 40
    # Already overdue: the shortest pause, not a busy loop.
    assert next_look_delay(100, 500, 0.7, 3600) == gates.MIN_LOOK_INTERVAL_SECONDS
    # Never past the deadline.
    assert next_look_delay(100, 0, 0.7, 5) == 5
    assert next_look_delay(100, 0, 0.7, -1) == 0


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 9, 25, 10, tzinfo=UTC)
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)

    def clock(self):
        return Clock(sleep=self.sleep, now=lambda: self.now)


def test_waiting_for_a_running_upstream_follows_its_average_length():
    fake = FakeClock()
    clock = fake.clock()
    started = fake.now
    looks = iter(["IN-PROGRESS", "IN-PROGRESS", "SUCCESS"])

    def latest():
        return LatestRun(9, next(looks), started)

    budget = WaitBudget.start(clock)
    gates._wait_while_running(latest, lambda: 100.0, "upstream", budget, clock)
    assert fake.slept == pytest.approx([70, 10])
    assert budget.looks_left == gates.MAX_LOOKS - 2


def test_waiting_stops_when_the_budget_runs_out():
    fake = FakeClock()
    clock = fake.clock()
    started = fake.now.replace(tzinfo=None)  # a naive start is read as UTC

    budget = WaitBudget(deadline=fake.now + timedelta(seconds=90), looks_left=gates.MAX_LOOKS)
    gates._wait_while_running(
        lambda: LatestRun(9, "IN-PROGRESS", started), lambda: None, "upstream", budget, clock
    )
    # The default length is assumed; the first look at 70% of it is cut to the deadline.
    assert fake.slept == [90]
    assert budget.exhausted(clock)


def test_an_upstream_that_is_not_running_is_not_waited_for():
    fake = FakeClock()
    clock = fake.clock()
    budget = WaitBudget.start(clock)
    gates._wait_while_running(lambda: None, lambda: 1.0, "upstream", budget, clock)
    gates._wait_while_running(
        lambda: LatestRun(1, "FAILED", fake.now), lambda: 1.0, "upstream", budget, clock
    )
    assert fake.slept == [] and budget.looks_left == gates.MAX_LOOKS


@pytest.mark.parametrize(
    ("run_id", "revision", "repairs", "accepted"),
    [
        (5, 2, True, True),
        (5, 2, False, False),
        (5, 1, True, False),
        (4, 99, True, False),
        (6, 1, False, True),
    ],
)
def test_freshness_compares_identity_and_revision(run_id, revision, repairs, accepted):
    selected, reason = fresh(
        FinishedRun(run_id, "SUCCESS", True, revision),
        ConsumedRun(5, 1),
        consume_repairs=repairs,
    )
    assert selected == (run_id if accepted else None)
    if run_id == 5 and revision == 2 and not repairs:
        assert "CONSUME_REPAIRS='N'" in reason


@pytest.mark.parametrize(
    ("expression", "first", "second"),
    [
        ("u.SUCCESS", "SUCCESS", "FAILED"),
        ("u.FAILED", "FAILED", "SUCCESS"),
        ("u.SKIPPED", "SKIPPED", "SUCCESS"),
        ("u.FINISHED", "SUCCESS", "IN-PROGRESS"),
        ("u.HAS_DATA", "SUCCESS", "FAILED"),
        ("u.STATUS = SUCCESS", "SUCCESS", "FAILED"),
    ],
)
def test_pipeline_status_facts_have_three_valued_evaluations(expression, first, second):
    condition = parse(expression, Scope.PIPELINE)
    for status, expected in ((first, True), (second, False), (None, None)):
        facts = Facts(status, {"ROWS_WRITTEN": 1}, scope=Scope.PIPELINE) if status else None
        assert evaluate(condition, lambda _, facts=facts: facts) is expected


@pytest.mark.parametrize(
    "fact",
    [
        "SOURCE_ROWS",
        "TARGET_ROWS",
        "ROWS_WRITTEN",
        "INSERTED",
        "UPDATED",
        "DELETED",
        "REJECTED",
        "DUPLICATES",
        "DURATION_SECONDS",
    ],
)
def test_pipeline_numeric_facts_have_three_valued_evaluations(fact):
    condition = parse(f"u.{fact} = 2", Scope.PIPELINE)
    for count, expected in ((2, True), (1, False), (None, None)):
        facts = Facts("SUCCESS", {fact: count}, duration_seconds=count, scope=Scope.PIPELINE)
        assert evaluate(condition, lambda _, facts=facts: facts) is expected
