"""What every command that reads craft-connector.yml does first."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar

from sqlalchemy.engine import Engine

from etl_craft.cli.authentication import command_identity
from etl_craft.cli.client import ApiClient
from etl_craft.cli.output import Output
from etl_craft.cli.prompts import CONSOLE
from etl_craft.config import ConnectorConfig, load_config, resolve_config_path
from etl_craft.config.discovery import CONFIG_PATH_ENV_VAR
from etl_craft.config.loader import load_project
from etl_craft.config.sizing import start_role
from etl_craft.core.actor import current_actor
from etl_craft.core.enums import ActionName, ActionScope, ApiRole, HttpMethod
from etl_craft.core.environment import Environment
from etl_craft.core.errors import UsageError
from etl_craft.core.text import is_metadata_code
from etl_craft.engine.connection import check_reachable, engine_db
from etl_craft.execution.attempt_types import ChildOptions
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import ACTIONS, invoke
from etl_craft.services.operations.identity import authenticated_context
from etl_craft.services.operations.tokens import TokenView
from etl_craft.services.operations.upgrade_signin import UpgradeAdmin

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

logger = logging.getLogger(__name__)

R = TypeVar("R", bound="DataclassInstance")


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, its one-line help, its options and what it does.

    ``configure`` adds the command's own options to its parser. ``run`` receives the parsed
    arguments, including the global ``config``, ``log_level`` and ``log_format``, and returns
    the exit code. It reports failures by raising an ``EtlCraftError``, which the command line
    turns into an ``error:`` line and that error's exit code.
    """

    name: str
    help: str
    run: Callable[[argparse.Namespace, Output], int]
    configure: Callable[[argparse.ArgumentParser], None] | None = None
    actions: tuple[ActionName, ...] = ()
    """The actions the command calls, whichever its options select."""


def command_config_path(args: argparse.Namespace) -> Path:
    """Select one folder's config before authentication or project selection."""
    directory = getattr(args, "project_dir", None)
    if directory is not None and args.config is not None:
        raise UsageError("--project-dir and --config both given; choose one project source")
    return (
        directory / "craft-connector.yml"
        if directory is not None
        else resolve_config_path(args.config)
    )


def load_command_config(args: argparse.Namespace) -> ConnectorConfig:
    """Find and load craft-connector.yml: ``--config``, ``$ETL_CRAFT_CONFIG``, or a search."""
    scoped = command_identity.get()
    if scoped is not None:
        return scoped.config
    path = command_config_path(args)
    logger.debug("reading %s", path)
    return load_config(path)


def connect_engine_db(config: ConnectorConfig) -> Engine:
    """Build the Engine DB engine and check it, and its schema, can be used."""
    engine = engine_db(config)
    try:
        check_reachable(engine, config.engine.schema)
    except BaseException:
        engine.dispose()
        raise
    return engine


def configure_run_selector(parser: argparse.ArgumentParser) -> None:
    """Add mutually exclusive identities for a pipeline's run."""
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--run-id", help="The exact pipeline run id or stored run label.")
    selection.add_argument("--run-key", help="The exact run key within this pipeline.")


def configure_tags(parser: argparse.ArgumentParser) -> None:
    """Offer the shared repeatable AND filter."""
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Carry every given tag (repeatable; exact match).",
    )


def configure_output(parser: argparse.ArgumentParser) -> None:
    """Offer one schema-versioned operation document instead of text output."""
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="Result format (default: text).",
    )


@contextmanager
def command_context(
    args: argparse.Namespace, *, role: Literal["run", "controller", "ui"] | None = None
) -> Iterator[OperationContext]:
    """Load command resources and dispose them after the service operation.

    ``role`` marks a process that runs tasks or serves: its allocation is measured and, with a
    ``Deployment.Profile``, its slots, threads and Engine DB pool are sized from it.
    """
    config = load_command_config(args)
    if role is not None:
        config = start_role(config, server=role in ("controller", "ui"))
    engine = connect_engine_db(config)
    try:
        project = args.project or config.project
        if args.project and config.project and args.project != config.project:
            raise UsageError(
                f"--project={args.project!r} conflicts with "
                f"Orchestration.Project={config.project!r} "
                f"in {config.config_path}; select that project's own craft-connector.yml"
            )
        if project and not is_metadata_code(project):
            raise UsageError(
                f"project={project!r}; expected a letter followed by at most 127 letters, "
                "numbers or underscores; pass --project with a valid code"
            )
        context = OperationContext(
            engine,
            replace(config, project=project),
            current_actor(),
            ChildOptions(log_level=args.log_level, log_format=args.log_format),
            role=(
                ApiRole(scoped.identity.role)
                if (scoped := command_identity.get()) and scoped.identity
                else None
            ),
            provisioning=scoped is not None and scoped.provisioning,
            project=project,
        )
        yield (
            authenticated_context(context, scoped.identity)
            if scoped is not None and isinstance(scoped.identity, TokenView)
            else replace(
                context,
                actor=scoped.identity.actor,
                upgrade_signin=isinstance(scoped.identity, UpgradeAdmin),
            )
            if scoped is not None and scoped.identity is not None
            else context
        )
    finally:
        engine.dispose()


def request_from(args: argparse.Namespace, cls: type[R], **given: object) -> R:
    """Build an action's request from the options whose names are its fields, and ``given``."""
    values = {f.name: getattr(args, f.name) for f in fields(cls) if hasattr(args, f.name)}
    return cls(**{**values, **given})


def call(
    args: argparse.Namespace,
    name: ActionName,
    request: object,
    *,
    role: Literal["run", "controller", "ui"] | None = None,
) -> object:
    """Run one action: as the web console's caller, through the API with ``--api``, else here."""
    caller = CONSOLE.get()
    if caller is not None:
        return invoke(caller, name, request)
    if args.api and ACTIONS[name].method is None:
        command_project(args, required=ACTIONS[name].scope != ActionScope.DEPLOYMENT)
        on_host(args, name)
    if name == ActionName.MIGRATE:
        from etl_craft.engine.migrations import before_project_migrations

        prepare_context(args, name, confirm=False)
        token = before_project_migrations.set(lambda: prepare_context(args, name))
        try:
            with command_context(args, role=role) as ctx:
                return invoke(ctx, name, request)
        finally:
            before_project_migrations.reset(token)
    prepare_context(args, name)
    if args.api:
        return ApiClient(
            args.api, command_project(args, required=ACTIONS[name].scope != ActionScope.DEPLOYMENT)
        ).invoke(name, request)
    with command_context(args, role=role) as ctx:
        return invoke(ctx, name, request)


def command_project(args: argparse.Namespace, *, required: bool = False) -> str:
    """Select an API project without loading any connection credentials."""
    path = command_config_path(args)
    configured = (
        load_project(path)
        if getattr(args, "project_dir", None) is not None
        or args.config is not None
        or os.environ.get(CONFIG_PATH_ENV_VAR)
        or path.is_file()
        else ""
    )
    if args.project and configured and args.project != configured:
        raise UsageError(
            f"--project={args.project!r} conflicts with Orchestration.Project={configured!r} "
            f"in {path}; select that project's own craft-connector.yml"
        )
    selected = args.project or configured
    if required and not selected:
        raise UsageError(
            f"{path}: missing Orchestration.Project; supply --project P "
            "or set Orchestration.Project in this file"
        )
    return selected


def on_host(args: argparse.Namespace, name: ActionName) -> None:
    """Refuse ``--api`` for an action that runs only on the controller's host."""
    if args.api:
        remedy = ACTIONS[name].remedy
        raise UsageError(f"`{name}` runs on the controller's host only: {remedy}")


def prepare_context(
    args: argparse.Namespace, name: ActionName, *, identity: bool = False, confirm: bool = True
) -> None:
    """Resolve presentation through the existing authorized project-list action."""
    from etl_craft.services.operations.admin_metadata import ProjectIdentity, Projects

    out = getattr(args, "_output", None)
    if (
        out is None
        or CONSOLE.get() is not None
        or (ACTIONS[name].scope == ActionScope.DEPLOYMENT and not identity)
    ):
        return
    if name == ActionName.MIGRATE:
        from etl_craft.dialects.engine import for_engine
        from etl_craft.services.credentials import database_key

        with command_context(args) as ctx, ctx.engine.connect() as conn:
            columns = (
                for_engine(conn).column_names(conn, "CFG_PROJECTS")
                if for_engine(conn).has_table(conn, "CFG_PROJECTS")
                else []
            )
            if "environment_type" not in {column.lower() for column in columns}:
                out.unknown_environment(
                    database_key(ctx.engine, ctx.config.engine.schema),
                    json=getattr(args, "output_format", "text") == "json",
                )
                return
            scoped = command_identity.get()
            if scoped is not None and (
                scoped.provisioning
                or (scoped.identity is not None and scoped.identity.role == ApiRole.ADMIN)
            ):
                from etl_craft.engine.environment import project_environment

                project, environment = project_environment(conn, code=ctx.project or None)
                out.context(
                    project,
                    environment,
                    None,
                    json=getattr(args, "output_format", "text") == "json",
                )
    if identity:
        identity_context(args, out)
        return
    if out.environment is None:
        project = command_project(args, required=bool(args.api))
        request = ProjectIdentity(project=project or None, reason="CLI environment context")
        if args.api:
            projects = ApiClient(args.api).invoke(ActionName.PROJECT_LIST, request)
        else:
            with command_context(args) as ctx:
                projects = invoke(ctx, ActionName.PROJECT_LIST, request)
        assert isinstance(projects, Projects)
        if len(projects.projects) != 1:
            raise UsageError(
                f"project {project!r}: environment unavailable; select an accessible "
                f"project with --project"
            )
        row = projects.projects[0]
        out.context(
            row.project,
            Environment(row.environment_type, row.environment_name),
            args.api,
            json=getattr(args, "output_format", "text") == "json",
        )
    if confirm and (
        (
            ACTIONS[name].method == HttpMethod.POST
            and name not in {ActionName.DATA_PROVENANCE, ActionName.AGENT_DOCTOR}
        )
        or name in {ActionName.CONFIG_APPLY, ActionName.MIGRATE, ActionName.PUBLISH_DOCS}
    ):
        out.confirm(name, yes=args.yes)


def identity_context(args: argparse.Namespace, out: Output) -> None:
    """Use the identity action, which remains available during a forced password change."""
    from etl_craft.services.operations.sessions import Identity, IdentityInput

    selected = command_project(args, required=bool(args.api))
    account = call(args, ActionName.WHOAMI, IdentityInput(project=selected))
    assert isinstance(account, Identity)
    if account.environment is not None:
        out.context(
            selected,
            account.environment,
            args.api,
            json=getattr(args, "output_format", "text") == "json",
        )
