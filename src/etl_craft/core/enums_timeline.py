"""Closed values for a run's timeline of recorded waits and attempts.

Split from ``core.enums`` by concern; the same rules apply to every closed set here.
"""

from __future__ import annotations

from enum import StrEnum


class TimelineKind(StrEnum):
    """What one timeline segment records."""

    QUEUE = "QUEUE"
    """An attempt waiting for an agent slot, from queuing to start."""
    GATE = "GATE"
    """A dependency gate wait, from its first check to its recorded decision."""
    EVENT = "EVENT"
    """An event wait, from its first check to its task's recorded end."""
    CHILD_RUN = "CHILD_RUN"
    """A trigger task waiting for its child pipeline run."""
    EXECUTION = "EXECUTION"
    """An attempt running, from start to end."""


class WaitOutcome(StrEnum):
    """How a recorded wait ended, or that it is still open."""

    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    BYPASSED = "BYPASSED"
    """An unmet dependency was overridden or bypassed by policy."""
    REFUSED = "REFUSED"
    TIMED_OUT = "TIMED_OUT"
    ENDED = "ENDED"
    """The wait stopped with its run, before any decision was recorded."""
