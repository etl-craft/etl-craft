"""``etl-craft deploy``: publish the project, apply its config, load its seeds, refresh."""

import argparse
from pathlib import Path

from etl_craft.cli.commands.common import Command, call, configure_output
from etl_craft.cli.commands.config import render_sync
from etl_craft.cli.output import Output
from etl_craft.config import load_config, resolve_config_path
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ExitCode, UsageError
from etl_craft.engine.project_files import collect
from etl_craft.services.operations.deploy import DeployInput, Deployment


def configure(parser: argparse.ArgumentParser) -> None:
    """Resolve the project directory; ``--api`` needs no Engine DB credentials."""
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Run every step without writing: check the files, validate the config changes and "
        "roll them back, and list the seed tables.",
    )
    parser.add_argument(
        "--project-dir", type=Path, help="Project directory containing craft-connector.yml."
    )
    configure_output(parser)


def run(args: argparse.Namespace, out: Output) -> int:
    """Send the files when the deployment publishes them, then render each step."""
    if args.project_dir is not None and args.config is not None:
        raise UsageError(
            "deploy: --project-dir and --config both given; expected one source; choose one"
        )
    path = (
        (args.project_dir / "craft-connector.yml")
        if args.project_dir is not None
        else resolve_config_path(args.config)
    )
    args.config = path
    args.project_dir = None
    # Over the API the server publishes the files; here, only a store publishes them.
    publish = bool(args.api) or bool(load_config(path).artifacts.store)
    request = DeployInput(files=collect(path.parent) if publish else {}, plan=args.plan)
    result = call(args, ActionName.DEPLOY, request)
    assert isinstance(result, Deployment)
    out.result(result, args.output_format, text=lambda: _render(out, result, len(request.files)))
    return ExitCode.FAILURE if result.failed else ExitCode.SUCCESS


def _render(out: Output, done: Deployment, files: int) -> None:
    if done.bundle_id is not None:
        out.line(f"published bundle {done.bundle_id}: {files} files")
    elif done.plan and files:
        out.line(f"plan: {files} files checked, not published")
    if done.config is None:
        out.line("no config/ folder: config files skipped")
    else:
        render_sync(out, done.config, "plan" if done.plan else "apply")
        if done.config.failed:
            return
    if done.plan:
        for seed in done.seeds:
            out.line(f"seed {seed}: to load")
        return
    for load in done.seed_loads:
        out.line(load.message)
    for checked in done.refreshes:
        out.line(f"{checked.pipeline_code}: refresh {checked.status}")
        for finding in checked.findings:
            out.line(f"  {finding.file}: {finding.message}; {finding.remedy}")
    out.line("deploy stopped at the failure above" if done.failed else "deployed")


COMMAND = Command(
    "deploy",
    "Publish the project (with Artifacts.Store), apply its config, load its seeds and refresh "
    "its pipelines.",
    run,
    configure,
    (ActionName.DEPLOY,),
)
