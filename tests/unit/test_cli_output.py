import io

import pytest

from etl_craft.cli.output import Output

pytestmark = pytest.mark.unit


def test_results_go_to_stdout_and_errors_to_stderr(capsys):
    out = Output()
    out.line("result")
    out.line()
    out.error("something broke")
    captured = capsys.readouterr()
    assert captured.out == "result\n\n"
    assert captured.err == "error: something broke\n"


def test_rows_are_tab_separated_with_none_as_an_empty_field():
    stdout = io.StringIO()
    Output(stdout=stdout).rows([("P1", "Daily load", "FULL"), ("P2", None, 3)])
    assert stdout.getvalue() == "P1\tDaily load\tFULL\nP2\t\t3\n"


def test_an_empty_result_is_one_parenthesised_line():
    stdout = io.StringIO()
    Output(stdout=stdout).empty("no active pipelines")
    assert stdout.getvalue() == "(no active pipelines)\n"


def test_given_streams_are_used_instead_of_the_process_streams(capsys):
    stdout, stderr = io.StringIO(), io.StringIO()
    out = Output(stdout, stderr)
    out.line("a")
    out.error("b")
    assert (stdout.getvalue(), stderr.getvalue()) == ("a\n", "error: b\n")
    assert capsys.readouterr() == ("", "")


def test_terminal_rows_align_while_pipes_keep_their_contract():
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    terminal = Terminal()
    Output(stdout=terminal).rows([("Name", "Role"), ("a", "admin")])
    assert terminal.getvalue() == "Name  Role\na     admin\n"


def test_run_labels_follow_numeric_columns_and_are_shell_words():
    import json
    import shlex

    from etl_craft.core.enums import RunStatus, TriggerKind
    from etl_craft.services.operations.models import RunView

    label = "SALES-2026-11-10 06:28:20-3"
    done = RunView(
        1,
        "SALES",
        3,
        "key",
        TriggerKind.MANUAL,
        None,
        RunStatus.SUCCESS,
        None,
        None,
        None,
        False,
        None,
        None,
        None,
        None,
        run_label=label,
    )
    stdout = io.StringIO()
    out = Output(stdout=stdout)
    out.result(done, "text", text=lambda: out.rows([("RUN_ID", "STATUS"), (3, "SUCCESS")]))
    columns = stdout.getvalue().splitlines()[1].split("\t")
    assert columns[0] == "3"
    assert shlex.split(columns[1]) == [label]
    stdout.seek(0)
    stdout.truncate()
    out.result(done, "json")
    assert json.loads(stdout.getvalue())["pipeline_run_id"] == 3
    assert "RUN_LABEL" not in stdout.getvalue()
