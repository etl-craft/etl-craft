"""Render reference pages from the package's configuration, schemas and action contracts.

``docs/gen_reference_pages.py`` writes these pages into the documentation build.
"""

from __future__ import annotations

import ast
import re
from dataclasses import MISSING, Field, dataclass, field, fields, is_dataclass
from enum import Enum
from importlib import import_module
from importlib.machinery import SourceFileLoader
from importlib.util import find_spec
from inspect import getdoc, getsource
from pathlib import Path
from pkgutil import walk_packages
from textwrap import dedent
from types import UnionType
from typing import ClassVar, Literal, Union, get_args, get_origin, get_type_hints

import etl_craft
from etl_craft.cli.commands.migrate import MigrationResult
from etl_craft.config.loader import settings_by_section
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ConfigurationError
from etl_craft.dialects.warehouse.base import STORAGE_PARAMETERS
from etl_craft.handlers import (
    alert_message,
    event_wait,
    file_validation,
    python_scripts,
    run_pipeline,
)
from etl_craft.handlers.registry import COMMON_PARAMETERS
from etl_craft.handlers.sql.spec import FLAGS, SCREENED
from etl_craft.handlers.sql.spec import PARAMETERS as SQL_PARAMETERS
from etl_craft.services.catalog import document as catalog_document
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.actions import ACTIONS
from etl_craft.services.operations.requests import NoInput

REPO = Path(__file__).resolve().parents[1]
ANNOTATED = REPO / "docs" / "craft-connector.example.yml"
EXAMPLES = REPO / "docs" / "examples"
SCHEMA = REPO / "src" / "etl_craft" / "dialects" / "engine" / "postgres" / "schema.sql"
HANDLER_GUIDES = {
    "Every task": "../guides/pipelines-and-tasks.md#cfg_task_parameters",
    "SQL": "../guides/sql-tasks.md",
    "PYTHON": "../guides/python-scripts.md",
    "FILE_VALIDATION": "../guides/stewardship.md",
    "SQL_SCRIPT": "../guides/sql-scripts.md",
    "ALERT": "../guides/alerts.md",
    "EVENT_WAIT": "../guides/event-waits.md",
    "RUN_PIPELINE": "../guides/pipeline-triggers.md",
}


def written_in(key: str, text: str) -> bool:
    """Whether ``text`` (a YAML file) sets ``key``, or shows it commented out."""
    return re.search(rf"(^|\s|#\s*){re.escape(key)}:", text, re.MULTILINE) is not None


def setting_sources(key: str) -> list[str]:
    """Return the annotated reference, or else the examples, that show ``key``."""
    if written_in(key, ANNOTATED.read_text(encoding="utf-8")):
        return [ANNOTATED.name]
    return sorted(
        path.name for path in EXAMPLES.glob("*.yml") if written_in(key, path.read_text("utf-8"))
    )


def configuration_page() -> str:
    """Return the configuration reference: every setting, by section, and where it is shown."""
    lines = [
        "# craft-connector.yml",
        "",
        "Every setting the loader accepts, by section, generated from the loader itself. A key "
        "it does not accept stops every command with the key named. Each setting is explained "
        "where it is shown: the [annotated reference](../craft-connector.example.yml), or the "
        "[example](../examples/README.md) that uses it.",
        "",
        "`Orchestration` settings, and each section's `Profile`, may be written at the section "
        "level or in a profile block (`dev:`, `prod:`, ...); `Engine` and `Warehouse` "
        "connection fields are written in a profile block.",
        "",
    ]
    for section, keys in settings_by_section().items():
        lines += [f"## `{section}`", "", "| Setting | Shown in |", "|---|---|"]
        for key in sorted(keys, key=str.lower):
            shown = ", ".join(
                f"[`{name}`](../{'examples/' if name != ANNOTATED.name else ''}{name})"
                for name in setting_sources(key)
            )
            lines.append(f"| `{key}` | {shown} |")
        lines.append("")
    return "\n".join(lines)


def handler_parameters() -> dict[str, list[tuple[str, str]]]:
    """Return each handler's parameters, with what each applies to."""
    sql = []
    for name in sorted(SQL_PARAMETERS):
        if name in FLAGS:
            applies = ", ".join(f"`{action}`" for action in sorted(FLAGS[name]))
        elif name == "REJECT_LIMIT":
            applies = ", ".join(f"`{action}`" for action in sorted(SCREENED))
        elif name in STORAGE_PARAMETERS:
            applies = "where the table's files live"
        else:
            applies = ""
        sql.append((name, applies))
    alert = [
        (name, "EMAIL channels" if name in alert_message.EMAIL_PARAMETERS else "")
        for name in sorted(alert_message.PARAMETERS)
    ]
    return {
        "Every task": [(name, "") for name in sorted(COMMON_PARAMETERS)],
        "SQL": sql,
        "PYTHON": [(name, "") for name in sorted(python_scripts.PARAMETERS)],
        "FILE_VALIDATION": [(name, "") for name in sorted(file_validation.PARAMETERS)],
        "ALERT": alert,
        "EVENT_WAIT": [(name, "local mode") for name in sorted(event_wait.PARAMETERS)],
        "RUN_PIPELINE": [(name, "") for name in sorted(run_pipeline.PARAMETERS)],
    }


def task_parameters_page() -> str:
    """Return the task parameter reference: every name each handler reads."""
    lines = [
        "# Task parameters",
        "",
        "Every `CFG_TASK_PARAMETERS.PARAMETER_NAME` etl-craft reads, by handler, generated from "
        "the handlers themselves. Each is explained in its handler's guide. A `BUSINESS_RULES` "
        "task reads none of its own: its rules are rows of `CFG_BUSINESS_RULES`. A name no "
        "handler reads is a [`validate`](../guides/validating.md) warning.",
        "",
    ]
    for handler, params in handler_parameters().items():
        title = handler if handler == "Every task" else f"`{handler}`"
        lines += [
            f"## {title}",
            "",
            f"Explained in [its guide]({HANDLER_GUIDES[handler]}).",
            "",
            "| Parameter | Applies to |",
            "|---|---|",
        ]
        lines += [f"| `{name}` | {applies} |" for name, applies in params]
        lines.append("")
    return "\n".join(lines)


@dataclass
class Column:
    """One column of an Engine DB table."""

    name: str
    type: str
    nullable: bool = True
    default: str | None = None
    allowed: list[str] = field(default_factory=list)


@dataclass
class Table:
    """One Engine DB table, the comment above it, and its columns."""

    name: str
    comment: str
    columns: list[Column] = field(default_factory=list)
    unique: list[str] = field(default_factory=list)


_CREATE = re.compile(r"CREATE TABLE (\w+) \((.*?)\n\);", re.DOTALL)
_CHECK_IN = re.compile(r"CHECK \((\w+) IN \(([^)]*)\)\)")
_UNIQUE_INDEX = re.compile(r"CREATE UNIQUE INDEX \w+\s+ON (\w+) \(([^)]*)\)(?:\s+WHERE ([^;]+))?;")


def schema_tables(schema: Path = SCHEMA) -> list[Table]:
    """Read the tables of ``schema``: comments, columns, allowed values and unique keys."""
    text = schema.read_text(encoding="utf-8")
    tables: list[Table] = []
    for match in _CREATE.finditer(text):
        before = text[: match.start()].rstrip("\n").split("\n")
        comment: list[str] = []
        while before and before[-1].startswith("--"):
            comment.insert(0, before.pop()[2:].strip())
        table = Table(match.group(1), " ".join(comment))
        for raw in match.group(2).split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            if not re.match(r"^[A-Z_][A-Z_0-9]*\s", line):
                continue
            name, rest = line.split(None, 1)
            if name in {"CONSTRAINT", "CHECK", "CASE", "OR", "AND", "PRIMARY", "FOREIGN", "UNIQUE"}:
                continue
            type_ = re.split(
                r"\s+(NOT NULL|DEFAULT|REFERENCES|GENERATED|PRIMARY|CONSTRAINT|CHECK)", rest
            )[0]
            default = re.search(r"DEFAULT (.+?)(?:\s+REFERENCES|\s+CONSTRAINT|\s+CHECK|$)", rest)
            table.columns.append(
                Column(
                    name,
                    type_.strip(),
                    nullable="NOT NULL" not in rest and "PRIMARY KEY" not in rest,
                    default=default.group(1).strip() if default else None,
                )
            )
        for column, values in _CHECK_IN.findall(match.group(2)):
            for col in table.columns:
                if col.name == column:
                    col.allowed = [v.strip().strip("'") for v in values.split(",")]
        tables.append(table)
    by_name = {table.name: table for table in tables}
    for table_name, column in re.findall(r"ALTER TABLE (\w+) DROP COLUMN (\w+);", text):
        if table_name in by_name:
            table = by_name[table_name]
            table.columns = [value for value in table.columns if value.name != column]
    for name, columns, where in _UNIQUE_INDEX.findall(text):
        if name in by_name:
            key = ", ".join(c.strip() for c in columns.split(","))
            by_name[name].unique.append(key + (f" where {where.strip()}" if where else ""))
    return tables


def schema_page() -> str:
    """Return the Engine DB schema reference: every table and column, from the schema itself."""
    lines = [
        "# Engine DB schema",
        "",
        "Every table and column of the Engine DB, generated from the PostgreSQL schema etl-craft "
        "creates; the SQLite schema has the same tables and columns, in the same order, with "
        "SQLite's types. Your team writes pipeline metadata in the `CFG_` tables; "
        "etl-craft manages API tokens, the `AUD_` "
        "tables and `SCHEMA_MIGRATIONS`. See [Pipelines and tasks]"
        "(../guides/pipelines-and-tasks.md) and [The Engine DB](../connectors/engine-db.md).",
        "",
    ]
    for table in schema_tables():
        lines += [f"## `{table.name}`", ""]
        if table.comment:
            lines += [table.comment, ""]
        lines += ["| Column | Type | Null | Default | Allowed values |", "|---|---|---|---|---|"]
        for col in table.columns:
            default = col.default.replace("|", r"\|") if col.default else None
            lines.append(
                f"| `{col.name}` | `{col.type}` | {'yes' if col.nullable else 'no'} | "
                f"{f'`{default}`' if default else ''} | "
                f"{', '.join(f'`{v}`' for v in col.allowed)} |"
            )
        if table.unique:
            lines += ["", "Unique: " + "; ".join(f"`{key}`" for key in table.unique) + "."]
        lines.append("")
    return "\n".join(lines)


def actions_page() -> str:
    """Render each action's command, route, scope, role, audit and placement from its row."""
    from etl_craft.cli.commands import COMMANDS
    from etl_craft.core.enums import Audit, Placement
    from etl_craft.services.operations.actions import action_path

    commands: dict[str, list[str]] = {}
    for command in COMMANDS:
        for name in command.actions:
            commands.setdefault(name, []).append(f"`{command.name}`")
    lines = [
        "# Actions",
        "",
        "Every action has one row in `etl_craft.services.operations.actions`. The CLI and the",
        "HTTP API reach it through `invoke`, which checks the role and records the request; this",
        "page is generated from that table.",
        "",
        "| Action | Command | HTTP route | Scope | Role | Audited | Runs |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, action in sorted(ACTIONS.items()):
        route = f"`{action.method} {action_path(action)}`" if action.path else "—"
        audited = {Audit.NONE: "no", Audit.REQUEST: "yes", Audit.BY_ACTION: "yes, by the action"}
        where = "anywhere" if action.placement == Placement.ANYWHERE else "controller's host"
        lines.append(
            f'| <a id="action-{action_anchor(name)}"></a>[`{name}`](#{action_anchor(name)}) | '
            f"{', '.join(commands.get(name, [])) or '—'} | {route} | "
            f"{action.scope} | {action.role or 'none'} | {audited[action.audit]} | {where} |"
        )
    lines += ["", "## Requests and responses", ""]
    documents = document_classes()
    for name, action in sorted(ACTIONS.items()):
        lines += action_details(name, action, documents)
    return "\n".join(lines)


# The CLI wraps the operation's migration list in cli/commands/migrate.py.
HOST_JSON = {ActionName.MIGRATE: MigrationResult}
NON_DOCUMENT_IDENTIFIERS: frozenset[str] = frozenset()
OTHER_DOCUMENTS = {
    "etl-craft/alert/1": (
        "The outbound webhook payload is produced by `services.operations.alert_delivery`. "
        "See [Webhook JSON and signature](../guides/alerts.md#webhook-json-and-signature)."
    ),
    "etl-craft/bundle-manifest/1": (
        "The stored manifest is produced by `services.operations.bundles.publish`. "
        "See [Project bundles](../deploying/project-bundles.md)."
    ),
    catalog_document.SCHEMA: "See [Catalog document shape 2](catalog-document.md).",
}


def document_classes() -> dict[str, type]:
    """Discover schema-bearing dataclasses in their defining modules."""
    documents: dict[str, type] = {}
    for module in walk_packages(etl_craft.__path__, "etl_craft."):
        # Docs-only builds omit warehouse extras, so inspect source before importing candidates.
        spec = find_spec(module.name)
        if spec is None or not isinstance(spec.loader, SourceFileLoader):
            continue
        source = spec.loader.get_source(module.name) or ""
        if not re.search(r"^\s+SCHEMA\s*:", source, re.MULTILINE):
            continue
        for cls in vars(import_module(module.name)).values():
            if not isinstance(cls, type) or cls.__module__ != module.name or not is_dataclass(cls):
                continue
            schema = getattr(cls, "SCHEMA", None)
            if (
                isinstance(schema, str)
                and get_origin(get_type_hints(cls).get("SCHEMA")) is ClassVar
            ):
                if schema in documents:
                    raise ConfigurationError(f"{schema}: multiple JSON document classes")
                documents[schema] = cls
    return documents


def action_anchor(name: ActionName) -> str:
    return name.replace(" ", "-")


def document_anchor(schema: str) -> str:
    return schema.removeprefix("etl-craft/").replace("/", "-")


def action_documents(action: Action, documents: dict[str, type]) -> list[str]:
    """Find the published documents for an action, including union alternatives."""
    result = HOST_JSON.get(action.name, action.result)
    if result is None or action.streams:
        return []
    options = get_args(result) if get_origin(result) in (Union, UnionType) else (result,)
    schemas = []
    for cls in options:
        schema = getattr(cls, "SCHEMA", None)
        if isinstance(schema, str) and documents.get(schema) is cls:
            schemas.append(schema)
        elif action.method is not None or action.name in HOST_JSON:
            raise ConfigurationError(
                f"action {action.name}: result {cls} must be a documented JSON document class"
            )
    return schemas


def display_type(hint: object, links: dict[type, str]) -> str:
    origin, args = get_origin(hint), get_args(hint)
    if isinstance(hint, type) and hint in links:
        return f"[`{hint.__name__}`]({links[hint]})"
    if origin in (Union, UnionType):
        members = [display_type(item, links) for item in args if item is not type(None)]
        union = members[0] if len(members) == 1 else f"Union[{', '.join(members)}]"
        return f"Optional[{union}]" if type(None) in args else union
    if origin is Literal:
        return "`Literal[" + ", ".join(repr(item).replace("|", r"\|") for item in args) + "]`"
    if origin is not None:
        return f"{origin.__name__}[" + ", ".join(display_type(item, links) for item in args) + "]"
    if hint is Ellipsis:
        return "`...`"
    return f"`{getattr(hint, '__name__', str(hint))}`"


def request_default(item: Field[object]) -> str:
    if item.default is not MISSING:
        value = item.default.value if isinstance(item.default, Enum) else item.default
        return "`" + repr(value).replace("|", r"\|") + "`"
    if item.default_factory is not MISSING:
        factory = getattr(item.default_factory, "__name__", "factory")
        return f"`{factory}()`"
    return "—"


def action_details(name: ActionName, action: Action, documents: dict[str, type]) -> list[str]:
    schemas = action_documents(action, documents)
    response = ", ".join(f"[`{s}`](json-documents.md#{document_anchor(s)})" for s in schemas)
    if name in HOST_JSON:
        response = f"JSON output of `etl-craft {name} --json` ({response})"
    elif action.streams:
        response = "a byte stream"
    elif action.method is not None and action.result is None:
        response = "no content (204)"
    elif not response:
        response = "No JSON document (host-only)"
    lines = [f"### `{name}` {{ #{action_anchor(name)} }}", "", f"**Response:** {response}", ""]
    try:
        hints = get_type_hints(action.request)
        request = [item for item in fields(action.request) if item.init]
        if action.request is NoInput:
            return [*lines, "**Request:** none", ""]
        lines += ["| Request field | Type | Default | Required |", "| --- | --- | --- | --- |"]
        for item in request:
            required = item.default is MISSING and item.default_factory is MISSING
            lines.append(
                f"| `{item.name}` | {display_type(hints[item.name], {})} | "
                f"{request_default(item)} | {'yes' if required else 'no'} |"
            )
    except (NameError, TypeError, KeyError) as error:
        raise ConfigurationError(
            f"action {name}: cannot resolve request fields: {error}"
        ) from error
    return [*lines, ""]


def nested_types(hint: object) -> list[type]:
    if isinstance(hint, type) and is_dataclass(hint):
        return [hint]
    return [cls for arg in get_args(hint) for cls in nested_types(arg)]


def attribute_docstrings(cls: type) -> dict[str, str]:
    """Read the string literals immediately following annotated field definitions."""
    descriptions = {}
    for base in reversed(cls.__mro__):
        if not is_dataclass(base):
            continue
        node = ast.parse(dedent(getsource(base))).body[0]
        assert isinstance(node, ast.ClassDef)
        for assignment, following in zip(node.body, node.body[1:], strict=False):
            if (
                isinstance(assignment, ast.AnnAssign)
                and isinstance(assignment.target, ast.Name)
                and isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                descriptions[assignment.target.id] = following.value.value.strip()
    return descriptions


def result_table(cls: type, links: dict[type, str]) -> list[str]:
    doc = getdoc(cls)
    lines = [doc.splitlines()[0], ""] if doc and not doc.startswith(f"{cls.__name__}(") else []
    lines += ["| Field | Type | Description |", "| --- | --- | --- |"]
    schema = getattr(cls, "SCHEMA", None)
    if isinstance(schema, str):
        lines.append(f"| `schema` | `str` | `{schema}` |")
    hints = get_type_hints(cls)
    assert is_dataclass(cls)
    descriptions = attribute_docstrings(cls)
    for item in fields(cls):
        description = (
            getattr(item, "doc", None)
            or item.metadata.get("description")
            or descriptions.get(item.name, "")
        )
        description = description.partition("\n")[0].replace("|", r"\|")
        lines.append(f"| `{item.name}` | {display_type(hints[item.name], links)} | {description} |")
    return [*lines, ""]


def json_documents_page() -> str:
    """Render every versioned JSON document with links to the actions that return it."""
    documents = document_classes()
    returned_by: dict[str, list[str]] = {}
    for name, action in sorted(ACTIONS.items()):
        for schema in action_documents(action, documents):
            returned_by.setdefault(schema, []).append(
                f"[`{name}`](actions.md#action-{action_anchor(name)})"
            )
    links = {cls: f"#{document_anchor(schema)}" for schema, cls in documents.items()}
    lines = [
        "# JSON documents",
        "",
        "Versioned JSON documents generated from the code. Dates use ISO 8601 strings,",
        "enums use their values, and tuples are JSON arrays.",
        "",
    ]
    for schema in sorted(documents.keys() | OTHER_DOCUMENTS.keys()):
        _, kind, version = schema.split("/")
        lines += [
            f"## {kind} (version {version}) {{ #{document_anchor(schema)} }}",
            "",
            f"`{schema}`",
            "",
        ]
        if schema in OTHER_DOCUMENTS:
            lines += [OTHER_DOCUMENTS[schema], ""]
            continue
        cls = documents[schema]
        nested = [cls]
        for shape in nested:
            for hint in get_type_hints(shape).values():
                for item in nested_types(hint):
                    if item not in links:
                        qualified_name = f"{item.__module__}.{item.__qualname__}".replace(
                            ".", "-"
                        ).lower()
                        links[item] = f"#fields-{qualified_name}"
                        nested.append(item)
        lines += result_table(cls, links)
        lines += ["**Returned by:** " + (", ".join(returned_by.get(schema, [])) or "—"), ""]
        for item in nested[1:]:
            lines += [f"### `{item.__name__}` {{ {links[item]} }}", "", *result_table(item, links)]
    return "\n".join(lines)
