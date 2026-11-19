"""The deploy command reports each step and fails only when a step failed."""

import argparse
import io

import pytest

from etl_craft.cli.commands import deploy
from etl_craft.cli.output import Output
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import ExitCode
from etl_craft.services.config_files import ConfigSync
from etl_craft.services.operations.deploy import Deployment
from etl_craft.services.operations.seeds import SeedLoad

pytestmark = pytest.mark.unit


def render(monkeypatch, tmp_path, result, output_format="text"):
    (tmp_path / "craft-connector.yml").write_text("Secrets: {}\n")
    monkeypatch.setattr(deploy, "call", lambda *args: result)
    stream = io.StringIO()
    args = argparse.Namespace(
        output_format=output_format, project_dir=tmp_path, config=None, api="http://x", plan=False
    )
    return deploy.run(args, Output(stdout=stream)), stream.getvalue()


@pytest.mark.parametrize("status", tuple(SeedStatus))
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_seed_outcomes_are_reported_and_only_a_failed_load_fails(
    monkeypatch, tmp_path, status, output_format
):
    load = SeedLoad("warehouse.ds.agents", "load-id", status, "recorded message")
    synced = ConfigSync("bundle b1", "r1", True, False, ())
    result = Deployment(False, "b1", synced, ("warehouse.ds.agents",), (load,))
    code, text = render(monkeypatch, tmp_path, result, output_format)
    assert code == (ExitCode.FAILURE if status == SeedStatus.FAILED else ExitCode.SUCCESS)
    assert "recorded message" in text


def test_a_failed_config_stops_and_a_plan_lists_seed_tables(monkeypatch, tmp_path):
    failed = Deployment(False, "b1", ConfigSync("bundle b1", "r1", False, True, ()))
    code, text = render(monkeypatch, tmp_path, failed)
    assert code == ExitCode.FAILURE
    assert "validate failed the result" in text and "deployed" not in text
    plan = Deployment(True, None, ConfigSync("config", "r1", False, False, ()), ("w.s.t",))
    code, text = render(monkeypatch, tmp_path, plan)
    assert code == ExitCode.SUCCESS
    assert "plan only: nothing was changed" in text and "seed w.s.t: to load" in text
