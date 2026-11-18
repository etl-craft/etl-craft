"""The checks ``validate`` shares with the handlers, on their own."""

import pytest

from etl_craft.core.alerts import AlertKind
from etl_craft.core.graph import cycles
from etl_craft.engine.repository.pipelines import pipeline_parameter_problems
from etl_craft.handlers.alert_message import compose, parameter_problems
from etl_craft.handlers.python_scripts import script_definition_problem

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        ("def run(task):\n    pass\n", None),
        ("def run():\n    pass\n", None),
        ("def run(task, extra=1, *args):\n    pass\n", None),
        ("from helpers import run\n", None),
        ("run = lambda task: None\n", None),
        ("async def run(task):\n    pass\n", "s.py: run is async"),
        (
            "def main(task):\n    pass\n",
            "SCRIPT_FILE='s.py' defines no run(task) function",
        ),
    ],
)
def test_a_script_is_read_without_running_it(tmp_path, source, problem):
    path = tmp_path / "s.py"
    path.write_text("import sys\nsys.exit(3)\n" + source, "utf-8")
    found = script_definition_problem(path, "s.py")
    assert found == problem if problem is None else found.startswith(problem)


def test_alert_settings_are_checked_against_the_channel_kind():
    assert (
        parameter_problems({"ALERT_SUBJECT": "$$pipeline_code: $$trigger"}, AlertKind.SLACK) == []
    )
    assert parameter_problems({"EMAIL_PIPELINES": "ALL"}, AlertKind.EMAIL) == []
    assert parameter_problems(
        {"ALERT_BODY": "$$x", "EMAIL_TEMPLATE": "email_templates/a.html"}, AlertKind.WEBHOOK
    ) == [
        "ALERT_BODY uses unknown token(s) $$x; the tokens are $$trigger, $$status, $$pipeline_id, "
        "$$pipeline_run_id, $$task_run_id, $$pipeline_code, $$task_code, $$error_message",
        "EMAIL_TEMPLATE applies to EMAIL channels only; this task's channel is WEBHOOK; remove "
        "EMAIL_TEMPLATE or select an EMAIL channel",
    ]


def test_an_alert_message_fills_its_tokens_or_the_built_in_wording():
    values = {
        "trigger": "FAILURE",
        "status": "FAILED",
        "pipeline_id": "3",
        "pipeline_run_id": "41",
        "task_run_id": "90",
        "pipeline_code": "SALES",
        "task_code": "notify",
        "error_message": "load: boom",
    }
    built_in = compose({}, values)
    assert built_in.subject == "SALES: FAILURE · run 41"
    assert built_in.body.endswith("\nload: boom")
    own = compose({"ALERT_SUBJECT": "$$pipeline_code\n$$status", "ALERT_BODY": "$$trigger"}, values)
    assert (own.subject, own.body) == ("SALES FAILED", "FAILURE")


def test_pipeline_parameters_are_typed():
    assert pipeline_parameter_problems(None) == ([], [])
    assert pipeline_parameter_problems('{"TAGS": ["a"]}') == ([], [])
    assert pipeline_parameter_problems('{"EMAIL_RECIPIENTS": ["a@x.io"]}') == (
        [],
        ["EMAIL_RECIPIENTS"],
    )
    assert pipeline_parameter_problems({"TAGS": "a", "CATCHUP": False}) == (
        [
            "TAGS='a'; expected a list of strings; write a JSON list of tags "
            "(1 to 64 lowercase ASCII letters, digits, '-', '_' or ':')"
        ],
        ["CATCHUP"],
    )
    assert pipeline_parameter_problems("[1]")[0] == [
        "PIPELINE_PARAMETERS must be a JSON object; it is [1]"
    ]
    assert pipeline_parameter_problems("{")[0][0].startswith(
        "PIPELINE_PARAMETERS is not valid JSON"
    )


def test_each_cycle_is_reported_once_from_its_smallest_code():
    edges = {("B", "C"), ("C", "B"), ("A", "B"), ("X", "Y"), ("Y", "Z"), ("Z", "X")}
    assert cycles(edges) == [["B", "C"], ["X", "Y", "Z"]]
    assert cycles({("A", "B"), ("B", "C")}) == []
