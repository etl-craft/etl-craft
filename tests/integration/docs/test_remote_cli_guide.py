"""Keep the guides' and concepts page's executable examples aligned with argparse."""

import shlex
from pathlib import Path

import pytest

from etl_craft.cli import build_parser

pytestmark = pytest.mark.docs


@pytest.mark.parametrize("page", ["guides/remote-cli.md", "guides/access.md", "concepts.md"])
def test_remote_guide_commands_parse(page):
    guide = Path(__file__).resolve().parents[3] / "docs" / page
    parser = build_parser()
    commands = [line for line in guide.read_text().splitlines() if line.startswith("etl-craft ")]
    assert commands, f"{page} must contain executable examples"
    for command in commands:
        args = parser.parse_args(shlex.split(command)[1:])
        assert args.command is not None, command
