"""Administrator interface to the shared channel operations."""

import argparse

from etl_craft.cli.commands.common import Command, call, configure_output, request_from
from etl_craft.cli.output import Output
from etl_craft.core.alerts import AlertKind, AlertTrigger
from etl_craft.core.enums import ActionName
from etl_craft.services.operations import alert_channels as operations

VERBS = {
    "list": (ActionName.ALERT_CHANNEL_LIST, operations.ChannelIdentity),
    "set": (ActionName.ALERT_CHANNEL_SET, operations.ChannelWrite),
    "disable": (ActionName.ALERT_CHANNEL_DISABLE, operations.ChannelDisable),
}


def configure(parser: argparse.ArgumentParser) -> None:
    """All routes require an explicit project; writes name their actor's reason."""
    verbs = parser.add_subparsers(dest="channel_verb", required=True)
    for verb in VERBS:
        sub = verbs.add_parser(verb)
        sub.add_argument("--project", required=True, help="Project that owns this channel.")
        sub.add_argument("--name", required=verb != "list", help="Approved channel name.")
        if verb != "list":
            sub.add_argument("--reason", required=True, help="Administrator's audit explanation.")
        if verb == "set":
            sub.add_argument("--kind", type=AlertKind, choices=tuple(AlertKind), required=True)
            sub.add_argument("--url-secret", required=True, help="URL secret variable name only.")
            sub.add_argument(
                "--signing-secret", required=True, help="Signing key variable name only."
            )
            sub.add_argument(
                "--default-alert-on",
                default=AlertTrigger.FAILURE,
                help="Pipe-separated event selectors.",
            )
        configure_output(sub)


def run(args: argparse.Namespace, out: Output) -> int:
    """Parse and render; the operation owns routing, validation and authorization."""
    action, request = VERBS[args.channel_verb]
    done = call(args, action, request_from(args, request))
    assert isinstance(done, operations.Channels)
    out.result(
        done,
        args.output_format,
        text=lambda: out.rows(
            (c.channel_name, c.kind, c.default_alert_on, c.active_flag) for c in done.channels
        ),
    )
    return 0


COMMAND = Command(
    "alert-channel",
    "Manage project alert routing (admin only).",
    run,
    configure,
    actions=tuple(action for action, _ in VERBS.values()),
)
