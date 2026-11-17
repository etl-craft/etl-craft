"""Team-named sensitive parameters hide their values; resolved secrets are masked everywhere."""

import json

import pytest

from etl_craft.core.redaction import (
    DEFAULT_SENSITIVE_PATTERNS,
    mask_log,
    mask_text,
    public_parameters,
    remember,
)
from etl_craft.handlers.parameters import package_parameters

pytestmark = pytest.mark.unit

BASE = (
    "Secrets:\n  Source_type: ENVIRONMENT\nOrchestration:\n"
    "Engine:\n  dev:\n    Jdbc_url: jdbc:sqlite:e.db\n    Schema: main\n"
)


def test_patterns_hide_team_names_and_input_param_keys_but_never_package_names():
    shown = public_parameters(
        {
            "MERGE_KEY": "customer_id",
            "SQL_ACTION": "SCD1_MERGE",
            "api_token": "tok-123",
            "Db_Password": "hunter22",
            "REGION": "eu",
            "INPUT_PARAMS": json.dumps({"vendor_secret": "abc", "days": 30}),
        },
        DEFAULT_SENSITIVE_PATTERNS,
        package_parameters(),
    )
    assert shown["MERGE_KEY"] == "customer_id" and shown["SQL_ACTION"] == "SCD1_MERGE"
    assert shown["api_token"] == shown["Db_Password"] == "[REDACTED]"
    assert shown["REGION"] == "eu"
    assert json.loads(shown["INPUT_PARAMS"]) == {"vendor_secret": "[REDACTED]", "days": 30}


def test_custom_patterns_replace_the_defaults_and_bad_json_is_left_for_validation():
    shown = public_parameters(
        {"ACCOUNT_REF": "x-1", "api_token": "kept", "INPUT_PARAMS": "{not json"},
        ("*_REF",),
        package_parameters(),
    )
    assert shown == {"ACCOUNT_REF": "[REDACTED]", "api_token": "kept", "INPUT_PARAMS": "{not json"}


def test_a_resolved_secret_is_masked_in_later_logs_only_and_short_values_are_not():
    remember("resolved-warehouse-password-9")
    remember("abc")
    assert mask_log("login with resolved-warehouse-password-9 failed") == (
        "login with [REDACTED] failed"
    )
    assert mask_log("abc def") == "abc def"
    # Results and errors keep exact text: a secret that is an ordinary word cannot rewrite them.
    assert mask_text("resolved-warehouse-password-9") == "resolved-warehouse-password-9"


def test_a_resolved_connection_secret_is_masked_in_later_log_text(tmp_path, monkeypatch):
    import logging

    from etl_craft.config import load_config, resolve_secret
    from etl_craft.core.log import ContextFilter

    monkeypatch.setenv("ENGINE_USER", "etl_engine")
    monkeypatch.setenv("ENGINE_SECRET", "env-resolved-secret-55")
    path = tmp_path / "craft-connector.yml"
    path.write_text(
        "Secrets:\n  Source_type: ENVIRONMENT\nOrchestration:\nEngine:\n  dev:\n"
        "    Jdbc_url: jdbc:postgresql://localhost:5432/etl_craft\n    Schema: public\n"
        "    User: ENGINE_USER\n    Auth_mode: PASSWORD\n    Secret: ENGINE_SECRET\n",
        encoding="utf-8",
    )
    config = load_config(path)
    resolve_secret(config, config.engine)
    record = logging.LogRecord(
        "t", logging.INFO, "f", 1, "dsn=%s", ("env-resolved-secret-55",), None
    )
    ContextFilter().filter(record)
    assert "env-resolved-secret-55" not in record.getMessage()


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("Redaction:\n  Sensitive_patterns: TOKEN\n", "expected a list of name globs"),
        ("Redaction:\n  Patterns: [x]\n", "unknown key"),
    ],
)
def test_redaction_settings_are_checked(tmp_path, section, message):
    from etl_craft.config import load_config
    from etl_craft.core.errors import ConfigurationError

    path = tmp_path / "craft-connector.yml"
    path.write_text(BASE + section, "utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_config(path)


def test_redaction_defaults_and_custom_patterns_load(tmp_path):
    from etl_craft.config import load_config

    path = tmp_path / "craft-connector.yml"
    path.write_text(BASE, "utf-8")
    assert load_config(path).sensitive_patterns == DEFAULT_SENSITIVE_PATTERNS
    path.write_text(
        BASE + "Redaction:\n  Sensitive_patterns: ['*_REF']\n",
        "utf-8",
    )
    assert load_config(path).sensitive_patterns == ("*_REF",)
