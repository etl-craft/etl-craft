"""Closed alert channel, event and delivery values."""

from enum import StrEnum

from etl_craft.core.enums import DependencyType, RunStatus


class AlertKind(StrEnum):
    """How a channel delivers: email through the Email relay, or an HTTPS receiver."""

    EMAIL = "EMAIL"
    WEBHOOK = "WEBHOOK"
    SLACK = "SLACK"


class AlertStatus(StrEnum):
    """Append-only admission and delivery outcomes."""

    ADMITTED = "ADMITTED"
    STARTED = "STARTED"
    SENT = "SENT"
    RETRY = "RETRY"
    FAILED = RunStatus.FAILED


class AlertTrigger(StrEnum):
    """Recorded source event categories."""

    FAILURE = DependencyType.FAILURE
    SUCCESS = RunStatus.SUCCESS
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    SLA_BREACH = "SLA_BREACH"
    LOST = "LOST"


class AlertErrorClass(StrEnum):
    """Controlled transport facts that contain no remote exception text."""

    HTTP = "HTTPError"
    TRANSPORT = "TransportError"
