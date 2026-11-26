"""An agent's port-free health probe checks its own successful renewal evidence."""

import os
import subprocess
import sys

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


PROBE = """
import sys
from etl_craft.cli import main
status = main(sys.argv[1:])
heavy = ("sqlalchemy", "etl_craft.cli.commands", "etl_craft.services")
heavy = sorted(m for m in heavy if m in sys.modules)
print("loaded:", ",".join(heavy) or "-")
raise SystemExit(status)
"""


@pytest.mark.parametrize("fresh", [True, False])
def test_the_health_probe_answers_without_loading_the_command_tree(tmp_path, fresh):
    (tmp_path / "craft-connector.yml").touch()
    if fresh:
        renewal.renewal_marker(tmp_path).touch()
    done = subprocess.run(
        [sys.executable, "-c", PROBE, "agent", "health", "--project-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == (ExitCode.SUCCESS if fresh else ExitCode.RUN_STATE), done.stderr
    assert "loaded: -" in done.stdout
    if not fresh:
        assert "error: " in done.stderr and "renewal evidence unavailable" in done.stderr


def test_other_health_forms_get_the_full_command_line(tmp_path, capsys):
    (tmp_path / "craft-connector.yml").touch()
    both = ["agent", "health", "--project-dir", str(tmp_path), "--config", "x.yml"]
    assert main(both) == ExitCode.USAGE
    assert "choose --project-dir or --config" in capsys.readouterr().err
