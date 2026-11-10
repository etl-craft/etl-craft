"""Password and device-flow sign-in, sign-out and account identity, locally or on a controller."""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import replace

from etl_craft.cli.authentication import command_identity
from etl_craft.cli.client import ApiClient
from etl_craft.cli.commands.common import (
    Command,
    call,
    command_context,
    command_project,
    configure_output,
    prepare_context,
)
from etl_craft.cli.output import Output
from etl_craft.cli.prompts import CONSOLE, interactive, password, piped_password
from etl_craft.core import interrupts
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ConfigurationError, UsageError
from etl_craft.services import credentials
from etl_craft.services.operations import sessions
from etl_craft.services.operations.requests import NoInput


def _login_options(parser: argparse.ArgumentParser) -> None:
    """Offer the unattended password sign-in that takes its secret from a pipe."""
    parser.add_argument("--name", help="Account name for --password-stdin.")
    parser.add_argument(
        "--password-stdin", action="store_true", help="Read one password line from a pipe."
    )


def _piped_credentials(args: argparse.Namespace) -> sessions.SignIn | None:
    """Return the piped account and password when asked for; refuse a terminal or a lone flag."""
    if not args.password_stdin:
        if args.name:
            raise UsageError("login --name requires --password-stdin; pipe the account's password")
        return None
    if sys.stdin.isatty() or not args.name:
        raise UsageError(
            "login --password-stdin requires piped stdin and --name N; pipe a secret "
            "from your secret manager instead of typing it visibly"
        )
    secret = piped_password("login")
    return sessions.SignIn(name=args.name, password=secret)


def _login(args: argparse.Namespace, out: Output) -> int:
    piped = _piped_credentials(args)
    if piped is None:
        interactive()
    methods = call(args, ActionName.LOGIN_METHODS, NoInput())
    assert isinstance(methods, sessions.SignInMethods)
    if piped is not None:
        signed = call(args, ActionName.LOGIN, piped)
        assert isinstance(signed, sessions.Session)
        session = signed
    elif methods.sso and input("Sign in with SSO? [y/N]: ").lower() == "y":
        session = sso_session(
            lambda: call(args, ActionName.LOGIN_SSO, NoInput()),
            lambda start: call(
                args,
                ActionName.LOGIN_SSO_POLL,
                sessions.SsoPollInput(device_code=start.device_code, nonce=start.nonce),
            ),
            out,
        )
    else:
        signed = call(
            args,
            ActionName.LOGIN,
            sessions.SignIn(name=input("Account name: "), password=password()),
        )
        assert isinstance(signed, sessions.Session)
        session = signed
    try:
        where = _store(args, session)
    except BaseException:
        token = session.refresh_token or session.access_token
        call(args, ActionName.LOGOUT, sessions.TokenInput(token=token))
        raise
    if CONSOLE.get() is None and command_project(args):
        scoped = command_identity.get()
        identity_token = command_identity.set(
            replace(scoped, identity=session.metadata) if scoped else None
        )
        try:
            prepare_context(args, ActionName.WHOAMI, identity=True)
        finally:
            command_identity.reset(identity_token)
    out.line(f"Signed in{where} as {session.metadata.name} ({session.metadata.role})")
    return 0


def _store(args: argparse.Namespace, session: sessions.Session) -> str:
    """Keep the session where later commands find it; return where, for the message."""
    if args.api:
        client = ApiClient(args.api)
        client.store(session)
        return f" to {client.url}"
    with command_context(args) as ctx:
        key = credentials.database_key(ctx.engine, ctx.config.engine.schema)
    credentials.store_session(key, session.access_token)
    return ""


def sso_session(
    start: Callable[[], object],
    poll: Callable[[sessions.SsoStart], object],
    out: Output,
) -> sessions.Session:
    """Show the issuer's code, then poll until the person approves or the code expires."""
    begun = start()
    assert isinstance(begun, sessions.SsoStart)
    out.line(f"Open {begun.verification_uri} and enter {begun.user_code}")
    deadline = time.monotonic() + begun.expires_in
    interval = begun.interval
    while time.monotonic() + interval < deadline:
        interrupts.sleep(interval)
        polled = poll(begun)
        assert isinstance(polled, sessions.SsoPoll)
        if polled.session is not None:
            return polled.session
        interval += polled.interval
    raise ConfigurationError("OIDC device code expired; run `etl-craft login` again")


def _logout(args: argparse.Namespace, out: Output) -> int:
    if args.api:
        client = ApiClient(args.api)
        token = client.forget()
        where = f" of {client.url}"
    else:
        with command_context(args) as ctx:
            key = credentials.database_key(ctx.engine, ctx.config.engine.schema)
        token = credentials.read_session(key)
        credentials.store_session(key, None)
        where = ""
    if token is not None:
        call(args, ActionName.LOGOUT, sessions.TokenInput(token=token))
    out.line(f"Signed out{where}")
    return 0


def _whoami(args: argparse.Namespace, out: Output) -> int:
    if CONSOLE.get() is None and command_project(args):
        prepare_context(args, ActionName.WHOAMI, identity=True)
    identity = call(
        args,
        ActionName.WHOAMI,
        sessions.IdentityInput(
            project=None if CONSOLE.get() is not None else command_project(args) or None
        ),
    )
    assert isinstance(identity, sessions.Identity)
    out.result(
        identity,
        args.output_format,
        text=lambda: out.line(
            f"Account: {identity.name} · role: {identity.role}"
            if out.stdout.isatty()
            else f"{identity.name} {identity.role}"
        ),
    )
    return 0


COMMANDS = (
    Command(
        "login",
        "Sign in on this project's Engine DB, or through the API with --api.",
        _login,
        _login_options,
        actions=(
            ActionName.LOGIN_METHODS,
            ActionName.LOGIN,
            ActionName.LOGIN_SSO,
            ActionName.LOGIN_SSO_POLL,
            ActionName.LOGOUT,
        ),
    ),
    Command(
        "logout",
        "Revoke and remove this person's stored session.",
        _logout,
        actions=(ActionName.LOGOUT,),
    ),
    Command(
        "whoami",
        "Print the signed-in account and role.",
        _whoami,
        configure_output,
        actions=(ActionName.WHOAMI,),
    ),
)
