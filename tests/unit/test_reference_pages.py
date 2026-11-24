"""The generated reference pages list exactly what the code reads, and every name is explained."""

import re
from dataclasses import fields, is_dataclass
from typing import get_args

import pytest

from etl_craft.config.loader import settings_by_section
from fixtures.scripts import load

pytestmark = pytest.mark.unit

pages = load("reference_pages")
GUIDES = pages.REPO / "docs" / "guides"
GUIDE_FILES = {
    "Every task": "pipelines-and-tasks.md",
    "SQL": "sql-tasks.md",
    "PYTHON": "python-scripts.md",
    "FILE_VALIDATION": "stewardship.md",
    "ALERT": "alerts.md",
    "EVENT_WAIT": "event-waits.md",
    "RUN_PIPELINE": "pipeline-triggers.md",
}
SCHEMAS = pages.REPO / "src" / "etl_craft" / "dialects" / "engine"


def test_every_setting_is_shown_in_the_annotated_reference_or_an_example():
    unshown = [
        f"{section}.{key}"
        for section, keys in settings_by_section().items()
        for key in keys
        if not pages.setting_sources(key)
    ]
    assert unshown == []
    email = settings_by_section()["Orchestration.Email"]
    annotated = pages.ANNOTATED.read_text(encoding="utf-8")
    assert [key for key in email if not pages.written_in(key, annotated)] == []


def test_every_task_parameter_is_explained_in_its_handlers_guide():
    unexplained = []
    for handler, params in pages.handler_parameters().items():
        guide = (GUIDES / GUIDE_FILES[handler]).read_text(encoding="utf-8")
        for name, _ in params:
            named = re.search(rf"\b{name}\b", guide)
            if not named and f"`{pages.OUTCOME_PATTERNS.get(name)}`" not in guide:
                unexplained.append(f"{handler}: {name}")
    assert unexplained == []


def test_the_parameter_page_lists_what_each_handler_reads():
    page = pages.task_parameters_page()
    assert "| `SCHEMA_EVOLUTION` | `OVERWRITE_TABLE`, `SCD1_MERGE`, `SCD2_MERGE` |" in page
    assert "| `SCRIPT_FILE` |  |" in page
    assert "| `EMAIL_PIPELINES` | EMAIL channels |" in page
    assert "| `TASK_TIMEOUT_SECONDS` |  |" in page
    assert "| `REQUIRE_UPLOADS` |  |" in page


@pytest.mark.parametrize("dialect", ["postgres", "sqlite"])
def test_every_engine_db_table_is_described_and_read_whole(dialect):
    tables = pages.schema_tables(SCHEMAS / dialect / "schema.sql")
    text = (SCHEMAS / dialect / "schema.sql").read_text(encoding="utf-8")
    assert [t.name for t in tables] == re.findall(r"^CREATE TABLE (\w+)", text, re.MULTILINE)
    assert [t.name for t in tables if not t.comment] == []
    for table in tables:
        body = re.search(rf"CREATE TABLE {table.name} \((.*?)\n\);", text, re.DOTALL).group(1)
        declared = [
            line.split()[0]
            for line in body.splitlines()
            if re.match(r"^\s+[A-Z_][A-Z_0-9]*\s", line)
            and line.split()[0]
            not in {"CONSTRAINT", "CHECK", "CASE", "OR", "AND", "PRIMARY", "FOREIGN", "UNIQUE"}
        ]
        assert [c.name for c in table.columns] == declared, table.name
        if table.name in {"CFG_ACCESS_BINDINGS", "AUD_CFG_ACCESS_BINDINGS_HISTORY"}:
            columns = {column.name for column in table.columns}
            assert {"ROLE_NAME", "ACCOUNT_ID", "GRANTEE_ROLE"} <= columns
            assert not {"ROLE", "CASE"} & columns
        if table.name == "CFG_BUSINESS_RULES":
            assert "TARGET_TABLE_ID" in [column.name for column in table.columns]
            assert "TARGET_TABLE" not in [column.name for column in table.columns]


def test_the_schema_page_shows_types_allowed_values_and_unique_keys():
    page = pages.schema_page()
    assert "## `AUD_RUN_INTERVENTIONS`" in page
    assert "## `AUD_TASK_ATTEMPTS`" in page
    assert "## `AUD_GATE_DECISIONS`" in page
    assert "| `CONFIG_SHA256` | `VARCHAR(64)` |" in page
    assert "| `CONSUME_REPAIRS` | `VARCHAR(1)` | no | `'Y'` | `Y`, `N` |" in page
    assert "| `REFRESH_TYPE` | `VARCHAR` | no |  | `FULL`, `INCREMENTAL` |" in page
    assert "Unique: `PROJECT_ID, PIPELINE_CODE`." in page
    assert "| `ACTIVE_FLAG` | `VARCHAR` | no | `'Y'` | `Y`, `N` |" in page


def test_the_configuration_page_has_every_section():
    page = pages.configuration_page()
    for section in settings_by_section():
        assert f"## `{section}`" in page
    assert "| `Dependency_gates` | [`craft-connector.example.yml`]" in page


def test_bundle_ownership_and_approval_columns_include_their_final_constraints():
    tables = {table.name: table for table in pages.schema_tables()}
    columns = {column.name: column for column in tables["AUD_PROJECT_BUNDLES"].columns}
    assert not columns["PROJECT_ID"].nullable
    assert columns["PROJECT_ID"].default == "1"
    assert not columns["CONNECTIONS_SHA256"].nullable
    assert columns["CONNECTIONS_APPROVED_FLAG"].allowed == ["Y", "N"]


def test_every_versioned_json_identifier_has_a_reference_section():
    pattern = r"etl-craft/[a-z0-9_-]+/[0-9]+\b"
    literals = {
        identifier
        for path in (pages.REPO / "src").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        for identifier in re.findall(pattern, path.read_text(encoding="utf-8", errors="ignore"))
    }
    page = pages.json_documents_page()
    rendered = set(re.findall(rf"^`({pattern})`$", page, re.MULTILINE))
    assert literals - rendered == pages.NON_DOCUMENT_IDENTIFIERS
    assert rendered <= literals
    assert "| `mapped` | tuple[" in page
    assert "Managed columns whose values come from the SELECT." in page
    nested_anchors = re.findall(r"\n### .* \{ #(fields-[^ ]+) \}", page)
    assert nested_anchors
    assert len(nested_anchors) == len(set(nested_anchors))
    assert set(re.findall(r"\]\(#(fields-[^)]+)\)", page)) == set(nested_anchors)


def test_every_action_documents_its_request_and_response():
    actions = pages.actions_page()
    documents = pages.json_documents_page()
    for name, action in pages.ACTIONS.items():
        start = f"### `{name}` {{ #{pages.action_anchor(name)} }}"
        assert start in actions, name
        section = actions.split(start, 1)[1].split("\n### ", 1)[0]
        if action.request is pages.NoInput:
            assert "**Request:** none" in section, name
        for item in fields(action.request):
            if item.init:
                assert f"| `{item.name}` |" in section, name
        if action.streams:
            assert "**Response:** a byte stream" in section, name
        elif action.method is not None and action.result is None:
            assert "**Response:** no content (204)" in section, name
        elif action.method is not None:
            for cls in get_args(action.result) or (action.result,):
                assert isinstance(cls, type) and is_dataclass(cls), name
                schema = getattr(cls, "SCHEMA", None)
                assert isinstance(schema, str) and f"\n`{schema}`\n" in documents, name
                assert (
                    f"[`{schema}`](json-documents.md#{pages.document_anchor(schema)})" in section
                ), name
    for name in (pages.ActionName.SETUP, pages.ActionName.INIT_DB):
        section = actions.split(f"### `{name}` ", 1)[1].split("\n### ", 1)[0]
        assert "**Response:** No JSON document (host-only)" in section, name
    for name, cls in pages.HOST_JSON.items():
        assert is_dataclass(cls) and isinstance(cls.SCHEMA, str), name
        assert f"\n`{cls.SCHEMA}`\n" in documents, name
        assert f"JSON output of `etl-craft {name} --json`" in actions, name
