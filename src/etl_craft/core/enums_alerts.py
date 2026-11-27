"""Closed alert channel, event and delivery values."""

from enum import StrEnum

from etl_craft.core.enums import AlertTrigger as AlertTrigger
from etl_craft.core.enums import RunStatus


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


class AlertErrorClass(StrEnum):
    """Controlled transport facts that contain no remote exception text."""

    HTTP = "HTTPError"
    TRANSPORT = "TransportError"
