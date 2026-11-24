"""Keep the remote CLI guide's executable examples aligned with argparse."""

import shlex
from pathlib import Path

import pytest

from etl_craft.cli import build_parser

pytestmark = pytest.mark.docs


def test_remote_guide_commands_parse():
    guide = Path(__file__).resolve().parents[3] / "docs/guides/remote-cli.md"
    parser = build_parser()
    commands = [line for line in guide.read_text().splitlines() if line.startswith("etl-craft ")]
    assert commands, "remote CLI guide must contain executable examples"
    for command in commands:
        args = parser.parse_args(shlex.split(command)[1:])
        assert args.command is not None, command
