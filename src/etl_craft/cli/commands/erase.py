"""Register, preview, list or lift an admin's standing erasure."""

import argparse

from etl_craft.cli.commands.common import Command, call, configure_output
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ExitCode, UsageError
from etl_craft.services.operations.erasure import EraseInput
from etl_craft.services.operations.requests import NoInput


def configure(parser: argparse.ArgumentParser) -> None:
    """Keep erasure flags explicit and reuse project and output selection."""
    for name in ("table", "column", "value", "reason"):
        parser.add_argument("--" + name)
    for name in ("dry-run", "lift", "list"):
        parser.add_argument("--" + name, action="store_true")
    configure_output(parser)


def run(args: argparse.Namespace, out: Output) -> int:
    """All decisions and mutations stay in the shared admin operation."""
    if args.list:
        if any((args.table, args.column, args.value, args.reason, args.lift, args.dry_run)):
            raise UsageError("erase --list accepts no value or change flags; use --list alone")
        result = call(args, ActionName.ERASURE_LIST, NoInput())
    else:
        if any(getattr(args, name) is None for name in ("table", "column", "value", "reason")):
            raise UsageError("erase requires --table, --column, --value and --reason")
        result = call(
            args,
            ActionName.ERASE,
            EraseInput(
                table=args.table,
                column=args.column,
                value=args.value,
                reason=args.reason,
                dry_run=args.dry_run,
                lift=args.lift,
            ),
        )
    out.result(result, args.output_format, text=lambda: out.document(result))
    return ExitCode.SUCCESS


COMMAND = Command(
    "erase",
    "Apply standing personal-data erasures.",
    run,
    configure,
    (ActionName.ERASE, ActionName.ERASURE_LIST),
)
