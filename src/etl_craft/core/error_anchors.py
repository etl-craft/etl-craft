"""Typed error events recorded by a single task interpreter."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock

from etl_craft.core.enums import FailureClass
from etl_craft.core.errors import EtlCraftError, ExitCode, UsageError
from etl_craft.core.failures import Failure
from etl_craft.core.redaction import mask_log


@dataclass(frozen=True)
class ErrorEvent:
    """An error as logged, before the supervisor knows its canonical location."""

    sequence: int
    step: str | None
    error_class: str
    exit_code: str
    failure_class: FailureClass


@dataclass(frozen=True)
class ErrorAnchors:
    """The first and last recorded errors of one attempt."""

    first: ErrorEvent
    last: ErrorEvent
    first_position: ErrorPosition | None = None
    last_position: ErrorPosition | None = None


class ErrorEvents:
    """Keep the first and latest error metadata without retaining log messages."""

    def __init__(self) -> None:
        """Start tracking an attempt with no errors."""
        self._lock = Lock()
        self._anchors: ErrorAnchors | None = None

    def record(self, error: BaseException, failure: Failure, step: str | None) -> int:
        """Allocate a sequence and carry forward the last known failing step."""
        with self._lock:
            previous = self._anchors
            code = error.exit_code if isinstance(error, EtlCraftError) else ExitCode.UNEXPECTED
            event = ErrorEvent(
                1 if previous is None else previous.last.sequence + 1,
                mask_log(step)
                if step is not None
                else (None if previous is None else previous.last.step),
                type(error).__name__,
                code.name,
                failure.kind,
            )
            self._anchors = ErrorAnchors(event if previous is None else previous.first, event)
            return event.sequence

    @property
    def anchors(self) -> ErrorAnchors | None:
        """Return the evidence available at the terminal commit."""
        with self._lock:
            return self._anchors


_events: ContextVar[ErrorEvents | None] = ContextVar("error_events", default=None)


@contextmanager
def capture_errors() -> Iterator[None]:
    """Scope the sequence counter and evidence to this task invocation."""
    token = _events.set(ErrorEvents())
    try:
        yield
    finally:
        _events.reset(token)


def recorded_errors() -> ErrorAnchors | None:
    """Return the current task's evidence."""
    events = _events.get()
    return None if events is None else events.anchors


def error_fields(
    logger: logging.Logger, error: BaseException, failure: Failure, *, step: str | None = None
) -> dict[str, int]:
    """Supply a marker for a classified error written to the attempt log."""
    events = _events.get()
    if events is None or not logger.isEnabledFor(logging.ERROR):
        return {}
    return {"event_sequence": events.record(error, failure, step)}


MARKER_NONCE_ENV = "ETL_CRAFT_LOG_MARKER_NONCE"
MARKER = re.compile(rb"\[event ([1-9][0-9]{0,18})\]")


@dataclass(frozen=True)
class ErrorPosition:
    """A marker's physical line number and the byte offset where that line starts."""

    sequence: int
    offset: int
    line: int

    def __post_init__(self) -> None:
        """Require physical positions that can be represented by the Engine DB."""
        if not (0 < self.sequence < 2**63 and 0 <= self.offset < 2**63 and 0 < self.line < 2**63):
            raise UsageError(
                f"error event {self.sequence}, offset {self.offset}, line {self.line}: expected "
                "positive sequence and line and nonnegative offset within BIGINT; "
                "send the observed log position or leave it absent"
            )
