"""Task environment is an allowlist shared by both launchers."""

from dataclasses import replace
from pathlib import Path

import pytest

from etl_craft.config import parse_config
from etl_craft.config.model import SettingSource
from etl_craft.execution.child_environment import child_environment

pytestmark = pytest.mark.unit


def test_children_never_receive_agent_token(monkeypatch):
    config = parse_config(
        {
            "Secrets": {"Source_type": "ENVIRONMENT"},
            "Engine": {"dev": {"Jdbc_url": "jdbc:sqlite::memory:", "Schema": "main"}},
        },
        Path("craft-connector.yml"),
    )
    config = replace(
        config,
        settings=(SettingSource("Warehouse.dev.Secret", "WAREHOUSE_SECRET", "WAREHOUSE_SECRET"),),
    )
    for name in (
        "ETL_CRAFT_TOKEN",
        "ETL_CRAFT_REFRESH_TOKEN",
        "UNRELATED_SECRET",
        "WAREHOUSE_SECRET",
        "PATH",
        "HOME",
        "LC_ALL",
    ):
        monkeypatch.setenv(name, "test-value")
    environment = child_environment(config)
    assert {"ETL_CRAFT_TOKEN", "ETL_CRAFT_REFRESH_TOKEN", "UNRELATED_SECRET"}.isdisjoint(
        environment
    )
    for name in ("WAREHOUSE_SECRET", "PATH", "HOME", "LC_ALL"):
        assert environment[name] == "test-value"


def test_privacy_secret_stays_on_the_host_not_in_agent_children(monkeypatch):
    from dataclasses import replace

    from etl_craft.config import ConnectionProfile
    from fixtures.engine_db import engine_config

    config = replace(
        engine_config(ConnectionProfile("ENGINE", "dev", "jdbc:sqlite:engine.db", "", "NONE")),
        privacy_hmac_secret="PROJECT_PRIVACY",
    )
    monkeypatch.setenv("PROJECT_PRIVACY", "host-only-secret")
    assert child_environment(config, host=True)["PROJECT_PRIVACY"] == "host-only-secret"
    assert "PROJECT_PRIVACY" not in child_environment(config)
    config = replace(
        config,
        settings=(SettingSource("Warehouse.dev.Secret", "PROJECT_PRIVACY", "PROJECT_PRIVACY"),),
    )
    assert "PROJECT_PRIVACY" not in child_environment(config)
