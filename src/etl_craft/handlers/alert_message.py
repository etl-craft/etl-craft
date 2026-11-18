"""What an alert says: one subject and body for every channel kind, and the email around them.

``ALERT_SUBJECT`` and ``ALERT_BODY`` may use ``$$trigger`` (the event: ``FAILURE``,
``SUCCESS``, ``COMPLETED_WITH_ERRORS``, ``SLA_BREACH``, ``LOST`` or ``GATE_WAIT_OVER_<n>``),
``$$status`` (the source run's status), ``$$pipeline_id``, ``$$pipeline_run_id`` (the source
run), ``$$task_run_id`` (this alert task's run), ``$$pipeline_code``, ``$$task_code`` and
``$$error_message``. Any other ``$$`` token is refused. Email channels also read
``EMAIL_TEMPLATE``, ``EMAIL_TEMPLATE_TEXT`` and ``EMAIL_PIPELINES``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from etl_craft.core.alerts import AlertKind, AlertTrigger
from etl_craft.core.errors import HandlerError
from etl_craft.core.text import TOKEN
from etl_craft.handlers.mail import safe_subject

TOKENS = (
    "trigger",
    "status",
    "pipeline_id",
    "pipeline_run_id",
    "task_run_id",
    "pipeline_code",
    "task_code",
    "error_message",
)
EMAIL_PARAMETERS = frozenset({"EMAIL_TEMPLATE", "EMAIL_TEMPLATE_TEXT", "EMAIL_PIPELINES"})
PARAMETERS = frozenset(
    {"ALERT_CHANNEL", "ALERT_ON", "ALERT_SUBJECT", "ALERT_BODY", *EMAIL_PARAMETERS}
)
"""The task parameters an alert task reads."""

DEFAULT_SUBJECT = "$$pipeline_code: $$trigger · run $$pipeline_run_id"
DEFAULT_BODY = "Run $$pipeline_run_id of $$pipeline_code ended the event $$trigger ($$status)."


@dataclass(frozen=True)
class Message:
    """The words every channel kind sends."""

    subject: str
    body: str


def compose(params: Mapping[str, str], values: Mapping[str, str]) -> Message:
    """Fill the task's subject and body, or the built-in ones, from the event's values."""
    body = substitute(params.get("ALERT_BODY") or DEFAULT_BODY, values, "ALERT_BODY")
    if not params.get("ALERT_BODY") and values.get("error_message"):
        body = f"{body}\n{values['error_message']}"
    subject = substitute(params.get("ALERT_SUBJECT") or DEFAULT_SUBJECT, values, "ALERT_SUBJECT")
    return Message(safe_subject(subject), body)


def run_status(trigger: str, status: str) -> str:
    """Return the status an email shows; a run that was not clean reads COMPLETED_WITH_ERRORS."""
    return trigger if trigger == AlertTrigger.COMPLETED_WITH_ERRORS else status


def substitute(text: str, values: Mapping[str, str], setting: str) -> str:
    """Replace the ``$$`` tokens in ``text``; ``HandlerError`` naming an unknown one."""
    unknown = sorted({m.group(1) for m in TOKEN.finditer(text)} - set(values))
    if unknown:
        raise HandlerError(
            f"{setting} uses unknown token(s) {', '.join('$$' + t for t in unknown)}; the "
            f"tokens are {', '.join('$$' + t for t in TOKENS)}"
        )
    return TOKEN.sub(lambda m: values[m.group(1)], text)


def parameter_problems(params: Mapping[str, str], kind: AlertKind | None) -> list[str]:
    """Return what is wrong with an alert task's message settings for its channel's kind."""
    problems: list[str] = []
    blank = dict.fromkeys(TOKENS, "")
    for name in ("ALERT_SUBJECT", "ALERT_BODY"):
        if params.get(name):
            try:
                substitute(params[name], blank, name)
            except HandlerError as error:
                problems.append(str(error))
    if kind is not None and kind != AlertKind.EMAIL:
        for name in sorted(EMAIL_PARAMETERS & set(params)):
            problems.append(
                f"{name} applies to EMAIL channels only; this task's channel is {kind}; "
                f"remove {name} or select an EMAIL channel"
            )
    return problems
