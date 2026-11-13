"""The CLI shows the targets a full refresh would empty and waits for acceptance."""

import argparse
import io
from dataclasses import replace

import pytest

from etl_craft.cli.commands import run
from etl_craft.cli.output import Output
from etl_craft.core.errors import ConfirmationRequiredError, ExitCode, UsageError
from etl_craft.services.operations.requests import RunRequest

pytestmark = pytest.mark.unit

WARNING = "these APPEND_TABLE tasks would write them again:\n  load: mart.orders"


@pytest.fixture(autouse=True)
def outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)


def output():
    return Output(stdout=io.StringIO(), stderr=io.StringIO())


def test_yes_accepts_without_asking_and_the_warning_is_still_shown(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("asked despite --yes"))
    out = output()
    assert out.confirm_emptying(WARNING, yes=True)
    assert "load: mart.orders" in out.stderr.getvalue()


@pytest.mark.parametrize("answer", ["y", "Y", " yes "])
def test_a_terminal_answer_of_yes_continues(monkeypatch, answer):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    out = output()
    assert out.confirm_emptying(WARNING, yes=False)
    assert out.stderr.getvalue().endswith("Continue? [y/N] ")


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_any_other_answer_ends_the_command_before_anything_runs(monkeypatch, answer):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    with pytest.raises(UsageError, match="not confirmed; nothing was run"):
        output().confirm_emptying(WARNING, yes=False)


@pytest.mark.parametrize("terminal, ci", [(False, False), (True, True)])
def test_without_a_terminal_it_never_prompts_and_leaves_the_refusal_to_the_caller(
    monkeypatch, terminal, ci
):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: terminal)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("prompted without a terminal"))
    if ci:
        monkeypatch.setenv("CI", "1")
    assert output().confirm_emptying(WARNING, yes=False) is False


def test_a_closed_input_is_not_an_acceptance(monkeypatch):
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)

    def closed():
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert output().confirm_emptying(WARNING, yes=False) is False


def refresh_request():
    return RunRequest(pipeline_code="P", full_refresh=True, reason="profile history corrected")


def args(*, yes):
    return argparse.Namespace(yes=yes)


def asking(sent):
    """A `call` that refuses until the request names the targets, recording what was sent."""

    def call(_args, _name, request, **_options):
        sent.append(request)
        if request.empty_targets != ("mart.orders",):
            raise ConfirmationRequiredError(WARNING, ("mart.orders",))
        return "ran"

    return call


def test_the_request_is_repeated_once_with_exactly_the_targets_the_server_named(monkeypatch):
    sent = []
    monkeypatch.setattr(run, "call", asking(sent))
    assert run._call_run(args(yes=True), output(), refresh_request()) == "ran"
    assert [r.empty_targets for r in sent] == [(), ("mart.orders",)]
    assert replace(sent[1], empty_targets=()) == sent[0]


def test_an_unconfirmed_request_raises_the_refusal_with_its_own_exit_code(monkeypatch):
    sent = []
    monkeypatch.setattr(run, "call", asking(sent))
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: False)
    with pytest.raises(ConfirmationRequiredError) as refused:
        run._call_run(args(yes=False), output(), refresh_request())
    assert refused.value.exit_code == ExitCode.CONFIRMATION_REQUIRED == 31
    assert len(sent) == 1  # nothing was repeated, so nothing could have been emptied


def test_a_request_that_needs_no_confirmation_is_sent_once(monkeypatch):
    sent = []
    monkeypatch.setattr(run, "call", lambda _a, _n, request, **_o: sent.append(request) or "ran")
    assert run._call_run(args(yes=False), output(), refresh_request()) == "ran"
    assert len(sent) == 1
