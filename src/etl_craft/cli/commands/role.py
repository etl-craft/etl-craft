"""Roles are named sets of actions that access bindings give to accounts and groups."""

import argparse

from etl_craft.cli.commands.common import Command, call, configure_output, request_from
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.services.operations import roles
from etl_craft.services.operations.requests import NoInput

VERBS = {
    "list": (ActionName.ROLE_LIST, NoInput),
    "describe": (ActionName.ROLE_DESCRIBE, roles.RoleName),
    "create": (ActionName.ROLE_CREATE, roles.RoleCreate),
    "add-action": (ActionName.ROLE_ADD_ACTION, roles.RoleAction),
    "remove-action": (ActionName.ROLE_REMOVE_ACTION, roles.RoleAction),
    "disable": (ActionName.ROLE_DISABLE, roles.RoleName),
}


def _configure(parser: argparse.ArgumentParser) -> None:
    verbs = parser.add_subparsers(dest="role_verb", required=True)
    for name in VERBS:
        sub = verbs.add_parser(name)
        if name != "list":
            sub.add_argument("name", help="The role, such as data-analyst or CAN_RUN.")
        if name == "create":
            sub.add_argument("--description")
            sub.add_argument(
                "--action",
                dest="actions",
                action="append",
                default=[],
                help="An action the role allows, such as 'run'; repeat for more.",
            )
        if name in ("add-action", "remove-action"):
            sub.add_argument("--action", required=True, help="One action, such as 'run'.")
        configure_output(sub)


def _run(args: argparse.Namespace, out: Output) -> int:
    action, request = VERBS[args.role_verb]
    if args.role_verb == "create":
        args.actions = tuple(args.actions)
    done = call(args, action, request_from(args, request))
    assert isinstance(done, roles.Roles)
    out.result(
        done,
        args.output_format,
        text=lambda: out.rows(
            (
                r.name,
                "built-in" if r.built_in else "custom",
                r.active_flag,
                r.description or "",
                ", ".join(r.actions),
            )
            for r in done.roles
        ),
    )
    return 0


COMMAND = Command(
    "role",
    "Manage roles: named sets of actions that access bindings grant.",
    _run,
    _configure,
    actions=tuple(action for action, _ in VERBS.values()),
)
