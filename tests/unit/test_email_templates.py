"""Email templates are confined, escaped and strictly sandboxed before SMTP."""

from dataclasses import replace
from pathlib import Path

import pytest

from etl_craft.config import ConnectionProfile, ConnectorConfig, SourceConfig
from etl_craft.core.errors import EtlCraftError

pytestmark = pytest.mark.unit


def config():
    return ConnectorConfig(
        source=SourceConfig(type="environment"),
        engine=ConnectionProfile("ENGINE", "dev", "jdbc:sqlite:e.db", "main", "NONE"),
    )


def template(tmp_path, content, name="custom.html"):
    root = tmp_path / "email_templates"
    root.mkdir(exist_ok=True)
    (root / name).write_text(content)
    return replace(
        config(), config_path=tmp_path / "craft-connector.yml"
    ), "email_templates/" + name


def test_custom_template_is_escaped_and_full_error_is_preserved(tmp_path):
    from etl_craft.handlers.email_templates import context_example, render

    cfg, name = template(tmp_path, "{{ environment.label }} {{ body }} {{ errors[0] }}")
    data = context_example()
    data.update(body="<script>bad</script>\nsecond line", errors=["failure " * 2000])
    result = render(cfg, name, data)
    assert "&lt;script&gt;bad&lt;/script&gt;\nsecond line" in result
    assert "failure " * 2000 in result
    assert "PRODUCTION" in result


@pytest.mark.parametrize(
    "attack",
    [
        "{{ ''.__class__.__mro__ }}",
        "{{ environment.__class__ }}",
        "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
        "{% include '/etc/passwd' %}",
        "{% autoescape false %}{{ body }}{% endautoescape %}",
    ],
)
def test_sandbox_escape_is_refused(tmp_path, attack):
    from etl_craft.handlers.email_templates import context_example, render

    cfg, name = template(tmp_path, attack)
    with pytest.raises(EtlCraftError, match=r"template.*line.*(correct|documented)"):
        render(cfg, name, context_example())


@pytest.mark.parametrize("name", ["/etc/passwd.html", "email_templates/../outside.html"])
def test_paths_cannot_leave_templates(tmp_path, name):
    from etl_craft.handlers.email_templates import context_example, render

    with pytest.raises(EtlCraftError):
        render(
            replace(config(), config_path=tmp_path / "craft-connector.yml"), name, context_example()
        )


def test_symlink_cannot_leave_templates(tmp_path):
    from etl_craft.handlers.email_templates import context_example, render

    cfg, name = template(tmp_path, "hello")
    outside = tmp_path / "outside.html"
    outside.write_text("secret")
    (tmp_path / name).unlink()
    (tmp_path / name).symlink_to(outside)
    with pytest.raises(EtlCraftError, match="outside"):
        render(cfg, name, context_example())


@pytest.mark.parametrize(
    "body",
    [
        "line one\n{{ unknown }}",
        "line one\n{% if %}",
        "{% if false %}\n{{ run.missing }}{% endif %}",
    ],
)
def test_validate_names_file_line_and_remedy(tmp_path, body):
    from etl_craft.handlers.email_templates import validate_templates

    cfg, name = template(tmp_path, body)
    problems = validate_templates(cfg, {"EMAIL_TEMPLATE": name})
    assert len(problems) == 1
    assert name in problems[0]
    assert "line 2" in problems[0]
    assert "documented" in problems[0]


@pytest.mark.parametrize("outcome", ["FAILED", "SUCCESS", "SLA"])
def test_builtin_email_snapshots(outcome):
    from etl_craft.handlers.email_templates import render
    from fixtures.email_cases import email_case

    data = email_case(outcome)
    rendered = render(config(), None, data)
    expected = Path(__file__).parents[1] / "fixtures/email_snapshots" / (outcome.lower() + ".html")
    assert rendered == expected.read_text()
