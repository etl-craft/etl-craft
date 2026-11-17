"""Access bindings: give a role or one command to an account, group or audience, somewhere."""

import argparse

from etl_craft.cli.commands.common import (
    Command,
    call,
    command_project,
    configure_output,
    request_from,
)
from etl_craft.cli.output import Output
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import UsageError
from etl_craft.services.operations.access import AccessFilter, AccessView, AccessWrite
from etl_craft.services.operations.bindings import ExplainInput, Explanation

VERBS = {
    "grant": ActionName.ACCESS_GRANT,
    "revoke": ActionName.ACCESS_REVOKE,
    "list": ActionName.ACCESS_LIST,
    "explain": ActionName.ACCESS_EXPLAIN,
}


def configure(parser: argparse.ArgumentParser) -> None:
    """Keep project selection on the shared global flag."""
    verbs = parser.add_subparsers(dest="access_verb", required=True)
    for name in VERBS:
        sub = verbs.add_parser(name)
        sub.add_argument("--project", default=argparse.SUPPRESS)
        if name == "explain":
            sub.add_argument("--account", required=True)
            sub.add_argument("--action", required=True, help="The command, such as 'run'.")
            sub.add_argument("--pipeline")
            configure_output(sub)
            continue
        reach = sub.add_mutually_exclusive_group()
        reach.add_argument("--environment", help="Every project of this environment type.")
        reach.add_argument("--deployment", action="store_true", help="Every project.")
        principal = sub.add_mutually_exclusive_group()
        principal.add_argument("--group")
        principal.add_argument("--account")
        principal.add_argument("--audience", help="Every account with this deployment role.")
        target = sub.add_mutually_exclusive_group()
        target.add_argument("--pipeline")
        target.add_argument("--tag")
        if name != "list":
            what = sub.add_mutually_exclusive_group()
            what.add_argument("--role", help="CAN_VIEW, CAN_UPLOAD, CAN_RUN, CAN_MANAGE or custom.")
            what.add_argument("--action", help="One command, such as 'run'.")
            sub.add_argument("--reason", required=True)
        if name == "grant":
            sub.add_argument("--dry-run", action="store_true")
        configure_output(sub)


def run(args: argparse.Namespace, out: Output) -> int:
    """Submit one binding or explanation to the shared operation."""
    if args.access_verb == "explain":
        args.project = getattr(args, "project", None) or command_project(args)
        explained = call(args, VERBS["explain"], request_from(args, ExplainInput))
        assert isinstance(explained, Explanation)
        out.result(explained, args.output_format, text=lambda: render_explanation(out, explained))
        return 0
    wide = getattr(args, "deployment", False) or getattr(args, "environment", None)
    if not wide:
        args.project = command_project(args)
    if not wide and not args.project:
        raise UsageError(
            "access: scope is missing; expected --project P, --environment E or --deployment; "
            "choose where the binding applies"
        )
    request = (
        request_from(args, AccessFilter)
        if args.access_verb == "list"
        else request_from(args, AccessWrite)
    )
    done = call(args, VERBS[args.access_verb], request)
    assert isinstance(done, AccessView)
    out.result(
        done,
        args.output_format,
        text=lambda: render(out, done),
    )
    return 0


def render(out: Output, done: AccessView) -> None:
    """Show one change, or the bindings and the caller's effective pipeline levels."""
    if done.change is not None:
        b = done.change.binding
        out.rows(
            [
                (
                    done.change.change,
                    b.scope,
                    b.project or b.environment or "deployment",
                    b.group or b.account or b.audience,
                    b.pipeline or b.tag or "",
                    done.change.previous_role or "",
                    b.role or b.action,
                )
            ]
        )
        return
    out.rows(
        (
            b.scope,
            b.project or b.environment or "deployment",
            b.group or b.account or b.audience,
            b.pipeline or b.tag or "",
            b.role or b.action,
            b.active_flag,
        )
        for b in done.bindings
    )
    if done.project_level is not None:
        out.rows([("caller project", done.project_level, ", ".join(done.project_sources))])
    out.rows(
        ("caller effective", code, level, ", ".join(sources))
        for code, level, sources in done.effective
    )


def render_explanation(out: Output, done: Explanation) -> None:
    """Say whether the account may run the action, what allows it, or why it is refused."""
    verdict = "allowed" if done.allowed else "refused"
    out.rows([(done.account, done.action, done.pipeline or done.project or "", verdict)])
    out.rows(("allowed by", source) for source in done.allowed_by)
    if done.refusal:
        out.rows([("refused", done.refusal)])
    if done.roles_with_action:
        out.rows([("roles that allow it", ", ".join(done.roles_with_action))])


COMMAND = Command(
    "access",
    "Grant roles or single commands to accounts, groups and audiences, and explain access.",
    run,
    configure,
    actions=tuple(VERBS.values()),
)
