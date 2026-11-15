"""The banner shows the mark and facts on a terminal, and plain facts everywhere else."""

import io
from dataclasses import replace

import pytest

from etl_craft.cli import main
from etl_craft.cli.banner import (
    LIGHT,
    MARK,
    MARK_TOP_ROWS,
    RED,
    TEAL,
    WORDMARK,
    WORDMARK_ROW,
    Facts,
    is_terminal,
    render,
    wants_art,
    wants_colour,
)

pytestmark = pytest.mark.unit

FACTS = Facts(
    version="1.2.3",
    schema="0085_ending_evidence.sql",
    account="owner",
    role="admin",
    project="orders",
    environment="PRODUCTION",
    production=True,
    controllers=0,
    server="1.2.4",
)


class Terminal(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


def test_a_terminal_banner_draws_the_mark_beside_aligned_rows():
    lines = render(FACTS, art=True, colour=False).splitlines()
    assert lines[0].startswith(MARK[0].rstrip())
    assert lines[WORDMARK_ROW].endswith(WORDMARK[0])  # the name in block letters beside the mark
    assert any(line.rstrip().endswith("owner (admin)") for line in lines)
    assert any("none live" in line for line in lines)
    assert any("Server" in line and "1.2.4" in line for line in lines)
    assert len({line.index("1.2.3") for line in lines if "1.2.3" in line}) == 1


def test_piped_output_has_no_mark_and_no_escape_codes():
    text = render(FACTS, art=False, colour=False)
    assert "\033" not in text and not any(char in text for char in "/\\|")
    assert text.splitlines()[0] == "etl-craft"


def test_production_is_red_only_when_colour_is_wanted():
    assert RED + "PRODUCTION" in render(FACTS, art=False, colour=True)
    assert "PRODUCTION" in render(FACTS, art=False, colour=False)
    assert "\033" not in render(FACTS, art=False, colour=False)


def test_lines_without_a_value_are_left_out():
    text = render(Facts(version="1.2.3"), art=False, colour=False)
    assert text.splitlines()[2:] == ["Version  1.2.3"]


def test_the_terminal_and_colour_rules(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert is_terminal(Terminal(True)) and wants_colour(Terminal(True))
    assert not is_terminal(Terminal(False)) and not wants_colour(Terminal(False))
    monkeypatch.setenv("NO_COLOR", "")
    assert is_terminal(Terminal(True)) and not wants_colour(Terminal(True))
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert not is_terminal(Terminal(True))


def test_a_bare_invocation_shows_the_banner_only_on_a_terminal(monkeypatch, capsys):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("COLUMNS", "100")
    assert main([]) == 2
    assert "etl-craft" not in capsys.readouterr().out.split("usage")[0]  # piped: usage only
    shown = Terminal(True)
    monkeypatch.setattr("sys.stdout", shown)
    assert main([]) == 2
    first, _, rest = shown.getvalue().partition("usage")
    assert MARK[0].strip() in first and "Version" in first and rest


def test_the_mark_needs_a_wide_enough_terminal_and_honours_suppression(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("ETL_CRAFT_NO_BANNER", raising=False)
    monkeypatch.setenv("COLUMNS", "100")
    assert wants_art(Terminal(True), FACTS)
    monkeypatch.setenv("COLUMNS", "30")
    assert not wants_art(Terminal(True), FACTS)  # narrow: plain rows only
    monkeypatch.setenv("COLUMNS", "120")
    assert not wants_art(Terminal(False), FACTS)
    monkeypatch.setenv("ETL_CRAFT_NO_BANNER", "1")
    assert not wants_art(Terminal(True), FACTS)


def test_suppression_leaves_a_bare_invocation_with_only_the_usage(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("ETL_CRAFT_NO_BANNER", "1")
    shown = Terminal(True)
    monkeypatch.setattr("sys.stdout", shown)
    assert main([]) == 2
    assert shown.getvalue().startswith("usage")


def test_the_mark_is_twenty_rows_with_a_clear_stem_and_chevron_gap():
    assert len(MARK) == 20
    assert {len(row) for row in MARK} == {38}
    assert all(set(row) <= set(" ▀▄█") for row in MARK)
    # The stem is separated from both arms; the lower chevron stays below it.
    assert "  " in MARK[13][8:17] and "  " in MARK[13][21:30]
    assert MARK[13][17:21].strip()
    # Only the upper half of this row holds the top layer; the stem starts below it.
    assert MARK[10][17:21] == " ▀▀ "
    coloured = render(FACTS, art=True, colour=True).splitlines()
    for index in range(len(MARK)):
        assert coloured[index].startswith(LIGHT if index < MARK_TOP_ROWS else TEAL)


def test_the_art_width_boundary_keeps_aligned_facts_inside_the_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("ETL_CRAFT_NO_BANNER", raising=False)
    lines = render(FACTS, art=True, colour=False).splitlines()
    width = max(map(len, lines))
    assert width <= 100
    monkeypatch.setenv("COLUMNS", str(width - 1))
    assert not wants_art(Terminal(True), FACTS)
    monkeypatch.setenv("COLUMNS", str(width))
    assert wants_art(Terminal(True), FACTS)


def test_long_facts_use_the_padded_label_width_for_the_art_boundary(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("ETL_CRAFT_NO_BANNER", raising=False)
    facts = replace(FACTS, schema="m" * 60)
    width = max(map(len, render(facts, art=True, colour=False).splitlines()))
    monkeypatch.setenv("COLUMNS", str(width - 1))
    assert not wants_art(Terminal(True), facts)
    monkeypatch.setenv("COLUMNS", str(width))
    assert wants_art(Terminal(True), facts)
