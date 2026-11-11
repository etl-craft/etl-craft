"""Project context and production confirmation stay in the CLI presentation layer."""

import io
import json

import pytest

from etl_craft.cli.output import Output
from etl_craft.core.errors import UsageError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)


def output(kind="PROD", name=None, *, json_mode=False):
    from etl_craft.core.environment import Environment

    out = Output(stdout=io.StringIO(), stderr=io.StringIO())
    out.context("support_insights", Environment(kind, name), "https://etl.example", json=json_mode)
    return out


def test_context_is_one_line_on_stderr_and_json_is_augmented():
    out = output()
    out.line("result")
    assert out.stderr.getvalue() == "support_insights · PRODUCTION · https://etl.example\n"
    assert out.stdout.getvalue() == "result\n"
    other = output("UAT", "owner testing", json_mode=True)
    from etl_craft.services.operations.sessions import Identity

    other.document(Identity("tester", "viewer"))
    assert other.stderr.getvalue() == ""
    assert json.loads(other.stdout.getvalue())["environment"] == {
        "type": "UAT",
        "name": "owner testing",
    }


@pytest.mark.parametrize("answer", ["support_insights", "wrong", "support_insights "])
def test_production_confirmation_checks_exact_project(monkeypatch, answer):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    out = output()
    if answer != "support_insights":
        with pytest.raises(
            UsageError, match=r"confirmation did not match.*project action was not executed"
        ):
            out.confirm("run", yes=False)
    else:
        out.confirm("run", yes=False)
        assert out.confirmed
    assert "PRODUCTION action: run" in out.stderr.getvalue()


def test_noninteractive_refuses_without_yes_and_never_prompts(monkeypatch):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: False)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("noninteractive prompt"))
    out = output()
    with pytest.raises(UsageError, match=r"support_insights.*PRODUCTION.*--yes"):
        out.confirm("run", yes=False)
    out.confirm("run", yes=True)
    assert out.confirmed


def test_nonproduction_never_prompts(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("nonproduction prompt"))
    out = output("DEV", "workstation")
    out.confirm("run", yes=False)
    assert "DEV · workstation" in out.stderr.getvalue()


def test_context_is_one_safe_line_for_multiline_environment_names():
    out = output("UAT", "owner\nreview\x1b")
    assert out.stderr.getvalue() == "support_insights · UAT · owner review · https://etl.example\n"


def test_ci_never_prompts_even_with_a_terminal(monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("CI prompt"))
    with pytest.raises(UsageError, match="--yes"):
        output().confirm("run", yes=False)


def test_context_refreshes_when_a_migration_changes_the_environment():
    from etl_craft.core.environment import Environment

    out = output("DEV")
    out.context("support_insights", Environment("PROD"), None, json=False)
    assert out.environment.type == "PROD"
    assert "PRODUCTION · local" in out.stderr.getvalue()
