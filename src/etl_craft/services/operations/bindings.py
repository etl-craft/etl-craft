"""Custom-role and single-action bindings: the additive half of every authorization decision.

An action is allowed when the account role and built-in CAN_* grants allow it (the existing
check), or when a binding of the account, one of its groups or its role audience gives it the
action, through a custom role or by name, on the deployment, the project's environment type, the
project, or every pipeline the request names (directly or through one of its tags).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from sqlalchemy.engine import Connection, Row

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ActionScope, ApiRole, YesNo
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import read_tags
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import Request

Check = Callable[[OperationContext, Action, Any, ApiRole | None], None]
Codes = Callable[[Connection, Action, Any], list[str]]
_SHARED: dict[str, Any] = {}


def authorize(
    ctx: OperationContext,
    action: Action,
    request: object,
    required: ApiRole | None,
    check: Check,
    codes: Codes,
) -> None:
    """Allow when the existing check or any custom binding allows; otherwise keep its refusal.

    Every action is admitted here before it runs, so the action table's own check and pipeline
    resolution are kept for ``explain``, which evaluates them for another account.
    """
    _SHARED.update(check=check, codes=codes)
    try:
        _SHARED["check"](ctx, action, request, required)
    except (PermissionDeniedError, ResourceNotFoundError):
        if not covering(ctx, action, request):
            raise


def covering(ctx: OperationContext, action: Action, request: object) -> tuple[Row[Any], ...]:
    """Return the custom bindings that allow this request, or nothing."""
    if ctx.role in (None, ApiRole.AGENT) or action.role in (None, ApiRole.AGENT):
        return ()
    deployment = action.scope == ActionScope.DEPLOYMENT
    if not deployment and ctx.project_id is None:
        return ()
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            statement(conn, "access_allowed"),
            {
                "project_id": None if deployment else ctx.project_id,
                "account": ctx.actor.name,
                "role": ctx.role,
                "sso_group_ids": _groups(ctx),
                "action": str(action.name),
            },
        ).all()
        if deployment:
            return tuple(r for r in rows if r.project_id is None and r.environment is None)
        codes = _SHARED["codes"](conn, action, request)
        whole = tuple(r for r in rows if r.pipeline_code is None and r.tag is None)
        if not codes:
            return whole
        tags = _tags(conn, ctx.project_id)
        found: list[Row[Any]] = []
        for code in codes:
            match = whole or tuple(
                r
                for r in rows
                if r.pipeline_code == code or (r.tag and r.tag in tags.get(code, ()))
            )
            if not match:
                return ()
            found.extend(match)
        return tuple(dict.fromkeys(found))


def _groups(ctx: OperationContext) -> str:
    import json

    return json.dumps(ctx.sso_group_ids)


def _tags(conn: Connection, project_id: int | None) -> dict[str, tuple[str, ...]]:
    return {
        row.pipeline_code: tuple(read_tags(row.pipeline_parameters, row.pipeline_code))
        for row in conn.execute(statement(conn, "permission_pipelines"), {"project_id": project_id})
        if row.active_flag == YesNo.YES
    }


@dataclass(frozen=True, kw_only=True)
class ExplainInput(Request):
    """Why one account may or may not run one action, optionally on one pipeline."""

    account: str
    action: str
    project: str | None = None
    pipeline: str | None = None


@dataclass(frozen=True)
class Explanation:
    """The decision, what allows it, or why it is refused and what would allow it."""

    SCHEMA: ClassVar[str] = "etl-craft/access-explain/1"
    account: str
    action: str
    project: str | None
    pipeline: str | None
    allowed: bool
    allowed_by: tuple[str, ...]
    refusal: str | None
    roles_with_action: tuple[str, ...]


def explain(ctx: OperationContext, request: ExplainInput) -> Explanation:
    """Evaluate the same check the account's own request would meet, without running it."""
    from etl_craft.services.operations.actions import ACTIONS
    from etl_craft.services.operations.roles import role_actions

    try:
        name = ActionName(request.action.strip())
    except ValueError:
        raise UsageError(
            f"action {request.action!r}: not a known etl-craft action; expected a command name "
            "such as 'run'; correct --action"
        ) from None
    action = ACTIONS[name]
    target = _account_context(ctx, request)
    probe = _probe(action, request)
    with ctx.engine.connect() as conn:
        holders = tuple(
            role for role, actions in sorted(role_actions(conn).items()) if str(name) in actions
        )
    allowed_by: tuple[str, ...] = ()
    refusal = None
    try:
        _SHARED["check"](target, action, probe, action.required_role(target, probe))
        allowed_by = (f"account role {target.role} or a built-in CAN_* grant",)
    except (PermissionDeniedError, ResourceNotFoundError) as error:
        rows = covering(target, action, probe)
        allowed_by = tuple(
            f"binding {r.binding_id}: {r.granted} to {r.principal} on {_where(r)}" for r in rows
        )
        refusal = None if rows else str(error)
    return Explanation(
        request.account,
        str(name),
        request.project,
        request.pipeline,
        refusal is None,
        allowed_by,
        refusal,
        holders,
    )


def _account_context(ctx: OperationContext, request: ExplainInput) -> OperationContext:
    with ctx.engine.connect() as conn:
        accounts = {row.name: row for row in conn.execute(statement(conn, "account_list"))}
        project_id = None
        if request.project is not None:
            row = conn.execute(
                statement(conn, "project_by_code"), {"code": request.project}
            ).one_or_none()
            if row is None:
                raise UsageError(
                    f"project {request.project!r}: not found; expected an existing project; "
                    "correct --project"
                )
            project_id = int(row.project_id)
    account = accounts.get(request.account)
    if account is None or account.active_flag != YesNo.YES:
        raise UsageError(
            f"account {request.account!r}: expected an active account; use `etl-craft account list`"
        )
    return replace(
        ctx,
        actor=Actor(request.account, ActorKind(account.kind)),
        role=ApiRole(account.role),
        sso_group_ids=(),
        project=request.project or ctx.project,
        project_id=project_id,
    )


def _probe(action: Action, request: ExplainInput) -> object:
    """Build the narrowest request of the action's own type that names the pipeline."""
    fields = getattr(action.request, "__dataclass_fields__", {})
    values: dict[str, object] = {}
    if request.pipeline is not None and "pipeline_code" in fields:
        values["pipeline_code"] = request.pipeline
    try:
        return action.request(**values)
    except (TypeError, UsageError):
        raise UsageError(
            f"action {action.name!r}: explain builds the request from --pipeline-code alone, "
            "and this action needs more inputs; run the command itself to see its decision"
        ) from None


def _where(row: Row[Any]) -> str:
    if row.pipeline_code:
        return f"pipeline {row.pipeline_code}"
    if row.tag:
        return f"tag {row.tag}"
    if row.project_id is not None:
        return "the project"
    return f"environment {row.environment}" if row.environment else "the deployment"
