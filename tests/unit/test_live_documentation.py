"""Live instructions agree with the registered API and parser inventories."""

import argparse
import re
import runpy
from contextlib import nullcontext
from io import StringIO
from pathlib import Path

import mkdocs_gen_files
import pytest

from etl_craft.cli import build_parser
from etl_craft.config.loader import settings_by_section
from etl_craft.config.loader_helpers import shown
from etl_craft.config.managed_engine import MANAGED_FIELDS
from fixtures.scripts import load

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
ROUTE = re.compile(r"(?:(GET|POST|PUT|PATCH|DELETE) )?(/api/v1/[\w./{}$-]+)")
REMOVED = re.compile(
    r"\b(?:remote[- ]mode|mode remote|remote_mode\.sql|Orchestration\.Mode|"
    r"Erasure\.Hmac_secret|etl-craft (?:control|controller start|generate-yml)\b(?!-))"
    r"|--finalize-only"
)


def live_documents():
    """Read current guides and examples, excluding historical design and roadmap text."""
    for folder in ("docs", "examples"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix in {".md", ".py", ".yml", ".yaml"} and (
                folder != "docs" or path.relative_to(ROOT / folder).parts[0] != "development"
            ):
                yield path, path.read_text(encoding="utf-8")


def test_documented_operational_routes_are_registered(tmp_path):
    from sqlalchemy import create_engine

    from etl_craft.api.app import create_app
    from etl_craft.config import load_config
    from etl_craft.core.actor import SYSTEM_ACTOR
    from etl_craft.services.operations.actions import ACTIONS, action_path
    from etl_craft.services.operations.context import OperationContext

    config = tmp_path / "craft-connector.yml"
    config.write_text(
        "Secrets:\n  Source_type: ENVIRONMENT\n"
        "Engine:\n  dev:\n    Jdbc_url: jdbc:sqlite:engine.db\n    Schema: main\n"
    )
    engine = create_engine("sqlite://")
    try:
        app = create_app(OperationContext(engine, load_config(config), SYSTEM_ACTOR))
        routes = {
            (action.method, action_path(action)) for action in ACTIONS.values() if action.path
        }
        routes.update(
            (method, route.path) for route in app.routes for method in getattr(route, "methods", ())
        )
    finally:
        engine.dispose()
    patterns = [
        (method, re.compile(re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(path))))
        for method, path in routes
    ]
    missing = []
    for file, contents in live_documents():
        for method, path in ROUTE.findall(contents):
            # A trailing slash in prose denotes a route prefix, not an operation.
            if path.endswith(("/", "/...")):
                continue
            if not any(
                (not method or method == verb) and pattern.fullmatch(path.rstrip("."))
                for verb, pattern in patterns
            ):
                missing.append((file.relative_to(ROOT), method, path))
    assert not missing


def test_no_live_instruction_uses_removed_names():
    assert not [
        (file.relative_to(ROOT), match[0])
        for file, contents in live_documents()
        for match in REMOVED.finditer(contents)
    ]


def test_configuration_reference_covers_loader_inventory():
    reference = load("reference_pages").configuration_page()
    sections = dict(re.findall(r"^## `([^`]+)`\n(.*?)(?=^## |\Z)", reference, re.M | re.S))
    inventory = settings_by_section()
    inventory["Engine"] |= frozenset(map(shown, MANAGED_FIELDS))
    assert {
        section: frozenset(re.findall(r"^\| `([^`]+)` \|", content, re.M))
        for section, content in sections.items()
    } == inventory


def parser_commands(parser, prefix=""):
    yield prefix, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from parser_commands(child, f"{prefix} {name}".strip())


def test_cli_reference_renders_each_parsers_own_help(monkeypatch):
    page = StringIO()
    monkeypatch.setattr(mkdocs_gen_files, "open", lambda *args, **kwargs: nullcontext(page))
    monkeypatch.setattr(mkdocs_gen_files, "set_edit_path", lambda *args: None)
    monkeypatch.setenv("COLUMNS", "100")
    runpy.run_path(str(ROOT / "docs/gen_cli_page.py"))
    parts = re.split(r"^## `([^`]+)`\n", page.getvalue(), flags=re.M)
    sections = {"": parts[0]} | dict(zip(parts[1::2], parts[2::2], strict=True))
    for command, parser in parser_commands(build_parser()):
        assert f"```text\n{parser.format_help()}```" in sections.get(command, ""), command


def test_deployment_examples_use_the_cli_and_configuration_inventories(monkeypatch):
    import shlex

    import yaml

    from etl_craft.config import load_config

    deployment = ROOT / "docs/deploying"
    parser = build_parser()
    compose = yaml.safe_load((deployment / "compose/compose.yml").read_text())
    for service in compose["services"].values():
        if service["image"].startswith("ghcr.io/etl-craft/etl-craft:"):
            parser.parse_args(service["command"])
            probe = service["healthcheck"]["test"]
            if probe[:2] == ["CMD", "etl-craft"]:
                parser.parse_args(probe[2:])
    for path in (deployment / "kubernetes").glob("*.yml"):
        for resource in yaml.safe_load_all(path.read_text()):
            if resource["kind"] != "Deployment":
                continue
            for container in resource["spec"]["template"]["spec"]["containers"]:
                parser.parse_args(container["args"])
                for key in ("startupProbe", "readinessProbe", "livenessProbe"):
                    if (probe := container.get(key, {}).get("exec")) is not None:
                        executable, *arguments = probe["command"]
                        assert executable == "etl-craft"
                        parser.parse_args(arguments)
    for unit in (deployment / "systemd").glob("*.service"):
        line = next(line for line in unit.read_text().splitlines() if line.startswith("ExecStart="))
        executable, *arguments = shlex.split(line.partition("=")[2])
        assert Path(executable).name == "etl-craft"
        parser.parse_args(arguments)
    monkeypatch.setenv("ENGINE_PASSWORD", "deployment-test-password")
    load_config(deployment / "compose/engine.yml")
    load_config(deployment / "compose/agent.yml", agent=True)
