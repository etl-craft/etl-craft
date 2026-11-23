"""Administrator-managed group identities and their durable account memberships."""

from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import YesNo
from etl_craft.core.errors import UsageError
from etl_craft.engine import locks
from etl_craft.engine.queries import statement
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import NoInput, Request


@dataclass(frozen=True)
class Group:
    """A group identity, including inactive identities retained for audit."""

    group_id: int
    name: str
    description: str | None
    active_flag: YesNo
    members: tuple[str, ...]


@dataclass(frozen=True)
class Groups:
    """Group administration results."""

    SCHEMA: ClassVar[str] = "etl-craft/groups/1"
    groups: tuple[Group, ...]


@dataclass(frozen=True, kw_only=True)
class GroupName(Request):
    """One group by its stable name."""

    name: str

    def __post_init__(self) -> None:
        """Apply the same name limits as account identities."""
        Actor(self.name, ActorKind.USER)


@dataclass(frozen=True, kw_only=True)
class GroupAdd(GroupName):
    """A new group and its optional description."""

    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class GroupMember(GroupName):
    """An account's membership of a group."""

    account: str

    def __post_init__(self) -> None:
        """Check both identity names."""
        super().__post_init__()
        Actor(self.account, ActorKind.USER)


def list_groups(ctx: OperationContext, request: NoInput) -> Groups:
    """List groups and their active explicit members."""
    with ctx.engine.connect() as conn:
        members: dict[int, list[str]] = {}
        for row in conn.execute(statement(conn, "group_members")):
            members.setdefault(row.group_id, []).append(row.account_name)
        return Groups(
            tuple(
                Group(
                    row.group_id,
                    row.name,
                    row.description,
                    YesNo(row.active_flag),
                    tuple(members.get(row.group_id, ())),
                )
                for row in conn.execute(statement(conn, "group_list"))
            )
        )


def add_group(ctx: OperationContext, request: GroupAdd) -> Groups:
    """Create a permanent identity; disabled names remain reserved."""
    try:
        with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
            conn.execute(
                statement(conn, "group_add"),
                {
                    "name": request.name,
                    "description": request.description,
                },
            )
    except IntegrityError as error:
        raise UsageError(
            f"group {request.name!r}: name already exists; choose a distinct group name"
        ) from error
    return list_groups(ctx, NoInput())


def disable_group(ctx: OperationContext, request: GroupName) -> Groups:
    """Retire a group without deleting memberships or grants."""
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        require_group(conn, request.name)
        conn.execute(statement(conn, "group_disable"), {"name": request.name})
    return list_groups(ctx, NoInput())


def add_member(ctx: OperationContext, request: GroupMember) -> Groups:
    """Add or reactivate membership of an active account and group."""
    return _membership(ctx, request, YesNo.YES)


def remove_member(ctx: OperationContext, request: GroupMember) -> Groups:
    """Retire a membership while retaining its identity and history."""
    return _membership(ctx, request, YesNo.NO)


def _membership(ctx: OperationContext, request: GroupMember, active: YesNo) -> Groups:
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30), ctx.engine.begin() as conn:
        values = {"name": request.name, "account": request.account, "active": active}
        found = require_membership_identities(conn, request, active == YesNo.YES)
        values.update(group_id=found.group_id, account_id=found.account_id)
        conn.execute(statement(conn, "group_member_set"), values)
    return list_groups(ctx, NoInput())


def require_membership_identities(
    conn: Connection, request: GroupMember, adding: bool
) -> Row[tuple[object, ...]]:
    """Resolve the same identities for inspection and a membership change."""
    found = conn.execute(
        statement(conn, "group_member_identity"),
        {
            "name": request.name,
            "account": request.account,
            "active": YesNo.YES if adding else YesNo.NO,
        },
    ).one_or_none()
    if found is None:
        raise UsageError(
            f"group {request.name!r}, account {request.account!r}: expected active identities; "
            "check `etl-craft group list` and `etl-craft account list`"
        )
    return found


def require_group(conn: Connection, name: str) -> None:
    """Require the retained group that disable updates, including inactive groups."""
    if not any(row.name == name for row in conn.execute(statement(conn, "group_list"))):
        raise UsageError(f"group {name!r}: not found; use `etl-craft group list`")
