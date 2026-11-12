"""Closed alert channel, event and delivery values."""

from enum import StrEnum

from etl_craft.core.enums import DependencyType, RunStatus


class AlertKind(StrEnum):
    """Supported receiver protocols."""

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
    SLA_BREACH = "SLA_BREACH"
    LOST = "LOST"


class AlertBodyFormat(StrEnum):
    """Wire shapes supported by the channel's selected receiver protocol."""

    JSON = "JSON"
    SLACK = AlertKind.SLACK


class AlertErrorClass(StrEnum):
    """Controlled transport facts that contain no remote exception text."""

    HTTP = "HTTPError"
    TRANSPORT = "TransportError"
