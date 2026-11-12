"""Declared script credentials resolve without exposing provider values."""

from types import SimpleNamespace

import pytest

from etl_craft.config import SourceConfig
from etl_craft.core.enums import SecretsSource
from etl_craft.core.errors import PermanentError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("provider", [SecretsSource.ENVIRONMENT, SecretsSource.FILE])
def test_declared_secret_and_refusals(tmp_path, monkeypatch, provider):
    from etl_craft.handlers.task_secrets import resolve
    from etl_craft.scripting import ScriptTask

    value = "private-value-that-must-not-escape"
    path = tmp_path / "provider.env"
    path.write_text("SOURCE_TOKEN=" + value + "\n")
    monkeypatch.setenv("SOURCE_TOKEN", value)
    task = SimpleNamespace(
        config=SimpleNamespace(source=SourceConfig(provider, str(path))),
        pipeline_code="P",
        task_code="load",
        task_params={"SECRETS": "SOURCE_TOKEN"},
    )
    values = resolve(task)
    task._secret_values = values
    task._secret_provider = None
    assert ScriptTask.secret(task, "SOURCE_TOKEN") == value
    for name in ("NOT_DECLARED", "MISSING"):
        changed = (
            task
            if name == "NOT_DECLARED"
            else SimpleNamespace(**(vars(task) | {"task_params": {"SECRETS": "MISSING"}}))
        )
        with pytest.raises(PermanentError) as error:
            ScriptTask.secret(changed, name) if name == "NOT_DECLARED" else resolve(changed)
        assert all(part in str(error.value) for part in ("P.load", name, str(provider)))
        assert value not in str(error.value)


def test_validation_refuses_literal_undeclared_name(tmp_path, monkeypatch):
    from etl_craft.handlers.task_secrets import problems

    monkeypatch.setenv("SOURCE_TOKEN", "private-example")
    task = SimpleNamespace(
        config=SimpleNamespace(source=SourceConfig(SecretsSource.ENVIRONMENT)),
        pipeline_code="P",
        task_code="load",
        task_params={"SECRETS": "SOURCE_TOKEN"},
    )
    path = tmp_path / "load.py"
    path.write_text('def run(task):\n    return task.secret("OTHER_TOKEN")\n')
    with pytest.raises(PermanentError, match=r"P.load.*OTHER_TOKEN.*ENVIRONMENT.*SECRETS"):
        problems(task, path)


def test_provider_payload_is_bounded_without_echoing_values(monkeypatch):
    from etl_craft.handlers.task_secrets import resolve

    monkeypatch.setenv("LARGE_TOKEN", "x" * (1024 * 1024))
    task = SimpleNamespace(
        config=SimpleNamespace(source=SourceConfig(SecretsSource.ENVIRONMENT)),
        pipeline_code="P",
        task_code="load",
        task_params={"SECRETS": "LARGE_TOKEN"},
    )
    with pytest.raises(PermanentError, match=r"P.load.*ENVIRONMENT.*1 MiB.*reduce") as error:
        resolve(task)
    assert "xxxxx" not in str(error.value)


def test_channel_agent_claim_never_reads_task_secret_declaration():
    from etl_craft.core.enums import Handler
    from etl_craft.services.operations.task_secrets import for_claim

    task = SimpleNamespace(
        handler=Handler.EMAIL_ALERT,
        pipeline_code="P",
        task_code="notify",
        task_params={"ALERT_CHANNEL": "ops", "SECRETS": "not a variable declaration"},
    )
    assert for_claim(SimpleNamespace(), task) == {}
