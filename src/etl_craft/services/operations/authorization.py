"""One access decision for every action: what the principal holds, and the action's rule.

Every binding gives a set of actions: a built-in CAN_* role's stored actions, a custom role's, or
one named action. They apply at the deployment, an environment type, a project, or one of its
pipelines or tags, and they only add: a pipeline or tag binding raises access on that pipeline and
never hides it from anyone. The account role adds the deployment-wide actions up to its level and,
on a project the account can see, the project and run-level actions up to its level.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import Connection, Row

from etl_craft.core.enums import ActionName, ActionScope, ApiRole, YesNo
from etl_craft.core.enums_access import Permission
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import read_tags, selected_project
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.permissions import has_role, project_not_found, require_project
from etl_craft.services.operations.requests import BulkControlRequest

PROJECT_MANAGE_ACTIONS = frozenset(
    {
        ActionName.RENAME,
        ActionName.CONFIG_PLAN,
        ActionName.PIPELINE_REFRESH,
        ActionName.MIGRATE,
        ActionName.DEPLOY,
        ActionName.GENERATE_DOCS,
    }
)
"""Project actions only a binding gives (CAN_MANAGE or a custom role), never the account role."""

EVERY_PIPELINE = frozenset({ActionName.RECONCILE, ActionName.LINEAGE_REFRESH})
"""Project-wide run actions that need the action on every pipeline of the project."""


@dataclass(frozen=True)
class Held:
    """The actions one principal holds, from one read of its bindings."""

    deployment: frozenset[str] = frozenset()
    project: frozenset[str] = frozenset()
    pipelines: dict[str, frozenset[str]] = field(default_factory=dict)
    rows: tuple[Row[Any], ...] = ()

    def on(self, code: str) -> frozenset[str]:
        """Return the actions held on one pipeline: project-wide, its own and its tags'."""
        return self.project | self.pipelines.get(code, frozenset())

    def reaches(self, code: str) -> bool:
        """Whether any binding reaches the pipeline, which is what makes it visible."""
        return bool(self.on(code))


def held(conn: Connection, ctx: OperationContext, project_id: int | None) -> Held:
    """Read what the principal holds deployment-wide and, given ``project_id``, in that project."""
    if ctx.role in (None, ApiRole.AGENT):
        return Held()
    with selected_project(project_id):
        rows = tuple(
            conn.execute(
                statement(conn, "deployment_access_held" if project_id is None else "access_held"),
                {
                    "account": ctx.actor.name,
                    "role": ctx.role,
                    "sso_group_ids": json.dumps(ctx.sso_group_ids),
                },
            ).all()
        )
    deployment = {r.action_name for r in rows if r.project_id is None and r.environment is None}
    if project_id is None:
        return Held(frozenset(deployment), rows=rows)
    tags = pipeline_tags(conn, project_id)
    project: set[str] = set()
    pipelines: dict[str, set[str]] = {}
    for r in rows:
        if r.pipeline_code is None and r.tag is None:
            project.add(r.action_name)
        elif r.pipeline_code is not None:
            pipelines.setdefault(r.pipeline_code, set()).add(r.action_name)
        else:
            for code, labels in tags.items():
                if r.tag in labels:
                    pipelines.setdefault(code, set()).add(r.action_name)
    return Held(
        frozenset(deployment),
        frozenset(project),
        {code: frozenset(names) for code, names in pipelines.items()},
        rows,
    )


def pipeline_tags(conn: Connection, project_id: int | None) -> dict[str, tuple[str, ...]]:
    """Each active pipeline's tags in the project."""
    if project_id is None:
        return {}
    with selected_project(project_id):
        return {
            row.pipeline_code: tuple(read_tags(row.pipeline_parameters, row.pipeline_code))
            for row in conn.execute(statement(conn, "permission_pipelines"))
            if row.active_flag == YesNo.YES
        }


def authorize(
    ctx: OperationContext, action: Action, request: object, required: ApiRole | None
) -> None:
    """Allow the request, or refuse it.

    ``ResourceNotFoundError`` refuses what the account cannot see; ``PermissionDeniedError``
    what it sees but may not do.
    """
    if ApiRole.AGENT in {ctx.role, required}:
        require_role(ctx, action, required)
        return
    if ctx.role == ApiRole.ADMIN or (action.provisioning and ctx.provisioning):
        return
    from etl_craft.services.operations import access

    wide = isinstance(request, access.AccessFilter) and request.reaches_beyond_project
    scoped = action.scope != ActionScope.DEPLOYMENT or isinstance(request, access.AccessFilter)
    with ctx.engine.connect() as conn:
        if not scoped or wide:
            if has_role(ctx.role, required) or action.name in held(conn, ctx, None).deployment:
                return
            require_role(ctx, action, required)
        found = held(conn, ctx, ctx.project_id)
        _require_visible_project(conn, ctx, action, found)
        if action.name in PROJECT_MANAGE_ACTIONS:
            # Escalated to admin, only the account role allows it; otherwise a binding does.
            if required == ApiRole.ADMIN:
                require_role(ctx, action, required)
            if action.name not in found.project:
                require_project(conn, ctx, needed=Permission.CAN_MANAGE)
            return
        if (
            action.scope == ActionScope.PIPELINE
            and required is not None
            and _pipeline_rule(conn, ctx, action, request, required, found)
        ):
            return
        if action.name in found.project:
            return
        require_role(ctx, action, required)


def _require_visible_project(
    conn: Connection, ctx: OperationContext, action: Action, found: Held
) -> None:
    """Mask a project the account cannot see, unless a binding there holds the action."""
    try:
        require_project(conn, ctx)
    except ResourceNotFoundError:
        if action.name not in found.project:
            raise project_not_found(ctx.project) from None


def _pipeline_rule(
    conn: Connection,
    ctx: OperationContext,
    action: Action,
    request: object,
    required: ApiRole,
    found: Held,
) -> bool:
    """Decide a run-level action from the pipelines it names; False defers to project bindings."""
    from etl_craft.services.operations.requests import ReconcileInput

    if isinstance(request, ReconcileInput) and request.attest_ended:
        # Attesting that an attempt ended needs the account role; no binding gives it.
        require_role(ctx, action, required)
        return True
    name = str(action.name)
    if action.name == ActionName.LINEAGE_REFRESH:
        require_role(ctx, action, required)
    if isinstance(request, BulkControlRequest) and has_role(ctx.role, required):
        return True
    codes = request_codes(conn, action, request)
    for code in codes:
        require_on(ctx, found, code, action, required)
    if codes:
        return True
    if action.name in EVERY_PIPELINE:
        project_pipelines = pipeline_tags(conn, ctx.project_id)
        # Lineage refresh needs every pipeline visible; reconcile needs the action on each.
        if any(
            not found.reaches(code)
            if action.name == ActionName.LINEAGE_REFRESH
            else name not in found.on(code)
            for code in project_pipelines
        ):
            raise PermissionDeniedError(
                f"account {ctx.actor.name!r}: {action.name} needs the action on every pipeline "
                f"in project {ctx.project!r}; ask its project manager for the required "
                "permission or select an accessible pipeline"
            )
        if project_pipelines:
            return True
    return required == ApiRole.VIEWER and ctx.role is not None


def require_on(
    ctx: OperationContext, found: Held, code: str, action: Action, required: ApiRole
) -> None:
    """Refuse without revealing a pipeline the account cannot see."""
    if not found.reaches(code):
        raise ResourceNotFoundError(
            f"pipeline {code!r} is missing or not permitted; select an accessible pipeline "
            "or ask a project manager for access"
        )
    if str(action.name) not in found.on(code):
        raise PermissionDeniedError(
            f"account {ctx.actor.name!r}: pipeline {code!r}: action '{action.name}' needs "
            f"{required} role or a binding that includes it; none applies here; ask an "
            "administrator or CAN_MANAGE holder for permission on this pipeline, its tag or the "
            "project"
        )


def require_role(ctx: OperationContext, action: Action, required: ApiRole | None) -> None:
    """Refuse both insufficient account roles and a different credential protocol."""
    if not has_role(ctx.role, required):
        raise PermissionDeniedError(
            f"account {ctx.actor.name!r}: role={ctx.role or 'unproven'}; action '{action.name}': "
            f"{required} role is required; ask an administrator to grant {required} or a higher "
            "role"
        )


def request_codes(conn: Connection, action: Action, request: object) -> list[str]:
    """Resolve exact identities, and the requested child rather than an implicit parent run."""
    from etl_craft.engine.repository.tasks import fetch_admitted_parameters
    from etl_craft.services.operations import triggers
    from etl_craft.services.trigger_validation import trigger_definition

    if isinstance(request, BulkControlRequest):
        return list(
            dict.fromkeys(
                code
                for selected in request.requests
                for code in request_codes(conn, action, selected)
            )
        )
    if isinstance(request, triggers.TriggerRequest):
        row = conn.execute(
            statement(conn, "trigger_context"), {"task_run_id": request.task_run_id}
        ).one_or_none()
        if row is None:
            return []
        child = trigger_definition(
            conn, row.pipeline_id, fetch_admitted_parameters(conn, row.task_id, row.pipeline_run_id)
        )
        return [child.pipeline_code]
    code = getattr(request, "pipeline_code", None)
    if code is not None:
        return [code]
    identities = {
        key: getattr(request, key, None)
        for key in ("run_id", "attempt_id", "control_id", "task_run_id")
    }
    if any(value is not None for value in identities.values()):
        return list(conn.execute(statement(conn, "permission_scope"), identities).scalars())
    return []


def allows(
    ctx: OperationContext, name: ActionName, request: object, *, conn: Connection | None = None
) -> bool:
    """Whether a binding gives the action on everything the request names.

    Operations ask this when they recheck a narrower scope than admission did, such as each
    pipeline a project-wide request touches.
    """
    from etl_craft.services.operations.actions import ACTIONS

    action = ACTIONS[name]
    if ctx.role in (None, ApiRole.AGENT):
        return False
    with nullcontext(conn) if conn is not None else ctx.engine.connect() as conn:
        if action.scope == ActionScope.DEPLOYMENT:
            return str(name) in held(conn, ctx, None).deployment
        if ctx.project_id is None:
            return False
        found = held(conn, ctx, ctx.project_id)
        codes = request_codes(conn, action, request)
        if not codes:
            return str(name) in found.project
        return all(str(name) in found.on(code) for code in codes)


def held_anywhere(ctx: OperationContext, names: frozenset[ActionName]) -> frozenset[ActionName]:
    """Return the actions the caller could be allowed somewhere in its project.

    The account role reaches them, or a binding holds them deployment-wide, project-wide or on
    any pipeline. Interfaces use it to offer only commands that can succeed.
    """
    from etl_craft.services.operations.actions import ACTIONS

    if ctx.role == ApiRole.ADMIN:
        return names
    with ctx.engine.connect() as conn:
        found = held(conn, ctx, ctx.project_id)
    anywhere = found.deployment | found.project
    for actions in found.pipelines.values():
        anywhere |= actions
    return frozenset(
        name for name in names if has_role(ctx.role, ACTIONS[name].role) or str(name) in anywhere
    )
