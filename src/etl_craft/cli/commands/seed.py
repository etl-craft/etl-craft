"""Apply reference files from the published project bundle."""

import argparse

from etl_craft.cli.commands.common import Command, call, configure_output
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import ExitCode
from etl_craft.services.operations.requests import NoInput
from etl_craft.services.operations.seeds import SeedLoads


def configure(parser: argparse.ArgumentParser) -> None:
    """Seed apply accepts only the shared project and output options."""
    parser.add_argument("operation", choices=["apply"])
    configure_output(parser)


def run(args: argparse.Namespace, out: Output) -> int:
    """Render the exact messages recorded with the completed loads."""
    result = call(args, ActionName.SEED_APPLY, NoInput())
    assert isinstance(result, SeedLoads)

    def render() -> None:
        for load in result.loads:
            out.line(load.message)

    out.result(result, args.output_format, text=render)
    return (
        ExitCode.FAILURE
        if any(load.status == SeedStatus.FAILED for load in result.loads)
        else ExitCode.SUCCESS
    )


COMMAND = Command(
    "seed", "Apply the published project's seed tables.", run, configure, (ActionName.SEED_APPLY,)
)
