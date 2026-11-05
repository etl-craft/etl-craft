"""Sandboxed email templates over a documented, JSON-shaped context only."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from importlib import resources

from jinja2 import StrictUndefined, TemplateError, meta, nodes
from jinja2.sandbox import SandboxedEnvironment

from etl_craft.config import ConnectorConfig
from etl_craft.config.project import project_file
from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import EtlCraftError, HandlerError


class EmailSandbox(SandboxedEnvironment):
    """No Python attributes or calls; dictionary fields remain available as Jinja variables."""

    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:
        """Refuse Python attributes, including all dunder traversal."""
        return False

    def is_safe_callable(self, obj: object) -> bool:
        """Refuse calls even to otherwise exposed built-ins."""
        return False


def sandbox() -> EmailSandbox:
    """No includes/imports, globals, safe-HTML filter or autoescape overrides."""
    env = EmailSandbox(autoescape=True, undefined=StrictUndefined)
    env.globals.clear()
    env.filters.pop("safe", None)
    env.filters.pop("attr", None)
    return env


def source(config: ConnectorConfig, name: str | None, *, text: bool = False) -> tuple[str, str]:
    """Resolve team files through the project's confined file helper."""
    if name:
        directory = config.project_dir / "email_templates"
        if directory.is_symlink() or not directory.resolve().is_relative_to(
            config.project_dir.resolve()
        ):
            raise HandlerError(
                f"email template {name}: line 1: email_templates/ is a symlink or resolves "
                "outside the project; "
                f"replace the symlink with a local directory"
            )
        try:
            path = project_file(
                directory, name, setting="email template", suffix=".txt" if text else ".html"
            )
        except (EtlCraftError, OSError, ValueError) as error:
            raise HandlerError(
                f"email template {name!r}: line 1: {error}; correct the confined path "
                "under email_templates/ and run validate"
            ) from error
        try:
            return path.read_text(encoding="utf-8"), name
        except (OSError, UnicodeError) as error:
            raise HandlerError(
                f"email template {name}: line 1: unreadable UTF-8 ({type(error).__name__}); "
                "correct the file and validate again"
            ) from error
    filename = "default.txt" if text else "default.html"
    return resources.files("etl_craft.handlers").joinpath("email_templates", filename).read_text(
        encoding="utf-8"
    ), filename


_UNKNOWN = object()


def check_fields(tree: nodes.Template, filename: str) -> None:
    """Check field paths even in branches that the validation example does not execute."""

    def value(node: nodes.Node, scope: dict[str, object]) -> object:
        if isinstance(node, nodes.Name):
            return scope.get(node.name, _UNKNOWN)
        if isinstance(node, (nodes.Getattr, nodes.Getitem)):
            base = value(node.node, scope)
            key = (
                node.attr
                if isinstance(node, nodes.Getattr)
                else node.arg.value
                if isinstance(node.arg, nodes.Const)
                else _UNKNOWN
            )
            if isinstance(base, dict) and isinstance(key, str):
                if key not in base:
                    raise HandlerError(
                        f"email template {filename}: line {node.lineno}: undefined field {key!r}; "
                        "use the documented email context"
                    )
                found: object = base[key]
                return found
        return _UNKNOWN

    def visit(node: nodes.Node, scope: dict[str, object]) -> None:
        value(node, scope)
        if isinstance(node, nodes.Call):
            raise HandlerError(
                f"email template {filename}: line {node.lineno}: calls are forbidden; "
                "use only documented context fields"
            )
        if isinstance(node, nodes.For) and isinstance(node.target, nodes.Name):
            iterable = value(node.iter, scope)
            if isinstance(iterable, list) and iterable:
                scope = {**scope, node.target.name: iterable[0]}
        for child in node.iter_child_nodes():
            visit(child, scope)

    visit(tree, context_example())


def render(
    config: ConnectorConfig, name: str | None, context: Mapping[str, object], *, text: bool = False
) -> str:
    """Render completely before SMTP; never send a fallback or partially rendered message."""
    content, filename = source(config, name, text=text)
    env = sandbox()
    try:
        tree = env.parse(content)
        forbidden = next(
            (
                n
                for n in tree.find_all(nodes.Node)
                if isinstance(
                    n,
                    (
                        nodes.Include,
                        nodes.Import,
                        nodes.FromImport,
                        nodes.Extends,
                        nodes.EvalContextModifier,
                        nodes.ScopedEvalContextModifier,
                    ),
                )
            ),
            None,
        )
        if forbidden is not None:
            raise HandlerError(
                f"email template {filename}: line {forbidden.lineno}: includes, imports "
                "and autoescape "
                f"changes are forbidden; use only documented context fields"
            )
        check_fields(tree, filename)
        unknown = meta.find_undeclared_variables(tree) - (context.keys() | {"body_lines"})
        if unknown:
            token = next(n for n in tree.find_all(nodes.Name) if n.name in unknown)
            raise HandlerError(
                f"email template {filename}: line {token.lineno}: undefined name "
                f"{token.name!r}; use the documented email context"
            )
        # Serialization rejects Python objects instead of handing their methods to Jinja.
        data = json.loads(json.dumps(context, allow_nan=False))
        data["body_lines"] = data.get("body", "").splitlines()
        rendered = env.from_string(content).render(data)
        return html.unescape(rendered) if text else rendered
    except TemplateError as error:
        line = getattr(error, "lineno", None)
        if line is None:
            import traceback

            line = next(
                (
                    frame.lineno
                    for frame in reversed(traceback.extract_tb(error.__traceback__))
                    if frame.filename == "<template>"
                ),
                1,
            )
        raise HandlerError(
            f"email template {filename}: line {line}: {error}; correct the template using "
            f"the documented context and run validate"
        ) from error


def context_example() -> dict[str, object]:
    """Return the complete validation shape, including rows in optional tables."""
    task = {
        "code": "load",
        "status": RunStatus.FAILED,
        "symbol": "✕",
        "color": "#b42318",
        "error": "example error",
        "attempts": 1,
    }
    return {
        "environment": {"type": "PROD", "name": "production", "label": "PRODUCTION"},
        "project": {"code": "example"},
        "pipeline": {"code": "load"},
        "run": {
            "id": 1,
            "logical_date": "2026-01-01",
            "start": "2026-01-01T00:00:00+00:00",
            "end": None,
            "duration": "1.00 seconds",
            "status": RunStatus.FAILED,
            "symbol": "✕",
            "color": "#b42318",
        },
        "task": {"code": "alert", "run_id": 2, "status": RunStatus.IN_PROGRESS, "attempt": 1},
        "errors": ["example error"],
        "watched_tasks": [task],
        "pipelines": [
            {
                "code": "load",
                "run_id": 1,
                "status": RunStatus.FAILED,
                "start": None,
                "end": None,
                "tasks": [task],
            }
        ],
        "sla": {"hours": 1, "elapsed_hours": 2, "message": "SLA missed"},
        "version": "example",
        "recipients": ["team@example.com"],
        "recipient_reason": "EMAIL_TO on the alert task",
        "subject": "Example",
        "body": "Example body",
        "body_lines": ["Example body"],
    }


def validate_templates(config: ConnectorConfig, params: Mapping[str, str]) -> list[str]:
    """Parse/render every referenced template against the complete documented shape."""
    problems = []
    for name, text, is_sla in (
        (params.get("EMAIL_TEMPLATE"), False, False),
        (params.get("EMAIL_TEMPLATE_TEXT"), True, False),
        (config.email_template, False, True),
    ):
        if not name:
            continue
        data = context_example()
        if is_sla:
            data["task"] = None
        try:
            render(config, name, data, text=text)
            if not is_sla:
                data["sla"] = None
                render(config, name, data, text=text)
        except EtlCraftError as error:
            problems.append(str(error))
    return problems
