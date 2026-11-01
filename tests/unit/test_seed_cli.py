"""Seed command results preserve messages and fail only for failed table loads."""

import argparse
import io

import pytest

from etl_craft.cli.commands import seed
from etl_craft.cli.output import Output
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import ExitCode
from etl_craft.services.operations.seeds import SeedLoad, SeedLoads

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status", tuple(SeedStatus))
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_seed_command_reports_recorded_outcomes_and_exit_code(monkeypatch, status, output_format):
    result = SeedLoads((SeedLoad("warehouse.ds.agents", "load-id", status, "recorded message"),))
    monkeypatch.setattr(seed, "call", lambda *args: result)
    stream = io.StringIO()
    code = seed.run(argparse.Namespace(output_format=output_format), Output(stdout=stream))
    assert code == (ExitCode.FAILURE if status == SeedStatus.FAILED else ExitCode.SUCCESS)
    assert "recorded message" in stream.getvalue()
