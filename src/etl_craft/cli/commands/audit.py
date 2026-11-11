"""Read command requests and metadata changes without changing the Engine DB."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from etl_craft.cli.commands.common import (
    Command,
    call,
    configure_output,
    configure_tags,
    request_from,
)
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ExitCode
from etl_craft.services.operations.models import AuditView
from etl_craft.services.operations.requests import AuditInput


def _configure(parser: argparse.ArgumentParser) -> None:
    configure_output(parser)
    configure_tags(parser)
    parser.add_argument("--pipeline-code", help="Filter requests and related metadata rows.")
    parser.add_argument(
        "--since", type=datetime.fromisoformat, help="Changes since an ISO date or timestamp."
    )
    parser.add_argument(
        "--mine", action="store_true", help="Only your own requests, without metadata changes."
    )


def _run(args: argparse.Namespace, out: Output) -> int:
    done = call(args, ActionName.AUDIT, request_from(args, AuditInput))
    assert isinstance(done, AuditView)

    def render_text() -> None:
        limit = 100
        for resume in sorted(done.resumes, key=lambda row: row.resumed_at, reverse=True)[:limit]:
            out.line(
                f"{resume.pipeline_code}: resumed by {resume.actor} at {resume.resumed_at}: "
                f"{resume.reason}"
            )
        terminal = out.stdout.isatty()
        out.rows(
            [
                ("AT", "ACTOR", "KIND", "COMMAND", "OUTCOME", "RUN_ID", "ARGUMENTS"),
                *(
                    (
                        row.at,
                        row.actor,
                        row.kind,
                        row.command,
                        row.outcome,
                        row.pipeline_run_id,
                        _values(row.arguments, terminal),
                    )
                    for row in sorted(done.actions, key=lambda row: row.action_id, reverse=True)[
                        :limit
                    ]
                ),
            ]
        )
        out.rows(
            [
                (
                    "AT",
                    "ACTOR",
                    "KIND",
                    "TABLE",
                    "ROW",
                    "OPERATION",
                    "BEFORE",
                    "AFTER",
                    "MIGRATION",
                ),
                *(
                    (
                        row.at,
                        row.actor,
                        row.kind,
                        row.table_name,
                        _values(row.row_key, terminal),
                        row.operation,
                        _values(row.before_json, terminal),
                        _values(row.after_json, terminal),
                        row.migration,
                    )
                    for row in sorted(done.changes, key=lambda row: row.change_id, reverse=True)[
                        :limit
                    ]
                ),
            ]
        )
        return

    out.result(done, args.output_format, text=render_text, include_key=False)
    return ExitCode.SUCCESS


def _values(value: object, terminal: bool) -> str | None:
    """Keep machine-readable cells while making terminal fields readable."""
    if value is None:
        return None
    if terminal and isinstance(value, dict):
        return "; ".join(f"{key}={item}" for key, item in value.items() if item is not None)
    return json.dumps(value)


COMMAND = Command(
    "audit",
    "Show command requests and metadata changes with their actors.",
    configure=_configure,
    run=_run,
    actions=(ActionName.AUDIT,),
)
