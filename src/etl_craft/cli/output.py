"""The only place etl-craft writes to the terminal.

Command results go to standard output, so they can be piped; errors go to standard error, next
to the log records.
"""

from __future__ import annotations

import codecs
import json
import os
import sys
from collections.abc import Callable, Iterable
from typing import TextIO

from etl_craft.cli.prompts import can_prompt
from etl_craft.core.enums_access import EnvironmentType
from etl_craft.core.environment import Environment
from etl_craft.core.errors import UsageError
from etl_craft.engine.controls import ControlView
from etl_craft.services.operations import to_json
from etl_craft.services.operations.agents import AgentsView
from etl_craft.services.operations.models import BackfillView, OperationResult, ReconciliationView


class Output:
    """Writes a command's results and errors.

    The streams default to the current ``sys.stdout`` and ``sys.stderr``, looked up at each
    write, so redirecting them after construction still takes effect.
    """

    def __init__(self, stdout: TextIO | None = None, stderr: TextIO | None = None) -> None:
        """Write to the given streams instead of the process's standard streams."""
        self._stdout = stdout
        self._stderr = stderr
        self.environment: Environment | None = None
        self.project = ""
        self.confirmed = False
        self.environment_reason: str | None = None

    def context(
        self, project: str, environment: Environment, api: str | None, *, json: bool
    ) -> None:
        """Print one selected-project banner, or attach it to subsequent JSON results."""
        previous = (self.project, self.environment.label if self.environment else None)
        self.project, self.environment = project, environment
        if not json and previous != (project, environment.label):
            self.context_line(f"{project} · {environment.label} · {api or 'local'}")

    def context_line(self, text: str) -> None:
        """Keep context on one line without terminal-control sequences from display names."""
        line = " ".join(text.split())
        print("".join(char for char in line if char.isprintable()), file=self.stderr)

    def unknown_environment(self, engine: str, *, json: bool) -> None:
        """Make legacy schema uncertainty explicit without inventing a project environment."""
        self.environment_reason = "Engine DB predates environment metadata"
        if not json:
            self.context_line(f"{engine} · environment unknown ({self.environment_reason})")

    def confirm(self, action: str, *, yes: bool) -> None:
        """Confirm production changes once per command before an operation is called."""
        if (
            self.environment is None
            or self.environment.type != EnvironmentType.PROD
            or self.confirmed
        ):
            return
        if not yes:
            remedy = f"type {self.project!r} at a terminal, or pass --yes for unattended execution"
            if not can_prompt() or os.environ.get("CI"):
                raise UsageError(
                    f"project {self.project!r}, environment PRODUCTION: {action} requires "
                    f"confirmation; {remedy}"
                )
            print(
                f"PRODUCTION action: {action}; type project code {self.project} to confirm:",
                file=self.stderr,
            )
            try:
                answer = input()
            except EOFError as error:
                raise UsageError(
                    f"project {self.project!r}, environment PRODUCTION: confirmation ended; "
                    f"{remedy}"
                ) from error
            if answer != self.project:
                raise UsageError(
                    f"project {self.project!r}, environment PRODUCTION: confirmation did "
                    f"not match; project action was not executed; {remedy}"
                )
        self.confirmed = True

    @property
    def stdout(self) -> TextIO:
        """The stream results are written to."""
        return sys.stdout if self._stdout is None else self._stdout

    @property
    def stderr(self) -> TextIO:
        """The stream errors are written to."""
        return sys.stderr if self._stderr is None else self._stderr

    def line(self, text: str = "") -> None:
        """Write one line of results."""
        print(text, file=self.stdout)

    def chunks(self, chunks: Iterable[bytes], *, binary: bool = False) -> None:
        """Preserve download bytes; text-only sinks decode across chunk boundaries."""
        stream = getattr(self.stdout, "buffer", None) if binary else None
        if stream is not None:
            for chunk in chunks:
                stream.write(chunk)
            return
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict" if binary else "replace")
        for chunk in chunks:
            self.stdout.write(decoder.decode(chunk))
        self.stdout.write(decoder.decode(b"", final=True))

    def document(self, result: object) -> None:
        """Write operation JSON with the selected CLI environment metadata."""
        document = to_json(result)
        if self.environment_reason is not None:
            document = {
                **document,
                "environment": None,
                "environment_reason": self.environment_reason,
            }
        elif self.environment is not None and isinstance(document, dict):
            document = {
                **document,
                "environment": {"type": self.environment.type, "name": self.environment.name},
            }
        self.line(json.dumps(document, ensure_ascii=False, allow_nan=False))

    def result(
        self,
        done: object,
        output_format: str,
        *,
        text: Callable[[], None] | None = None,
    ) -> None:
        """Write JSON or render the command's text, defaulting to its outcome message."""
        if output_format == "json":
            self.document(done)
        elif text is not None:
            text()
        elif isinstance(done, ControlView):
            self.line(
                f"control_id={done.control_id} {done.action} {done.status}; "
                f"run_id={done.pipeline_run_id} task={done.task_code or 'all'} "
                f"run_status={done.run_status} execution_run_id={done.execution_run_id}: "
                f"{done.message}"
            )
        else:
            assert isinstance(done, (OperationResult, BackfillView, ReconciliationView))
            self.line(done.message)
            label = getattr(getattr(done, "run", None), "run_label", "")
            if label:  # beside the id, off the result line that scripts read
                print(f"run label: {label}", file=self.stderr)

    def rows(self, rows: Iterable[Iterable[object]]) -> None:
        """Align terminal columns; pipes retain TSV and ``None`` stays an empty field."""
        rendered = [["" if value is None else str(value) for value in row] for row in rows]
        if not self.stdout.isatty():
            for row in rendered:
                self.line("\t".join(row))
            return
        widths = [
            max(len(row[i]) if i < len(row) else 0 for row in rendered)
            for i in range(max((len(row) for row in rendered), default=0))
        ]
        for row in rendered:
            self.line("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)).rstrip())

    def agents(self, view: AgentsView | None) -> None:
        """Render the shared registry's advertised, reserved and free resources."""
        if view is None:
            return
        self.rows(
            [
                (
                    "AGENT",
                    "POOL",
                    "HOST",
                    "STATUS",
                    "USED_SLOTS",
                    "FREE_SLOTS",
                    "CPU",
                    "CPU_RESERVED",
                    "CPU_FREE",
                    "MEMORY_MB",
                    "MEMORY_RESERVED_MB",
                    "MEMORY_FREE_MB",
                    "HEARTBEAT",
                )
            ]
        )
        self.rows(
            (
                a.agent_id,
                a.pool,
                a.host,
                a.status,
                a.used,
                a.free,
                a.advertised_cpu,
                a.reserved_cpu,
                a.free_cpu,
                a.advertised_memory_mb,
                a.reserved_memory_mb,
                a.free_memory_mb,
                a.heartbeat_at,
            )
            for a in view.agents
        )
        self.rows(
            [
                (
                    "POOL",
                    "AGENTS",
                    "CPU",
                    "CPU_RESERVED",
                    "CPU_FREE",
                    "MEMORY_MB",
                    "MEMORY_RESERVED_MB",
                    "MEMORY_FREE_MB",
                )
            ]
        )
        self.rows(
            (
                p.pool,
                p.agents,
                p.advertised_cpu,
                p.reserved_cpu,
                p.free_cpu,
                p.advertised_memory_mb,
                p.reserved_memory_mb,
                p.free_memory_mb,
            )
            for p in view.pools
        )

    def empty(self, what: str) -> None:
        """Report a result with nothing in it, such as ``(no active pipelines)``."""
        self.line(f"({what})")

    def error(self, message: str) -> None:
        """Write ``error: <message>`` to standard error."""
        print(f"error: {message}", file=self.stderr)
