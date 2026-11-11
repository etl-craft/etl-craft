"""AUTO_RESTART_CONDITION and Allowed_auto_restarts: what may start a pipeline on its own."""

import pytest

from etl_craft.core.enums import RunStatus
from etl_craft.core.errors import MetadataFileError
from etl_craft.core.restart import parse_auto_restart, restart_statuses, schedule_allowed

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("NONE", "NONE"),
        ("SCHEDULE", "SCHEDULE"),
        ("ALWAYS", "ALWAYS"),
        ("SUCCESS", "SUCCESS"),
        ("SUCCESS|SCHEDULE", "SCHEDULE|SUCCESS"),
        ("FAILURE|SKIPPED|SUCCESS", "SUCCESS|SKIPPED|FAILURE"),
        ("ALWAYS|SCHEDULE", "SCHEDULE|ALWAYS"),
    ],
)
def test_a_value_is_read_in_one_canonical_order(written, canonical):
    assert parse_auto_restart(written) == canonical


@pytest.mark.parametrize(
    ("written", "message"),
    [
        ("success", r"'success', which is not one of NONE, SCHEDULE, SUCCESS, SKIPPED, FAILURE"),
        ("SUCCESS|", r"'', which is not one of"),
        ("SUCCESS|SUCCESS", "repeats a value"),
        ("NONE|SUCCESS", "combines NONE with another value"),
        ("ALWAYS|FAILURE", "names an ending beside ALWAYS"),
    ],
)
def test_a_bad_value_is_refused_naming_the_value_and_the_remedy(written, message):
    with pytest.raises(MetadataFileError, match=message):
        parse_auto_restart(written)


def test_the_endings_that_restart_a_run_never_include_a_cancel():
    assert restart_statuses("NONE") == frozenset()
    assert restart_statuses("SCHEDULE") == frozenset()
    assert restart_statuses("SCHEDULE|SUCCESS|SKIPPED") == {RunStatus.SUCCESS, RunStatus.SKIPPED}
    assert restart_statuses("FAILURE") == {RunStatus.FAILED}
    assert restart_statuses("ALWAYS") == {RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.FAILED}
    assert RunStatus.CANCELLED not in restart_statuses("ALWAYS")


def test_schedule_ticks_start_runs_only_when_schedule_is_named():
    assert schedule_allowed("SCHEDULE") and schedule_allowed("SCHEDULE|ALWAYS")
    assert not schedule_allowed("NONE") and not schedule_allowed("SUCCESS|SKIPPED")
