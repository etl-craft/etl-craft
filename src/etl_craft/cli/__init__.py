"""The ``etl-craft`` command line."""

from __future__ import annotations

import argparse
import difflib
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from etl_craft import __version__
from etl_craft.cli.authentication import access_context
from etl_craft.cli.banner import Facts, is_terminal, render, suppressed, wants_art, wants_colour
from etl_craft.cli.commands import COMMANDS, Command
from etl_craft.cli.output import Output
from etl_craft.core import log
from etl_craft.core.compatibility import input_refusal
from etl_craft.core.enums import InputKind
from etl_craft.core.errors import EtlCraftError, ExitCode

logger = logging.getLogger(__name__)

DEFAULT_LOG_LEVEL = "INFO"


class CommandHelp(argparse.HelpFormatter):
    """Group the command inventory by the work the person is doing."""

    def _format_action(self, action: argparse.Action) -> str:
        if not isinstance(action, argparse._SubParsersAction):
            return super()._format_action(action)
        groups: dict[str, list[str]] = {}
        for choice in action._choices_actions:
            name = choice.dest
            group = (
                "Run and inspect"
                if name
                in {
                    "run",
                    "status",
                    "history",
                    "pipelines",
                    "graph",
                    "explain",
                    "logs",
                    "items",
                    "audit",
                    "lineage",
                    "search",
                }
                else "Sign in and administer"
                if name
                in {
                    "login",
                    "logout",
                    "whoami",
                    "sso-login",
                    "account",
                    "token",
                    "group",
                    "access",
                    "project",
                    "pool",
                }
                else "Control work"
                if name
                in {
                    "hold",
                    "release",
                    "stop",
                    "abort",
                    "pause",
                    "resume",
                    "mark",
                    "reconcile",
                    "agent",
                }
                else "Configure and operate"
            )
            groups.setdefault(group, []).append(f"  {name:<22} {choice.help}\n")
        return "".join(f"\n{group}:\n" + "".join(lines) for group, lines in groups.items())


class CommandParser(argparse.ArgumentParser):
    """Keep refusals short and suggest the nearest known command or option."""

    def error(self, message: str) -> NoReturn:
        """Print a remedy without dumping the complete command inventory."""
        values = list(self._option_string_actions)
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                values.extend(action.choices)
        invalid = re.search(r"invalid choice: '([^']+)'", message)
        words = [invalid.group(1)] if invalid else re.findall(r"(?<!\w)-{1,2}[\w-]+", message)
        suggestion = next(
            (
                match[0]
                for word in words
                if (match := difflib.get_close_matches(word, values, n=1, cutoff=0.75))
            ),
            None,
        )
        if message.startswith("unrecognized arguments:"):
            message += "; " + " ".join(input_refusal(InputKind.CLI_OPTION, word) for word in words)
        message = message.split(" (choose from", 1)[0]
        hint = f" Did you mean {suggestion!r}?" if suggestion else ""
        self.exit(2, f"{self.prog}: error: {message}.{hint} Use {self.prog} --help.\n")


def _global_options(*, defaults: bool) -> argparse.ArgumentParser:
    """Build the options every command accepts, before or after the command name.

    The copy attached to each subcommand has no defaults, so a value given before the command
    name is not overwritten by the subcommand's parser.
    """
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("global options")

    def default(value: object) -> object:
        return value if defaults else argparse.SUPPRESS

    group.add_argument(
        "--yes",
        action="store_true",
        default=default(False),
        help="Confirm production changes or a printed selection without prompting.",
    )
    group.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="The craft-connector.yml to read.",
        default=default(None),
    )
    group.add_argument(
        "--api",
        metavar="URL",
        help="Operate this etl-craft API instead of the local project (default: "
        "$ETL_CRAFT_API); https:// except to localhost.",
        default=default(None),
    )
    group.add_argument(
        "--project",
        metavar="CODE",
        help="Project code (otherwise required in Orchestration.Project).",
        default=default(None),
    )
    group.add_argument(
        "--log-level",
        type=str.upper,
        choices=log.LEVELS,
        help="Lowest log level on stderr (default: WARNING for run, INFO otherwise).",
        default=default(None),
    )
    group.add_argument(
        "--log-format",
        type=str.lower,
        choices=[member.value for member in log.LogFormat],
        help="Log records as text lines or JSON objects (default: text).",
        default=default(log.LogFormat.TEXT.value),
    )
    if not defaults:
        for option in group._group_actions:
            option.help = argparse.SUPPRESS
    return parser


def build_parser(
    commands: Sequence[Command] = COMMANDS,
    parser_class: type[argparse.ArgumentParser] = CommandParser,
) -> argparse.ArgumentParser:
    """Build the top-level argument parser with one subcommand per entry in ``commands``.

    Subcommand parsers take ``parser_class`` too, so a caller can change how errors are shown.
    """
    parser = parser_class(
        prog="etl-craft",
        description="Metadata-driven ETL orchestration engine.",
        formatter_class=CommandHelp,
        parents=[_global_options(defaults=True)],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"etl-craft {__version__}",
        help="Print the version and exit.",
    )
    if commands:
        subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
        shared = _global_options(defaults=False)
        for command in commands:
            subparser = subparsers.add_parser(
                command.name,
                help=command.help,
                description=command.help,
                parents=[shared],
                epilog=(
                    "Global options: use etl-craft --help; accepted before or after this command."
                ),
            )
            if command.configure is not None:
                command.configure(subparser)
            subparser.set_defaults(handler=command.run)
    return parser


def main(argv: Sequence[str] | None = None, commands: Sequence[Command] = COMMANDS) -> int:
    """Run the command line and return its exit code.

    Returns 2 with the usage when no command is given. An ``EtlCraftError`` is written as an
    ``error:`` line and returns its own exit status; any other exception is a bug, logged with its
    traceback, and returns ``ExitCode.UNEXPECTED``.
    """
    parser = build_parser(commands)
    args = parser.parse_args(argv)
    out = Output()
    args._output = out
    if getattr(args, "handler", None) is None:
        hello = Facts(version=__version__)
        if is_terminal(out.stdout) and not suppressed():
            art = wants_art(out.stdout, hello)
            out.line(render(hello, art=art, colour=wants_colour(out.stdout)))
            out.line("")
        parser.print_usage(out.stdout)
        return ExitCode.USAGE
    requested_level = args.log_level
    args.log_level = requested_level or DEFAULT_LOG_LEVEL
    console_level = (
        "WARNING" if args.command == "run" and requested_level is None else args.log_level
    )
    log.configure(console_level, args.log_format)
    args.api = args.api or os.environ.get("ETL_CRAFT_API")
    try:
        if args.api or args.command == "agent" or (args.command == "doctor" and args.agent):
            return int(args.handler(args, out))
        with access_context(args):
            return int(args.handler(args, out))
    except EtlCraftError as error:
        out.error(as_flags(str(error), parser))
        return error.exit_code
    except Exception as error:
        logger.exception("unexpected error in etl-craft %s", args.command)
        out.error(f"unexpected {type(error).__name__}: {error}")
        return ExitCode.UNEXPECTED


def _options(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Map every option's destination to its flag, through every subcommand."""
    found: dict[str, str] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found.update(_options(sub))
        elif action.option_strings:
            found.setdefault(action.dest, max(action.option_strings, key=len))
    return found


def as_flags(message: str, parser: argparse.ArgumentParser) -> str:
    """Show each request field a message names in backticks as the option that sets it."""
    options = _options(parser)
    return re.sub(
        r"`([a-z_]+)`",
        lambda m: f"`{options[m.group(1)]}`" if m.group(1) in options else m.group(0),
        message,
    )
