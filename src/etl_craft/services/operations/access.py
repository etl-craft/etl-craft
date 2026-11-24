"""Grant, revoke and list access bindings: WHO gets WHAT, WHERE, one binding at a time."""

from dataclasses import replace
from typing import Any

from sqlalchemy.engine import Connection, Row

from etl_craft.core.enums import ActionName, ActionOutcome, ApiRole, YesNo
from etl_craft.core.enums_access import AccessChange, AccessIntent, BindingScope, Permission
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.engine import locks
from etl_craft.engine.audit import command_request
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import read_tags
from etl_craft.services.operations.access_inputs import Resolved, project, resolve, scope_problems
from etl_craft.services.operations.access_models import AccessFilter as AccessFilter
from etl_craft.services.operations.access_models import AccessView as AccessView
from etl_craft.services.operations.access_models import AccessWrite as AccessWrite
from etl_craft.services.operations.access_models import Binding, Change
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.permissions import (
    eligible_grants,
    pipeline_access,
    project_permission,
    require_project,
    tag_permission,
)
from etl_craft.services.operations.requests import arguments


def list_access(ctx: OperationContext, request: AccessFilter) -> AccessView:
    """List the bindings that apply to a project, or that sit at one wider reach (admins)."""
    if problems := scope_problems(request):
        raise UsageError("access: " + "; ".join(problems))
    if request.reaches_beyond_project:
        return _list_wide(ctx, request)
    with ctx.engine.connect() as conn:
        project_id = project(conn, request.project)
        assert request.project is not None
        scoped = replace(ctx, project=request.project, project_id=project_id)
        require_project(conn, scoped)
        access = pipeline_access(conn, scoped)
        bindings = tuple(
            _binding(
                row,
                BindingScope(row.scope),
                row.project if row.scope == BindingScope.PROJECT else None,
            )
            for row in conn.execute(statement(conn, "access_list"), {"project": request.project})
            if _matches(request, row)
            and (
                ctx.role == ApiRole.ADMIN
                or (
                    access.permits(row.pipeline)
                    if row.pipeline
                    else tag_permission(conn, scoped, row.tag) is not None
                    if row.tag
                    else project_permission(conn, scoped) is not None
                )
            )
        )
        tagged = {
            row.pipeline_code
            for row in conn.execute(
                statement(conn, "permission_pipelines"), {"project_id": scoped.project_id}
            )
            if request.tag is None
            or request.tag in read_tags(row.pipeline_parameters, row.pipeline_code)
        }
        effective = tuple(
            (code, level, access.sources[code])
            for code, level in access.levels.items()
            if level is not None
            and code in tagged
            and (request.pipeline is None or code == request.pipeline)
        )
        level = project_permission(conn, scoped)
        sources = tuple(
            source
            for pipeline, tag, _, source in eligible_grants(conn, scoped)
            if pipeline is None and tag is None
        )
    return AccessView(
        bindings=bindings, effective=effective, project_level=level, project_sources=sources
    )


def _list_wide(ctx: OperationContext, request: AccessFilter) -> AccessView:
    if ctx.role != ApiRole.ADMIN:
        raise PermissionDeniedError(
            f"account {ctx.actor.name!r}: deployment and environment bindings are listed by "
            "deployment administrators; list one project's bindings with --project"
        )
    scope = BindingScope.DEPLOYMENT if request.deployment else BindingScope.ENVIRONMENT
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            statement(conn, "access_at_scope"),
            {"binding_project_id": None, "environment": request.environment},
        )
        return AccessView(
            bindings=tuple(_binding(row, scope, None) for row in rows if _matches(request, row))
        )


def _matches(request: AccessFilter, row: Row[Any]) -> bool:
    return (
        (request.group is None or row.group_name == request.group)
        and (request.account is None or row.account == request.account)
        and (request.audience is None or row.audience == request.audience)
        and (request.pipeline is None or row.pipeline == request.pipeline)
        and (request.tag is None or row.tag == request.tag)
    )


def _binding(row: Row[Any], scope: BindingScope, project_code: str | None) -> Binding:
    return Binding(
        scope,
        project_code,
        row.environment,
        row.group_name,
        row.account,
        row.audience,
        row.pipeline,
        row.tag,
        row.role,
        row.action,
        row.active_flag,
    )


def grant_access(ctx: OperationContext, request: AccessWrite) -> AccessView:
    """Grant one binding in one locked transaction."""
    return _write(ctx, request, AccessIntent.GRANT)


def revoke_access(ctx: OperationContext, request: AccessWrite) -> AccessView:
    """Retire one binding without deleting its history."""
    return _write(ctx, request, AccessIntent.REVOKE)


def _write(ctx: OperationContext, request: AccessWrite, intent: AccessIntent) -> AccessView:
    """Record delegated refusals after the locked check has made its final decision."""
    action = ActionName.ACCESS_GRANT if intent == AccessIntent.GRANT else ActionName.ACCESS_REVOKE
    with command_request(action, arguments(request), project_id=ctx.project_id) as audit:
        audit.engine = ctx.engine
        try:
            return _apply(ctx, request, intent)
        except (PermissionDeniedError, ResourceNotFoundError) as error:
            audit.outcome = ActionOutcome.REFUSED
            audit.exit_code = error.exit_code
            raise


def _apply(ctx: OperationContext, request: AccessWrite, intent: AccessIntent) -> AccessView:
    if not request.reason.strip():
        raise UsageError(
            "access change reason is empty; expected a reason; supply --reason explaining it"
        )
    with (
        locks.MIGRATE.hold(ctx.engine, wait_seconds=30),
        locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30),
        ctx.engine.begin() as conn,
    ):
        if problems := scope_problems(request):
            raise UsageError("access: " + "; ".join(problems))
        project_id = None if request.reaches_beyond_project else project(conn, request.project)
        authorize(conn, ctx, Resolved(request, project_id, None, None))
        resolved = resolve(conn, request, intent)
        change = publish(conn, resolved, intent)
    return AccessView(change=change, dry_run=request.dry_run)


def authorize(conn: Connection, ctx: OperationContext, resolved: Resolved) -> None:
    """Administrators bind anywhere; a CAN_MANAGE holder binds within what it manages."""
    if ctx.role == ApiRole.ADMIN:
        return
    request = resolved.request
    if resolved.project_id is None:
        raise PermissionDeniedError(
            f"account {ctx.actor.name!r}: {resolved.scope} bindings reach beyond one project; "
            "expected a deployment administrator; ask an administrator to make this binding"
        )
    scoped = replace(ctx, project=str(request.project), project_id=resolved.project_id)
    require_project(conn, scoped)
    if project_permission(conn, scoped) == Permission.CAN_MANAGE:
        return
    if request.pipeline:
        access = pipeline_access(conn, scoped)
        access.require(scoped, request.pipeline, ApiRole.VIEWER)
        level = access.levels.get(request.pipeline)
    else:
        level = (
            tag_permission(conn, scoped, request.tag)
            if request.tag
            else project_permission(conn, scoped)
        )
    if level != Permission.CAN_MANAGE:
        raise PermissionDeniedError(
            f"account {ctx.actor.name!r}: {request.pipeline or request.tag or request.project!r} "
            f"in project {request.project!r}: effective level={level or 'none'}; expected "
            "CAN_MANAGE; ask an administrator or a CAN_MANAGE holder on it"
        )


def publish(conn: Connection, resolved: Resolved, intent: AccessIntent) -> Change:
    """Diff the binding at its exact reach and write it unless this is a dry run.

    A built-in CAN_* role is the principal's one level there, so granting replaces it. A custom
    role or a single action is its own binding beside any other, granted or revoked alone.
    """
    request = resolved.request
    principal = (request.group, request.account, request.audience)
    old = next(
        (
            r
            for r in conn.execute(
                statement(conn, "access_at_scope"),
                {"binding_project_id": resolved.project_id, "environment": request.environment},
            )
            if (r.group_name, r.account, r.audience) == principal
            and (r.pipeline, r.tag) == (request.pipeline, request.tag)
            and (
                (resolved.built_in and r.action is None and r.role in tuple(Permission))
                or (not resolved.built_in and (r.role, r.action) == (request.role, request.action))
            )
        ),
        None,
    )
    active = YesNo.YES if intent == AccessIntent.GRANT else YesNo.NO
    if active == YesNo.NO and old is None:
        raise UsageError(
            "access revoke: no such binding; use `etl-craft access list` to see current bindings"
        )
    role = old.role if active == YesNo.NO and old is not None else request.role
    change = AccessChange.UNCHANGED
    if active == YesNo.YES and (old is None or old.active_flag == YesNo.NO):
        change = AccessChange.ADDED
    elif active == YesNo.NO and old is not None and old.active_flag == YesNo.YES:
        change = AccessChange.REVOKED
    elif active == YesNo.YES and old is not None and old.role != role:
        change = AccessChange.CHANGED_PERMISSION
    binding = Binding(
        resolved.scope,
        request.project if resolved.project_id is not None else None,
        request.environment,
        *principal,
        request.pipeline,
        request.tag,
        role,
        request.action,
        active,
    )
    if not request.dry_run and change != AccessChange.UNCHANGED:
        conn.execute(
            statement(conn, "access_add" if old is None else "access_set"),
            {
                "binding_project_id": resolved.project_id,
                "environment": request.environment,
                "group_id": resolved.group_id,
                "account_id": resolved.account_id,
                "grantee_role": request.audience,
                "pipeline": request.pipeline,
                "tag": request.tag,
                "permission": role,
                "action": request.action,
                "active_flag": active,
                "grant_id": None if old is None else old.grant_id,
            },
        )
    return Change(binding, None if old is None else old.role, change)
