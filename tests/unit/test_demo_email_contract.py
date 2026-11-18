"""The installed demo checks exact email semantics against recorded task outcomes."""

import runpy
from pathlib import Path

import pytest

from etl_craft.core.enums import RunStatus

pytestmark = pytest.mark.unit
check = runpy.run_path(str(Path(__file__).parents[1] / "e2e/test_demo.py"))["expected_emails"]


class DemoEvidence:
    def __init__(self, attempts, status=RunStatus.SUCCESS, error=None):
        self.tasks = [("load", status, attempts, error)]

    def latest_run(self, pipeline):
        assert pipeline == "DEMO"
        return 7, RunStatus.SUCCESS

    def engine_rows(self, sql, **params):
        assert params == {"run": 7}
        return self.tasks


@pytest.mark.parametrize(
    ("attempts", "subject"),
    [
        (1, "[CUSTOM] DEMO: SUCCESS"),
        (2, "[CUSTOM] DEMO: COMPLETED_WITH_ERRORS"),
    ],
)
def test_demo_email_uses_recorded_retries(attempts, subject):
    assert subject in check(DemoEvidence(attempts))


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (RunStatus.SKIPPED, None),
        (RunStatus.IN_PROGRESS, None),
        (RunStatus.SUCCESS, "unexpected"),
    ],
)
def test_demo_does_not_accept_unexpected_task_outcomes(status, error):
    with pytest.raises(AssertionError):
        check(DemoEvidence(1, status, error))
