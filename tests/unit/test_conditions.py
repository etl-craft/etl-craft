"""Run-condition syntax, fact types and three-valued evaluation."""

import pytest

from etl_craft.core.conditions import COUNTS, Facts, Reading, Scope, evaluate, parse
from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import ConditionError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "scope", "message"),
    [
        ("load.SUCESS", Scope.TASK, "did you mean SUCCESS"),
        ("p.a.b.load.SUCCESS", Scope.TASK, "project.pipeline.task"),
        ("p.a.load.SUCCESS", Scope.PIPELINE, "project.pipeline"),
        ("pipeline.ATTEMPTS = 1", Scope.PIPELINE, "not available for a pipeline"),
        ("load.SUCCESS > 3", Scope.TASK, "use it on its own"),
        ("load.STATUS = 3", Scope.TASK, "expected one of SUCCESS"),
        ("load.STATUS > SUCCESS", Scope.TASK, "use = or <>"),
        ("load.REJECTED = FAILED", Scope.TASK, "expected a whole number"),
        ("load.REJECTED", Scope.TASK, "compare it"),
        ("AT_LEAST(3, a.SUCCESS, b.SUCCESS)", Scope.TASK, "count from 1 to 2"),
        ("AT_LEAST(0, a.SUCCESS, b.SUCCESS)", Scope.TASK, "count from 1 to 2"),
        ("AT_LEAST(1, a.SUCCESS)", Scope.TASK, "expected at least two"),
    ],
)
def test_condition_refusal_names_position_and_expected_input(text, scope, message):
    with pytest.raises(ConditionError, match="position") as caught:
        parse(text, scope)
    assert message in str(caught.value)


def test_evaluation_records_true_false_and_unknown_operands():
    expression = parse("AT_LEAST(2, a.SUCCESS, NOT b.FAILED, c.REJECTED = 0)", Scope.TASK)
    available = {
        "a": Facts(RunStatus.SUCCESS),
        "b": Facts(RunStatus.FAILED),
    }
    reading = Reading()

    def lookup(ref):
        return available.get(ref.parts[0])

    assert evaluate(expression, lookup, reading) is None
    assert reading.values == {"a.SUCCESS": True, "b.FAILED": True, "c.REJECTED": None}
    available["c"] = Facts(RunStatus.SUCCESS, {"REJECTED": 0})
    assert evaluate(expression, lookup) is True
    available["c"] = Facts(RunStatus.SUCCESS, {"REJECTED": 1})
    assert evaluate(expression, lookup) is False


@pytest.mark.parametrize("fact", [*COUNTS, "ATTEMPTS", "DURATION_SECONDS"])
@pytest.mark.parametrize("op", ["=", "<>", "<", "<=", ">", ">="])
def test_numeric_facts_and_operators(fact, op):
    expression = parse(f"load.{fact} {op} 3", Scope.TASK)

    def evaluate_count(count):
        facts = Facts(RunStatus.SUCCESS, {fact: count}, attempts=count, duration_seconds=count)
        return evaluate(expression, lambda _: facts)

    assert evaluate_count(None) is None
    assert {evaluate_count(count) for count in (2, 3, 4)} == {True, False}


@pytest.mark.parametrize(
    ("text", "yes", "no"),
    [
        ("load.SUCCESS", RunStatus.SUCCESS, RunStatus.FAILED),
        ("load.FAILED", RunStatus.FAILED, RunStatus.SUCCESS),
        ("load.SKIPPED", RunStatus.SKIPPED, RunStatus.CANCELLED),
        ("load.FINISHED", RunStatus.CANCELLED, RunStatus.IN_PROGRESS),
        ("load.HAS_DATA", RunStatus.SUCCESS, RunStatus.SKIPPED),
        ("load.STATUS = CANCELLED", RunStatus.CANCELLED, RunStatus.SUCCESS),
        ("load.ERROR_CLASS <> NONE", RunStatus.FAILED, RunStatus.SUCCESS),
    ],
)
def test_status_facts_are_true_false_or_unknown(text, yes, no):
    expression = parse(text, Scope.TASK)
    assert evaluate(expression, lambda _: None) is None
    assert (
        evaluate(expression, lambda _: Facts(yes, {"ROWS_WRITTEN": 3}, error_class="TRANSIENT"))
        is True
    )
    assert evaluate(expression, lambda _: Facts(no, error_class="NONE")) is False
