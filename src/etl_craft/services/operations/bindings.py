"""Explain one account's access decision for one action, from the shared evaluator."""

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, ClassVar

from sqlalchemy.engine import Row

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole, YesNo
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.engine.queries import statement
from etl_craft.services.operations import authorization
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import Request


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
    from etl_craft.services.operations.actions import ACTIONS, authorize_identity
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
        active = {
            row.name
            for row in conn.execute(statement(conn, "role_list"))
            if row.active_flag == YesNo.YES
        }
        holders = tuple(
            role
            for role, actions in sorted(role_actions(conn).items())
            if role in active and str(name) in actions
        )
    try:
        authorize_identity(target, action, probe)
        authorization.authorize(target, action, probe, action.required_role(target, probe))
        if name in {ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE}:
            from etl_craft.services.operations.access import authorize
            from etl_craft.services.operations.access_inputs import Resolved
            from etl_craft.services.operations.access_models import AccessWrite

            binding = AccessWrite(
                project=request.project, pipeline=request.pipeline, reason="explain"
            )
            with ctx.engine.connect() as conn:
                authorize(conn, target, Resolved(binding, target.project_id, None, None))
    except (PermissionDeniedError, ResourceNotFoundError) as error:
        return Explanation(
            request.account, str(name), request.project, request.pipeline, False, (),
            str(error), holders,
        )  # fmt: skip
    return Explanation(
        request.account,
        str(name),
        request.project,
        request.pipeline,
        True,
        _allowed_by(target, action, request.pipeline),
        None,
        holders,
    )


def _allowed_by(ctx: OperationContext, action: Action, pipeline: str | None) -> tuple[str, ...]:
    """Name the bindings that hold the action where it was asked, or the account role."""
    with ctx.engine.connect() as conn:
        found = authorization.held(conn, ctx, ctx.project_id)
        tags = authorization.pipeline_tags(conn, ctx.project_id) if pipeline else {}
    labels = tags.get(pipeline, ()) if pipeline else ()
    rows = [
        r
        for r in found.rows
        if r.action_name == str(action.name)
        and (
            (r.pipeline_code is None and r.tag is None)
            or (pipeline is not None and r.pipeline_code == pipeline)
            or r.tag in labels
        )
    ]
    return tuple(
        f"binding {r.binding_id}: {r.granted} to {r.principal} on {_where(r)}" for r in rows
    ) or (f"account role {ctx.role}",)


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
        if action.escalate is None:
            return SimpleNamespace(pipeline_code=request.pipeline)
        raise UsageError(
            f"action {action.name!r}: explain builds the request from --pipeline alone, "
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
