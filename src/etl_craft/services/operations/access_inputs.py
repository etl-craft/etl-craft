"""Resolve one submitted binding against current projects, principals, roles and pipelines."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Connection

from etl_craft.core.enums import ActionName, ApiRole, YesNo
from etl_craft.core.enums_access import AccessIntent, EnvironmentType, Permission
from etl_craft.core.errors import UsageError
from etl_craft.core.tags import valid_tag
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import read_tags
from etl_craft.services.operations.access_models import AccessWrite

AUDIENCES = (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER)
BUILT_IN = frozenset(Permission)


@dataclass(frozen=True)
class Resolved:
    """A valid binding with its current identities, written in the transaction that checked it."""

    request: AccessWrite
    project_id: int | None
    group_id: int | None
    account_id: int | None

    @property
    def scope(self) -> str:
        """DEPLOYMENT, ENVIRONMENT or PROJECT: how far the binding reaches."""
        if self.request.deployment:
            return "DEPLOYMENT"
        return "ENVIRONMENT" if self.request.environment else "PROJECT"

    @property
    def built_in(self) -> bool:
        """A built-in CAN_* level, one per principal at each exact scope."""
        return self.request.action is None and (
            self.request.role is None or self.request.role in BUILT_IN
        )


def project(conn: Connection, code: str | None) -> int:
    """Resolve an active project without guessing a namespace."""
    if not code:
        raise UsageError("project is missing; expected an explicit scope; supply --project P")
    row = conn.execute(statement(conn, "project_by_code"), {"code": code}).one_or_none()
    if row is None or row.active_flag != YesNo.YES:
        raise UsageError(
            f"project {code!r}: expected an active project; select an existing project"
        )
    return int(row.project_id)


def resolve(conn: Connection, request: AccessWrite, intent: AccessIntent) -> Resolved:
    """Name every invalid part of the binding at once, or return its resolved identities."""
    bad = scope_problems(request)
    project_id = None
    if not bad and not request.reaches_beyond_project:
        try:
            project_id = project(conn, request.project)
        except UsageError as error:
            bad.append(str(error))
    groups = {
        row.name: int(row.group_id)
        for row in conn.execute(statement(conn, "group_list"))
        if row.active_flag == YesNo.YES
    }
    accounts = {row.name: row for row in conn.execute(statement(conn, "account_list"))}
    bad.extend(principal_problems(request, groups, accounts))
    bad.extend(grant_problems(conn, request, intent))
    if project_id is not None:
        bad.extend(target_problems(conn, request, project_id))
    elif request.pipeline or request.tag:
        bad.append("a pipeline or tag narrows a project; add --project or remove it")
    if bad:
        raise UsageError("access: " + "; ".join(bad))
    account = accounts.get(request.account or "")
    return Resolved(
        request,
        project_id,
        groups.get(request.group or ""),
        None if account is None else int(account.account_id),
    )


def scope_problems(request: AccessWrite) -> list[str]:
    """Require exactly one reach: the deployment, one environment type, or one project."""
    chosen = [
        name
        for name, given in (
            ("--deployment", request.deployment),
            ("--environment", request.environment),
            ("--project", request.project),
        )
        if given
    ]
    if len(chosen) != 1:
        return [
            f"scope {chosen or 'none'}; expected exactly one of --deployment, --environment or "
            "--project; choose where the binding applies"
        ]
    if request.environment and request.environment not in tuple(EnvironmentType):
        return [
            f"environment {request.environment!r}; expected one of "
            f"{', '.join(EnvironmentType)}; correct --environment"
        ]
    if request.pipeline and request.tag:
        return ["a binding narrows to a pipeline or a tag, not both; choose one"]
    return []


def principal_problems(
    request: AccessWrite, groups: dict[str, int], accounts: dict[str, Any]
) -> list[str]:
    """Require exactly one active account, active group or supported audience."""
    given = [p for p in (request.group, request.account, request.audience) if p]
    if len(given) != 1:
        return ["expected exactly one of --account, --group or --audience; choose who"]
    if request.group and request.group not in groups:
        remedy = (
            "use --account for an account"
            if request.group in accounts
            else "use `etl-craft group list` or `group add`"
        )
        return [f"group {request.group!r}: expected an active group; {remedy}"]
    account = accounts.get(request.account or "")
    if request.account and (account is None or account.active_flag != YesNo.YES):
        return [f"account {request.account!r}: expected an active account; use account list"]
    if request.audience and request.audience not in AUDIENCES:
        return [
            f"audience {request.audience!r}: expected viewer, operator or developer; "
            "choose a supported audience"
        ]
    return []


def grant_problems(conn: Connection, request: AccessWrite, intent: AccessIntent) -> list[str]:
    """Require one existing role or one bindable action that fits the binding's reach."""
    from etl_craft.services.operations.roles import bindable, deployment_only, role_actions

    role, command = request.role, request.action
    if role and command:
        return ["expected --role or --action, not both; choose what the binding gives"]
    if not role and not command:
        if intent == AccessIntent.REVOKE:
            return []
        return ["expected --role or --action; choose what the binding gives"]
    try:
        if command:
            actions: tuple[str, ...] = (bindable(command),)
        else:
            known = role_actions(conn)
            if role not in known:
                return [f"role {role!r}: not an active role; use `etl-craft role list`"]
            actions = () if role in BUILT_IN else known[str(role)]
    except UsageError as error:
        return [str(error)]
    wide = sorted(a for a in actions if deployment_only(ActionName(a)))
    if wide and not request.deployment:
        return [f"{role or command}: {wide} act on the whole deployment; bind it with --deployment"]
    return []


def target_problems(conn: Connection, request: AccessWrite, project_id: int) -> list[str]:
    """Require current pipeline identities and existing, syntactically valid tags."""
    active = [
        row
        for row in conn.execute(statement(conn, "permission_pipelines"), {"project_id": project_id})
        if row.active_flag == YesNo.YES
    ]
    tags = {tag for row in active for tag in read_tags(row.pipeline_parameters, row.pipeline_code)}
    if request.pipeline and request.pipeline not in {row.pipeline_code for row in active}:
        return [
            f"pipeline {request.pipeline!r}: expected an active pipeline in "
            f"{request.project!r}; check the project"
        ]
    if request.tag and (not valid_tag(request.tag) or request.tag not in tags):
        return [
            f"tag {request.tag!r}: expected a tag on an active pipeline in "
            f"{request.project!r}; fix the tag"
        ]
    return []
