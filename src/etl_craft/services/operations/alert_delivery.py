"""One server-owned delivery operation for local and agent alert tasks, for every channel kind."""

import hashlib
import hmac
import json
import logging
import ssl
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from sqlalchemy.engine import Row

from etl_craft.config.resolve import resolve_named_secret
from etl_craft.core.actor import acting_as
from etl_craft.core.alerts import (
    HTTP_TIMEOUT,
    RETRY_DELAYS,
    AlertErrorClass,
    AlertKind,
    AlertStatus,
)
from etl_craft.core.enums import ApiRole, Handler, RunStatus, YesNo
from etl_craft.core.errors import (
    ConfigurationError,
    EtlCraftError,
    HandlerError,
    PermissionDeniedError,
    StaleTransitionError,
)
from etl_craft.core.redaction import mask, registering
from etl_craft.core.task_secrets import read
from etl_craft.engine.alert_channels import AlertChannel
from etl_craft.engine.alert_deliveries import AlertEvent, DeliveryAttempt, append, event
from etl_craft.engine.alerts import read_alert
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.handlers.alert_message import Message, compose, run_status
from etl_craft.handlers.email_context import email_context
from etl_craft.handlers.email_templates import render
from etl_craft.handlers.mail import parse_recipients, safe_subject, send_email
from etl_craft.handlers.registry import HandlerResult, TaskContext
from etl_craft.services.operations.context import OperationContext

logger = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    """Never forward a secret URL's payload or headers to a redirected destination."""

    def redirect_request(
        self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        """Refuse redirect forwarding, including an HTTPS target."""
        return None


def post(
    url: str, body: bytes, headers: dict[str, str]
) -> tuple[int | None, AlertErrorClass | None]:
    """Discard response bodies and exception text at the network boundary."""
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(
            Request(url, body, headers, method="POST"), timeout=HTTP_TIMEOUT
        ) as response:
            return response.status, None
    except HTTPError as error:
        code = error.code
        error.close()
        return code, AlertErrorClass.HTTP
    except (URLError, OSError, HTTPException, UnicodeError):
        return None, AlertErrorClass.TRANSPORT


def credentials(ctx: OperationContext, task: TaskContext, channel: AlertChannel) -> tuple[str, str]:
    """Resolve only references authorized by the administrator-owned channel."""
    if channel.url_secret is None or channel.signing_secret is None:
        raise ConfigurationError(
            f"channel {channel.channel_name}: kind={channel.kind} without URL_SECRET and "
            "SIGNING_SECRET; expected both variable names; set the channel again with them"
        )
    names = (channel.url_secret, channel.signing_secret)
    values = []
    for name in names:
        try:
            value = (
                resolve_named_secret(ctx.config, name)
                if task._secret_values is None
                else read(
                    task._secret_values,
                    tuple(names),
                    f"channel {channel.channel_name}",
                    str(ctx.config.source.type),
                    name,
                )
            )
            values.append(value)
        except EtlCraftError:
            raise ConfigurationError(
                f"channel {channel.channel_name}, variable {name}: missing or empty; "
                "expected a configured secret variable; set it in the secret source"
            ) from None
    url, key = values
    try:
        address = urlsplit(url)
        _ = address.port
    except ValueError:
        raise ConfigurationError(
            f"channel {channel.channel_name}, variable {channel.url_secret}: invalid endpoint; "
            "expected an HTTPS URL with a valid port; correct the secret variable"
        ) from None
    if address.scheme != "https" or not address.hostname or address.username or address.password:
        raise ConfigurationError(
            f"channel {channel.channel_name}, variable {channel.url_secret}: invalid endpoint; "
            "expected an HTTPS URL without userinfo; correct the secret variable"
        )
    try:
        key_bytes = key.encode()
    except UnicodeError:
        raise ConfigurationError(
            f"channel {channel.channel_name}, variable {channel.signing_secret}: invalid UTF-8; "
            "expected a UTF-8 key of at least 32 bytes; replace the secret variable"
        ) from None
    if len(key_bytes) < 32:
        raise ConfigurationError(
            f"channel {channel.channel_name}, variable {channel.signing_secret}: short key; "
            "expected at least 32 bytes; replace the secret variable"
        )
    return url, key


def deliver(ctx: OperationContext, task: TaskContext) -> HandlerResult:
    """Deliver for an ordinary alert task; never send from event observation."""
    if ctx.role not in {ApiRole.ADMIN, ApiRole.AGENT} or task.handler != Handler.ALERT:
        raise PermissionDeniedError(
            f"alert task {task.task_code}: role={ctx.role}, handler={task.handler}; expected the "
            "server-owned ALERT operation; dispatch the recorded alert task"
        )
    if ctx.role == ApiRole.AGENT and (
        task.attempt_id is None or ctx.credential_attempt_id != task.attempt_id
    ):
        raise PermissionDeniedError(
            "alert task: mismatched credential attempt; use the exact admitted claim"
        )
    with acting_as(ctx.actor), ctx.engine.connect() as conn:
        source = event(conn, task.pipeline_run_id)
        if source is None:
            return HandlerResult(
                variables={"ALERT_SENT": False, "REASON": "event admission owns delivery"}
            )
        row = conn.execute(
            statement(conn, "alert_source"), {"source_run_id": source.source_run_id}
        ).one_or_none()
        if row is None:
            raise HandlerError(
                f"alert run {task.pipeline_run_id}: source run {source.source_run_id} "
                "is missing; expected retained event history; restore it or cancel this alert run"
            )
        channel = conn.execute(
            statement(conn, "alert_channel"),
            {
                "project_id": ctx.project_id,
                "channel_name": task.task_params["ALERT_CHANNEL"],
            },
        ).one_or_none()
        if (
            channel is None
            or channel.channel_id != source.channel_id
            or channel.active_flag != YesNo.YES
        ):
            raise HandlerError(
                f"alert run {task.pipeline_run_id}: channel is missing or inactive; expected its "
                "admitted project channel; restore the channel before retrying"
            )
        previous = conn.execute(
            statement(conn, "alert_delivery_attempts"), {"run_id": task.pipeline_run_id}
        ).all()
    if any(item.status == AlertStatus.SENT for item in previous):
        return HandlerResult(variables={"ALERT_SENT": True})
    configured = AlertChannel(**channel._mapping)
    message = compose(
        task.task_params,
        {
            "trigger": source.trigger,
            "status": str(row.status),
            "pipeline_id": str(row.pipeline_id),
            "pipeline_run_id": str(row.run_id),
            "task_run_id": str(task.task_run_id),
            "pipeline_code": row.pipeline_code,
            "task_code": task.task_code,
            "error_message": row.error_message or "",
        },
    )
    if configured.kind == AlertKind.EMAIL:
        sender = Sender(_email(ctx, task, configured, source, row, message), "a relay acceptance")
        return _attempts(Delivery(ctx, task, source, configured.channel_name, sender), previous)
    url, key = credentials(ctx, task, configured)
    with registering(url, key), acting_as(ctx.actor), selected_project(ctx.project_id):
        body = _https_body(ctx, task, configured.kind, source, row, message)
        sender = Sender(lambda: _post_signed(url, key, body), "an HTTPS 2xx response")
        return _attempts(Delivery(ctx, task, source, configured.channel_name, sender), previous)


def _https_body(
    ctx: OperationContext,
    task: TaskContext,
    kind: AlertKind,
    source: AlertEvent,
    row: Row[Any],
    message: Message,
) -> bytes:
    """Return the exact bytes a webhook or Slack receiver is sent, with secrets masked."""
    if kind == AlertKind.SLACK:
        payload: object = {
            "text": mask(f"{message.subject}\n{message.body}"),
            "link_names": False,
            "unfurl_links": False,
            "unfurl_media": False,
        }
    else:
        payload = mask(
            {
                "schema": "etl-craft/alert/1",
                "event_id": source.event_id,
                "trigger": source.trigger,
                "subject": message.subject,
                "body": message.body,
                "run": {"id": row.run_id, "label": row.run_label},
                "task": {
                    "alert": task.task_code,
                    "source_task_id": source.source_task_id,
                    "source_attempt_id": source.source_attempt_id,
                },
                "status": row.status,
                "error": row.error_message,
                "links": {
                    "run": f"/ui/projects/{ctx.project}/runs/{row.pipeline_code}/{row.run_id}"
                },
            }
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _email(
    ctx: OperationContext,
    task: TaskContext,
    channel: AlertChannel,
    source: AlertEvent,
    row: Row[Any],
    message: Message,
) -> Callable[[], tuple[int | None, AlertErrorClass | None]]:
    """Render the whole email before the first attempt; each attempt only hands it to the relay."""
    if ctx.config.email is None:
        raise ConfigurationError(
            f"channel {channel.channel_name}: kind=EMAIL, but craft-connector.yml has no "
            "Orchestration Email block; expected the relay's host, port and from address; add it"
        )
    recipients = parse_recipients(channel.recipients, f"channel {channel.channel_name} RECIPIENTS")
    with selected_project(ctx.project_id), ctx.engine.connect() as conn:
        state = read_alert(
            conn,
            row.pipeline_id,
            row.run_id,
            task.task_params.get("EMAIL_PIPELINES"),
        )
    data = email_context(
        state, pipeline=row.pipeline_code, status=run_status(source.trigger, str(row.status))
    )
    assert state.environment is not None
    subject = safe_subject(f"[{state.environment.label.split(' · ')[0]}] {message.subject}")
    data.update(
        subject=subject,
        body=message.body,
        task={
            "code": task.task_code,
            "run_id": task.task_run_id,
            "status": RunStatus.IN_PROGRESS,
            "attempt": task.attempt,
        },
        recipients=recipients,
        recipient_reason=f"channel {channel.channel_name}",
    )
    html = render(ctx.config, task.task_params.get("EMAIL_TEMPLATE"), data)
    text = render(ctx.config, task.task_params.get("EMAIL_TEMPLATE_TEXT"), data, text=True)

    def send() -> tuple[int | None, AlertErrorClass | None]:
        try:
            send_email(ctx.config, recipients, subject, html, body_text=text)
        except HandlerError as error:
            logger.error("channel %s: %s", channel.channel_name, error)
            return None, AlertErrorClass.TRANSPORT
        return None, None

    return send


def _post_signed(url: str, key: str, body: bytes) -> tuple[int | None, AlertErrorClass | None]:
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(key.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return post(
        url,
        body,
        {
            "Content-Type": "application/json",
            "X-ETL-Craft-Timestamp": timestamp,
            "X-ETL-Craft-Signature": "v1=" + signature,
        },
    )


@dataclass(frozen=True)
class Sender:
    """One delivery attempt for a channel kind, and what success looks like for it."""

    send: Callable[[], tuple[int | None, AlertErrorClass | None]]
    expected: str


@dataclass(frozen=True)
class Delivery:
    """Only the active operation holds the resolved credentials, inside its sender."""

    ctx: OperationContext
    task: TaskContext
    source: AlertEvent
    channel_name: str
    sender: Sender


def _attempts(delivery: Delivery, previous: Sequence[Row[tuple[object, ...]]]) -> HandlerResult:
    ctx, task, channel_name = delivery.ctx, delivery.task, delivery.channel_name
    last = previous[-1] if previous else None
    if last is not None and last.status == AlertStatus.FAILED:
        raise HandlerError(
            f"channel {channel_name}: recorded delivery failed; "
            "expected a new event after receiver repair"
        )
    first = 1 if last is None else last.attempt_number + (last.status != AlertStatus.STARTED)
    for number in range(first, 5):
        if number > 1 and (ctx.shutdown or threading.Event()).wait(RETRY_DELAYS[number - 2]):
            raise HandlerError(
                f"channel {channel_name}: delivery stopped; resume the recorded alert run"
            )
        _record(delivery, AlertStatus.STARTED, DeliveryAttempt(number, task.task_run_id))
        code, error = delivery.sender.send()
        sent = error is None and (code is None or 200 <= code < 300)
        retry = error is not None or code in (408, 429) or (code is not None and code >= 500)
        status = (
            AlertStatus.SENT
            if sent
            else AlertStatus.RETRY
            if retry and number < 4
            else AlertStatus.FAILED
        )
        _record(delivery, status, DeliveryAttempt(number, task.task_run_id, code, error))
        if sent:
            return HandlerResult(variables={"ALERT_SENT": True})
        logger.error(
            "channel %s: delivery attempt %d status=%s HTTP=%s; inspect the alert run",
            channel_name,
            number,
            status,
            code,
        )
        if status == AlertStatus.FAILED:
            break
    raise HandlerError(
        f"channel {channel_name}: delivery failed; expected {delivery.sender.expected}; "
        "repair the receiver and submit a new alert event"
    )


def _record(delivery: Delivery, status: AlertStatus, attempt: DeliveryAttempt) -> None:
    task, ctx = delivery.task, delivery.ctx
    with ctx.engine.begin() as conn:
        if ctx.role == ApiRole.AGENT:
            from etl_craft.services.operations.task_secrets import require_live

            require_live(conn, ctx)
        if task.attempt_id is not None:
            found = conn.execute(
                statement(conn, "alert_attempt_fence"),
                {
                    "attempt_id": task.attempt_id,
                    "task_run_id": task.task_run_id,
                    "owner": task.owner,
                    "now": datetime.now(UTC),
                },
            ).one_or_none()
            if found is None:
                raise StaleTransitionError(
                    f"alert attempt {task.attempt_id}: claim is not live; expected its current "
                    "owner and lease; stop this task and reconcile before retrying"
                )
        append(conn, task.pipeline_run_id, delivery.source, status, attempt)
