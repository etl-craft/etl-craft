"""Project alert routing: email recipients or HTTPS secret references, owned by administrators."""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.alerts import AlertKind, AlertTrigger, triggers
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import HandlerError, PermissionDeniedError, UsageError
from etl_craft.core.text import is_env_name, is_metadata_code
from etl_craft.engine import locks
from etl_craft.engine.alert_channels import AlertChannel
from etl_craft.engine.queries import statement
from etl_craft.handlers.mail import parse_recipients
from etl_craft.services.operations.access_inputs import project
from etl_craft.services.operations.admin_metadata import reason
from etl_craft.services.operations.authorization import allows
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import Request


@dataclass(frozen=True, kw_only=True)
class ChannelIdentity(Request):
    """An explicitly selected project; no credential values are accepted."""

    project: str
    name: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChannelWrite(ChannelIdentity):
    """Full administrator-owned channel definition, also used to reactivate a channel.

    An EMAIL channel names its recipients; a WEBHOOK or SLACK channel names the variables that
    hold its URL and signing key.
    """

    reason: str
    kind: AlertKind
    url_secret: str | None = None
    signing_secret: str | None = None
    recipients: str | None = None
    default_alert_on: str = AlertTrigger.FAILURE


@dataclass(frozen=True, kw_only=True)
class ChannelDisable(ChannelIdentity):
    """Retire routing while retaining its identity and delivery history."""

    reason: str


@dataclass(frozen=True)
class Channels:
    """Channel reference names for an authorized deployment actor."""

    SCHEMA: ClassVar[str] = "etl-craft/alert-channels/1"
    channels: tuple[AlertChannel, ...]


def require_admin(ctx: OperationContext, action: ActionName, request: ChannelIdentity) -> None:
    """Keep direct Python calls under the same administrative boundary as HTTP and CLI."""
    if ctx.role != ApiRole.ADMIN and not allows(ctx, action, request):
        raise PermissionDeniedError(
            f"alert channels: account {ctx.actor.name!r} role={ctx.role}; expected admin; "
            "ask a deployment administrator to manage routing and secret references"
        )


def list_channels(ctx: OperationContext, request: ChannelIdentity) -> Channels:
    """List reference names, never resolved values."""
    require_admin(ctx, ActionName.ALERT_CHANNEL_LIST, request)
    with ctx.engine.connect() as conn:
        identity = project(conn, request.project)
        rows = conn.execute(statement(conn, "alert_channels_list"), {"project_id": identity})
        return Channels(
            tuple(
                AlertChannel(**r._mapping)
                for r in rows
                if request.name is None or r.channel_name == request.name
            )
        )


def set_channel(ctx: OperationContext, request: ChannelWrite) -> Channels:
    """Create or replace an approved routing definition under the metadata lock."""
    require_admin(ctx, ActionName.ALERT_CHANNEL_SET, request)
    reason(request.reason)
    if request.name is None or not is_metadata_code(request.name):
        raise UsageError(
            f"channel {request.name!r}: expected a metadata code; supply --name with letters, "
            "digits or underscores beginning with a letter"
        )
    if request.kind not in tuple(AlertKind):
        raise UsageError(
            f"channel {request.name}: kind={request.kind!r}; expected "
            f"{', '.join(AlertKind)}; supply --kind with a supported kind"
        )
    _check_routing(request)
    triggers(request.default_alert_on)
    with locks.MIGRATE.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        identity = project(conn, request.project)
        old = conn.execute(
            statement(conn, "alert_channel"),
            {
                "project_id": identity,
                "channel_name": request.name,
            },
        ).first()
        conn.execute(
            statement(conn, "alert_channel_add" if old is None else "alert_channel_set"),
            {
                "project_id": identity,
                "name": request.name,
                "kind": request.kind,
                "url_secret": request.url_secret or None,
                "signing_secret": request.signing_secret or None,
                "recipients": request.recipients or None,
                "default_alert_on": request.default_alert_on,
            },
        )
    return list_channels(ctx, request)


def _check_routing(request: ChannelWrite) -> None:
    """Refuse a definition missing its kind's routing or carrying another kind's."""
    if request.kind == AlertKind.EMAIL:
        if request.url_secret or request.signing_secret:
            raise UsageError(
                f"channel {request.name}: kind=EMAIL with --url-secret or --signing-secret; "
                "expected only --recipients; drop the secret variables"
            )
        try:
            parse_recipients(request.recipients, f"channel {request.name} --recipients")
        except HandlerError as error:
            raise UsageError(str(error)) from None
        return
    if request.recipients:
        raise UsageError(
            f"channel {request.name}: kind={request.kind} with --recipients; expected "
            "--url-secret and --signing-secret; drop --recipients or use --kind EMAIL"
        )
    for field, name in (
        ("URL_SECRET", request.url_secret),
        ("SIGNING_SECRET", request.signing_secret),
    ):
        if not name or not is_env_name(name):
            # The value is never echoed: a mistyped one may be the secret itself.
            raise UsageError(
                f"channel {request.name}: {field} is missing or not a variable name; expected a "
                "secret reference; store its value in the secret source and supply the variable "
                "name"
            )


def disable_channel(ctx: OperationContext, request: ChannelDisable) -> Channels:
    """Disable future admission and delivery without removing the retained channel."""
    require_admin(ctx, ActionName.ALERT_CHANNEL_DISABLE, request)
    reason(request.reason)
    with locks.MIGRATE.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        identity = project(conn, request.project)
        found = conn.execute(
            statement(conn, "alert_channel_disable"),
            {
                "project_id": identity,
                "name": request.name,
            },
        ).first()
        if found is None:
            raise UsageError(
                f"channel {request.name!r} in project {request.project!r}: missing; "
                "expected an existing channel; use alert-channel list"
            )
    return list_channels(ctx, request)
