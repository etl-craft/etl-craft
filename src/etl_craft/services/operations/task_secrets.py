"""Resolve task credentials only while the current claim is fenced and authorized."""

from sqlalchemy.engine import Connection

from etl_craft.config.remote import LOCAL_HOSTS
from etl_craft.core.enums import Handler, HttpScheme, Transport
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.core.task_secrets import declared
from etl_craft.engine.agent_state import fence
from etl_craft.engine.queries import statement
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.task_secrets import resolve
from etl_craft.services.operations.context import OperationContext


def for_claim(ctx: OperationContext, task: TaskContext) -> dict[str, str]:
    """Refuse stale claims and insecure peers before resolving any provider value."""
    if task.handler == Handler.EMAIL_ALERT and task.task_params.get("ALERT_CHANNEL"):
        return {}
    names = declared(task.task_params, f"{task.pipeline_code}.{task.task_code}")
    if not names:
        return {}
    if (
        ctx.transport == Transport.HTTP
        and ctx.client_scheme != HttpScheme.HTTPS
        and ctx.client_address not in LOCAL_HOSTS
    ):
        raise PermissionDeniedError(
            f"{task.pipeline_code}.{task.task_code}: task secrets require HTTPS; "
            "plain HTTP is allowed only for localhost; configure the agent's HTTPS API URL"
        )
    assert task.attempt_id is not None
    with ctx.engine.begin() as conn:
        fence(conn, task.attempt_id, str(ctx.credential_token_id))
        require_live(conn, ctx)
        values = resolve(task)
        fence(conn, task.attempt_id, str(ctx.credential_token_id))
        require_live(conn, ctx)
        return values


def require_live(conn: Connection, ctx: OperationContext) -> None:
    """Refuse a revoked agent before resolving or using server-owned credentials."""
    agent = conn.execute(
        statement(conn, "agent_get"), {"agent_id": ctx.credential_token_id}
    ).one_or_none()
    if agent is None or not agent.credential_live:
        raise PermissionDeniedError(
            f"agent {ctx.credential_token_id}: task secrets require a live credential; "
            "stop the child and issue a valid agent token"
        )
