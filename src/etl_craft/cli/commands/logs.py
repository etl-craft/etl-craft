"""``etl-craft logs``: one attempt's log, or a pipeline run's log, from this project or a server."""

from __future__ import annotations

import argparse
import shlex
from collections.abc import Iterable
from pathlib import Path

from etl_craft.cli.commands.common import Command, call, configure_run_selector, request_from
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ExitCode, UsageError
from etl_craft.services.operations.requests import AttemptId, LogInput, RunFilter, RunSelection


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--attempt-id", type=int, help="The attempt whose log.")
    parser.add_argument(
        "--offset", type=int, default=0, help="Start this many bytes into the log (default: 0)."
    )
    parser.add_argument(
        "--pipeline-code", help="The pipeline whose run log, rendered from the audit tables."
    )
    configure_run_selector(parser)
    parser.add_argument(
        "--zip",
        type=Path,
        dest="zip_path",
        help="Write the run's zip (run log, attempt logs, documents, manifest) to this file.",
    )


def _run(args: argparse.Namespace, out: Output) -> int:
    if (args.attempt_id is None) == (args.pipeline_code is None):
        raise UsageError(
            "logs: give --attempt-id for one attempt's log, or --pipeline-code (with --run-id "
            "or --run-key, or the single active run) for the pipeline run log"
        )
    if args.zip_path is not None and args.pipeline_code is None:
        raise UsageError("logs --zip: give --pipeline-code and the run; zips cover whole runs")
    detail = call(
        args,
        ActionName.ATTEMPT if args.attempt_id is not None else ActionName.STATUS,
        AttemptId(attempt_id=args.attempt_id)
        if args.attempt_id is not None
        else request_from(args, RunFilter),
    )
    from etl_craft.cli.rendering import run_labels
    from etl_craft.services.operations.status import StatusView

    selected = None
    if isinstance(detail, StatusView):
        selected = RunSelection(
            pipeline_code=detail.run.pipeline_code, run_id=detail.run.pipeline_run_id
        )
        detail = detail.run

    for kind, labels in run_labels(detail).items():
        for number, label in labels.items():
            out.context_line(
                f"{'task_run_id' if kind == 'task' else 'run_id'}={number} {shlex.quote(label)}"
            )
    if args.zip_path is not None:
        archive = call(args, ActionName.RUN_ZIP, selected)
        assert isinstance(archive, Iterable)
        with args.zip_path.open("wb") as target:
            for chunk in archive:
                target.write(chunk)
        out.line(f"wrote {args.zip_path}")
        return ExitCode.SUCCESS
    if args.attempt_id is not None:
        chunks = call(args, ActionName.LOGS, request_from(args, LogInput))
    else:
        chunks = call(args, ActionName.RUN_LOG, selected)
    assert isinstance(chunks, Iterable)
    out.chunks(chunks)
    return ExitCode.SUCCESS


COMMAND = Command(
    "logs",
    "Print one attempt's log or a pipeline run's log, or write a run's zip.",
    run=_run,
    configure=_configure,
    actions=(
        ActionName.LOGS,
        ActionName.RUN_LOG,
        ActionName.RUN_ZIP,
        ActionName.ATTEMPT,
        ActionName.STATUS,
    ),
)
