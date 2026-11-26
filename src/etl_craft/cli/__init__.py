"""The ``etl-craft`` command line.

``main`` answers ``etl-craft agent health`` before importing the commands: Kubernetes runs that
probe every few seconds per agent, and the command tree costs seconds of CPU to import. Every
other command line goes to :mod:`etl_craft.cli.app`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etl_craft.cli.commands import Command

__all__ = ["main"]


def main(argv: Sequence[str] | None = None, commands: Sequence[Command] | None = None) -> int:
    """Run the command line and return its exit code.

    An ``EtlCraftError`` is reported by :func:`etl_craft.cli.app.main`; any other exception is a
    bug, logged with its traceback, and returns ``ExitCode.UNEXPECTED``.
    """
    words = list(sys.argv[1:] if argv is None else argv)
    if commands is None and words[:2] == ["agent", "health"]:
        status = _agent_health(words[2:])
        if status is not None:
            return status
    from etl_craft.cli import app

    try:
        return app.main(argv) if commands is None else app.main(argv, commands)
    except Exception as error:
        # Process boundary: anything else is a bug, logged with its traceback, never swallowed.
        command = next((word for word in words if not word.startswith("-")), "")
        logging.getLogger(__name__).exception("unexpected error in etl-craft %s", command)
        sys.stderr.write(f"error: unexpected {type(error).__name__}: {error}\n")
        from etl_craft.core.errors import ExitCode

        return ExitCode.UNEXPECTED


def _agent_health(words: list[str]) -> int | None:
    """Answer the plain probe forms; return ``None`` for anything the full parser must judge."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--config", type=Path)
    try:
        args, unknown = parser.parse_known_args(words)
    except argparse.ArgumentError:
        return None
    if unknown or (args.project_dir is not None and args.config is not None):
        return None
    from etl_craft.cli.agent_health import agent_health
    from etl_craft.core.errors import EtlCraftError, ExitCode

    try:
        agent_health(args.project_dir, args.config)
    except EtlCraftError as error:
        sys.stderr.write(f"error: {error}\n")
        return error.exit_code
    return ExitCode.SUCCESS
