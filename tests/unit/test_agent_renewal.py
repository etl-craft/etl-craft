"""An agent's port-free health probe checks its own successful renewal evidence."""

import os

import pytest

from etl_craft.agent import renewal
from etl_craft.cli import main
from etl_craft.core.errors import ExitCode

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("age", "healthy"), [(None, False), (-1, False), (29, True), (30, False)])
def test_agent_health_needs_recent_local_renewal_without_api(
    tmp_path, monkeypatch, capsys, age, healthy
):
    monkeypatch.delenv("ETL_CRAFT_API", raising=False)
    monkeypatch.delenv("ETL_CRAFT_TOKEN", raising=False)
    config = tmp_path / "craft-connector.yml"
    config.touch()
    now = 100_000
    monkeypatch.setattr(renewal, "time", lambda: now)
    if age is not None:
        marker = renewal.renewal_marker(tmp_path)
        marker.touch()
        os.utime(marker, (now - age, now - age))
    assert main(["agent", "health", "--project-dir", str(tmp_path)]) == (
        ExitCode.SUCCESS if healthy else ExitCode.RUN_STATE
    )
    if not healthy:
        assert "check the agent" in capsys.readouterr().err
