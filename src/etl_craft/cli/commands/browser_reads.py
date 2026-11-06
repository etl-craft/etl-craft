"""Version information and generated catalog reads share the browser's operations."""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from etl_craft.cli.banner import Facts, render, wants_art, wants_colour
from etl_craft.cli.commands.common import (
    Command,
    call,
    command_project,
    configure_output,
    prepare_context,
)
from etl_craft.cli.output import Output
from etl_craft.cli.prompts import CONSOLE
from etl_craft.core.enums import ActionName
from etl_craft.services.operations import sessions
from etl_craft.services.operations.about import About
from etl_craft.services.operations.catalog_pages import CatalogInput, CatalogPage
from etl_craft.services.operations.requests import NoInput


def _about_options(parser: argparse.ArgumentParser) -> None:
    configure_output(parser)
    parser.add_argument("--json", dest="output_format", action="store_const", const="json")


def _banner(args: argparse.Namespace, about: About) -> str:
    """Render the versions with the signed-in account and the selected project's environment."""
    selected = None if CONSOLE.get() is not None else command_project(args) or None
    if selected:
        prepare_context(args, ActionName.WHOAMI, identity=True)
    who = call(args, ActionName.WHOAMI, sessions.IdentityInput(project=selected))
    assert isinstance(who, sessions.Identity)
    label = who.environment.label if who.environment else None
    facts = Facts(
        version=about.package_version,
        schema=about.schema_version,
        account=who.name,
        role=who.role,
        project=selected,
        environment=label,
        production=label == "PRODUCTION",
        controllers=len(about.controllers),
        server=about.server_version,
        docs=about.docs_url,
    )
    return render(facts, art=wants_art(sys.stdout, facts), colour=wants_colour(sys.stdout))


def _about(args: argparse.Namespace, out: Output) -> int:
    result = call(args, ActionName.ABOUT, NoInput())
    assert isinstance(result, About)
    out.result(result, args.output_format, text=lambda: out.line(_banner(args, result)))
    return 0


def _catalog_options(parser: argparse.ArgumentParser) -> None:
    verbs = parser.add_subparsers(dest="catalog_verb", required=True)
    page = verbs.add_parser("page", help="Read an existing generated page without rebuilding it.")
    page.add_argument("--path", default="index.html")
    page.add_argument("--output", type=Path)


def _catalog(args: argparse.Namespace, out: Output) -> int:
    page = call(args, ActionName.CATALOG_PAGE, CatalogInput(path=args.path))
    assert isinstance(page, Iterable)
    try:
        if args.output is None:
            out.chunks(page, binary=True)
        else:
            with args.output.open("wb") as target:
                for chunk in page:
                    target.write(chunk)
    finally:
        if isinstance(page, CatalogPage):
            page.close()
    return 0


ABOUT = Command(
    "about",
    "A banner: versions, the signed-in account and the project's environment.",
    _about,
    _about_options,
    actions=(ActionName.ABOUT, ActionName.WHOAMI),
)
CATALOG = Command(
    "catalog",
    "Read the selected project's existing generated catalog.",
    _catalog,
    _catalog_options,
    actions=(ActionName.CATALOG_PAGE,),
)
