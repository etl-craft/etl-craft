"""Administrator-owned routing and secret references, independent of project configuration."""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.alerts import AlertKind, AlertTrigger, triggers
from etl_craft.core.enums import ApiRole
from etl_craft.core.enums_alerts import AlertBodyFormat
from etl_craft.core.errors import PermissionDeniedError, UsageError
from etl_craft.core.text import is_env_name, is_metadata_code
from etl_craft.engine import locks
from etl_craft.engine.alert_channels import AlertChannel
from etl_craft.engine.queries import statement
from etl_craft.services.operations.access_inputs import project
from etl_craft.services.operations.admin_metadata import reason
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import Request


@dataclass(frozen=True, kw_only=True)
class ChannelIdentity(Request):
    """An explicitly selected project; no credential values are accepted."""

    project: str
    name: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChannelWrite(ChannelIdentity):
    """Full administrator-owned channel definition, also used to reactivate a channel."""

    reason: str
    kind: AlertKind
    url_secret: str
    signing_secret: str
    default_alert_on: str = AlertTrigger.FAILURE


@dataclass(frozen=True, kw_only=True)
class ChannelDisable(ChannelIdentity):
    """Retire routing while retaining its identity and delivery history."""

    reason: str


@dataclass(frozen=True)
class Channels:
    """Only administrators may read channel reference names."""

    SCHEMA: ClassVar[str] = "etl-craft/alert-channels/1"
    channels: tuple[AlertChannel, ...]


def require_admin(ctx: OperationContext) -> None:
    """Keep direct Python calls under the same administrative boundary as HTTP and CLI."""
    if ctx.role != ApiRole.ADMIN:
        raise PermissionDeniedError(
            f"alert channels: account {ctx.actor.name!r} role={ctx.role}; expected admin; "
            "ask a deployment administrator to manage routing and secret references"
        )


def list_channels(ctx: OperationContext, request: ChannelIdentity) -> Channels:
    """List reference names, never resolved values."""
    require_admin(ctx)
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
    require_admin(ctx)
    reason(request.reason)
    if request.name is None or not is_metadata_code(request.name):
        raise UsageError(
            f"channel {request.name!r}: expected a metadata code; supply --name with letters, "
            "digits or underscores beginning with a letter"
        )
    if request.kind not in tuple(AlertKind):
        raise UsageError(
            f"channel {request.name}: kind={request.kind!r}; expected WEBHOOK or "
            "SLACK; supply --kind with a supported kind"
        )
    for field, name in (
        ("URL_SECRET", request.url_secret),
        ("SIGNING_SECRET", request.signing_secret),
    ):
        if not is_env_name(name):
            raise UsageError(
                f"channel {request.name}: {field} is not a variable name; expected a secret "
                "reference; store its value in the secret source and supply the variable name"
            )
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
                "url_secret": request.url_secret,
                "signing_secret": request.signing_secret,
                "body_format": AlertBodyFormat.JSON
                if request.kind == AlertKind.WEBHOOK
                else AlertBodyFormat.SLACK,
                "default_alert_on": request.default_alert_on,
            },
        )
    return list_channels(ctx, request)


def disable_channel(ctx: OperationContext, request: ChannelDisable) -> Channels:
    """Disable future admission and delivery without removing the retained channel."""
    require_admin(ctx)
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
