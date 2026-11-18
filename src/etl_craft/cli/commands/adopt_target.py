"""``adopt-target``: take over an existing warehouse table as its configured writer's target."""

import argparse

from etl_craft.cli.commands.common import Command, call, request_from
from etl_craft.cli.output import Output
from etl_craft.core.adoption import AdoptResult
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ExitCode
from etl_craft.services.operations.maintenance import AdoptInput


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target",
        required=True,
        help="The existing table, as schema.table or catalog.schema.table.",
    )
    parser.add_argument(
        "--select",
        help="SELECT over the existing table returning its business columns and, optionally, "
        "CREATE_DATE, CREATED_BY, UPDATE_DATE, UPDATED_BY, ACTIVE_FLAG and DELETE_FLAG to keep "
        "(default: SELECT * FROM the target).",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep the original table as <target>_pre_adopt (by default it is dropped once the "
        "adopted table replaces it).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and show the SQL without changing tables."
    )


def _run(args: argparse.Namespace, out: Output) -> int:
    result = call(args, ActionName.ADOPT_TARGET, request_from(args, AdoptInput))
    assert isinstance(result, AdoptResult)
    if not result.adopted:
        out.line(f"{result.target}: already has every column {result.action} maintains")
        return ExitCode.SUCCESS
    original = f"kept as {result.kept}" if result.kept else "dropped"
    out.line(f"from the SELECT: {', '.join(result.mapped) or 'none'}")
    out.line(f"defaulted: {', '.join(result.defaulted) or 'none'}")
    if result.dry_run:
        out.line(f"{result.target}: would adopt for {result.action}; original would be {original}")
        for sql in result.sql:
            out.line(sql)
        return ExitCode.SUCCESS
    out.line(
        f"{result.target}: adopted {result.rows} row(s) for {result.action}; original {original}"
    )
    if result.rehash is not None:
        out.line(f"{result.target}: rehashed {result.rehash.rows} row(s); hash version 2")
    return ExitCode.SUCCESS


COMMAND = Command(
    "adopt-target",
    "Adopt an existing table as a target: rebuild it with the managed columns; the original "
    "is dropped unless --keep-original.",
    configure=_configure,
    run=_run,
    actions=(ActionName.ADOPT_TARGET,),
)
