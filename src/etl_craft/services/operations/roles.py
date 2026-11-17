"""Roles: named sets of actions that access bindings give to accounts, groups and audiences."""

from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from etl_craft.core.enums import ActionName, ActionScope, ApiRole, Placement, YesNo
from etl_craft.core.enums_access import Permission
from etl_craft.core.errors import UsageError
from etl_craft.engine import locks
from etl_craft.engine.queries import statement
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import NoInput, Request

ADMIN_ONLY_PREFIXES = ("account ", "token ", "group ", "role ", "project ")
"""Identity, access and project administration stay with deployment administrators."""
ADMIN_ONLY = frozenset({ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE})


@dataclass(frozen=True)
class Role:
    """A role and the actions it allows; built-in roles list their derived actions."""

    name: str
    description: str | None
    built_in: bool
    active_flag: YesNo
    actions: tuple[str, ...]


@dataclass(frozen=True)
class Roles:
    """Role administration results."""

    SCHEMA: ClassVar[str] = "etl-craft/roles/1"
    roles: tuple[Role, ...]


@dataclass(frozen=True, kw_only=True)
class RoleName(Request):
    """One role by its stable name."""

    name: str

    def __post_init__(self) -> None:
        """Keep names short, printable and distinct from action names."""
        if not self.name.strip() or len(self.name) > 64 or " " in self.name.strip():
            raise UsageError(
                f"role {self.name!r}: expected 1 to 64 characters without spaces; "
                "choose a name such as data-analyst"
            )


@dataclass(frozen=True, kw_only=True)
class RoleCreate(RoleName):
    """A new custom role with its first actions."""

    description: str | None = None
    actions: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RoleAction(RoleName):
    """One action added to or removed from a custom role."""

    action: str


def bindable(name: str) -> ActionName:
    """Resolve an action a custom role or binding may hold, naming the remedy when it may not."""
    from etl_craft.services.operations.actions import ACTIONS

    try:
        action = ActionName(name.strip())
    except ValueError:
        raise UsageError(
            f"action {name!r}: not a known etl-craft action; expected a command name such as "
            "'run' or 'pool set'; list them with `etl-craft role describe CAN_MANAGE` "
            "or the action table in the docs"
        ) from None
    spec = ACTIONS[action]
    if spec.role in (None, ApiRole.AGENT) or spec.placement == Placement.CONTROLLER_HOST:
        raise UsageError(
            f"action {action!r}: runs only for agents, at sign-in or on the controller host; "
            "expected an action people run through the CLI, API or UI; remove it from the role"
        )
    if action in ADMIN_ONLY or action.startswith(ADMIN_ONLY_PREFIXES):
        raise UsageError(
            f"action {action!r}: identity, access and project administration stay with "
            "deployment administrators; expected another action; remove it from the role "
            "(access is delegated with CAN_MANAGE)"
        )
    return action


def deployment_only(action: ActionName) -> bool:
    """Whether an action acts on the whole deployment, so it binds only at deployment scope."""
    from etl_craft.services.operations.actions import ACTIONS

    return ACTIONS[action].scope == ActionScope.DEPLOYMENT


def built_in_actions(permission: Permission) -> tuple[str, ...]:
    """Describe what a built-in CAN_* role allows, from the same rules authorization applies."""
    from etl_craft.services.operations.actions import ACTIONS, PROJECT_MANAGE_ACTIONS

    level = tuple(Permission).index(permission)
    allowed = {ApiRole.VIEWER} | ({ApiRole.OPERATOR} if level >= 2 else set())
    names = {
        name
        for name, spec in ACTIONS.items()
        if spec.scope != ActionScope.DEPLOYMENT
        and spec.role in allowed
        and spec.placement == Placement.ANYWHERE
        and (name != ActionName.UPLOAD or level >= 1)
    }
    if permission == Permission.CAN_MANAGE:
        names |= set(PROJECT_MANAGE_ACTIONS) | ADMIN_ONLY
    return tuple(sorted(names))


def role_actions(conn: Connection) -> dict[str, tuple[str, ...]]:
    """Return every active role's allowed actions, built-in roles included."""
    by_id: dict[int, list[str]] = {}
    for row in conn.execute(statement(conn, "role_actions")):
        by_id.setdefault(int(row.role_id), []).append(str(row.action_name))
    result = {}
    for row in conn.execute(statement(conn, "role_list")):
        if row.built_in == YesNo.YES:
            result[str(row.name)] = built_in_actions(Permission(row.name))
        else:
            result[str(row.name)] = tuple(by_id.get(int(row.role_id), ()))
    return result


def list_roles(ctx: OperationContext, request: NoInput) -> Roles:
    """List roles, inactive ones included, with what each allows."""
    with ctx.engine.connect() as conn:
        actions = role_actions(conn)
        return Roles(
            tuple(
                Role(
                    str(row.name),
                    row.description,
                    row.built_in == YesNo.YES,
                    YesNo(row.active_flag),
                    actions[str(row.name)],
                )
                for row in conn.execute(statement(conn, "role_list"))
            )
        )


def describe_role(ctx: OperationContext, request: RoleName) -> Roles:
    """Show one role and the actions it allows."""
    found = tuple(r for r in list_roles(ctx, NoInput()).roles if r.name == request.name)
    if not found:
        raise UsageError(f"role {request.name!r}: not found; use `etl-craft role list`")
    return Roles(found)


def create_role(ctx: OperationContext, request: RoleCreate) -> Roles:
    """Create a custom role and its actions in one transaction."""
    if request.name.upper() in tuple(Permission):
        raise UsageError(f"role {request.name!r}: a built-in role name; choose another name")
    actions = tuple(dict.fromkeys(bindable(a) for a in request.actions))
    try:
        with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
            conn.execute(
                statement(conn, "role_add"),
                {"name": request.name, "description": request.description},
            )
            role_id = _custom_role_id(conn, request.name)
            for action in actions:
                conn.execute(
                    statement(conn, "role_action_add"),
                    {"role_id": role_id, "action_name": str(action)},
                )
    except IntegrityError as error:
        raise UsageError(
            f"role {request.name!r}: name already exists; choose a distinct role name"
        ) from error
    return describe_role(ctx, request)


def add_action(ctx: OperationContext, request: RoleAction) -> Roles:
    """Add one action to a custom role; an action it already holds is left unchanged."""
    action = bindable(request.action)
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        role_id = _custom_role_id(conn, request.name)
        if str(action) not in role_actions(conn)[request.name]:
            conn.execute(
                statement(conn, "role_action_add"),
                {"role_id": role_id, "action_name": str(action)},
            )
    return describe_role(ctx, request)


def remove_action(ctx: OperationContext, request: RoleAction) -> Roles:
    """Remove one action from a custom role, keeping its history."""
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        role_id = _custom_role_id(conn, request.name)
        removed = conn.execute(
            statement(conn, "role_action_remove"),
            {"role_id": role_id, "action_name": request.action.strip()},
        ).first()
        if removed is None:
            raise UsageError(
                f"role {request.name!r}: does not allow {request.action!r}; "
                "use `etl-craft role describe` to see its actions"
            )
    return describe_role(ctx, request)


def disable_role(ctx: OperationContext, request: RoleName) -> Roles:
    """Retire a custom role; its bindings stop allowing anything on the next request."""
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        _custom_role_id(conn, request.name)
        conn.execute(statement(conn, "role_disable"), {"name": request.name})
    return describe_role(ctx, request)


def _custom_role_id(conn: Connection, name: str) -> int:
    for row in conn.execute(statement(conn, "role_list")):
        if row.name == name:
            if row.built_in == YesNo.YES:
                raise UsageError(
                    f"role {name!r}: built-in roles cannot be changed; create a custom role"
                )
            if row.active_flag != YesNo.YES:
                raise UsageError(f"role {name!r}: disabled; create a new role instead")
            return int(row.role_id)
    raise UsageError(f"role {name!r}: not found; use `etl-craft role list`")
