"""The request and plan of a one-time full refresh, before any database is involved."""

from datetime import date

import pytest

from etl_craft.core.errors import UsageError
from etl_craft.core.full_refresh import FullRefresh
from etl_craft.services.operations.requests import RunRequest

pytestmark = pytest.mark.unit


def refresh(**values):
    values.setdefault("reason", "profile history corrected")
    return RunRequest(pipeline_code="P", full_refresh=True, **values)


@pytest.mark.parametrize(
    "values",
    [
        {"backfill_from": date(2026, 1, 1), "backfill_to": date(2026, 1, 2)},
        {"skip": True},
        {"force": True},
        {"rerun": True, "task_code": "load"},
        {"standalone": True, "task_code": "load"},
        {"params": ("load.WATERMARK_START=0",), "request_key": "k"},
        {"run_id": 7},
    ],
)
def test_a_full_refresh_starts_its_own_run_and_refuses_the_other_run_options(values):
    with pytest.raises(UsageError, match="starts its own run"):
        refresh(**values)


def test_a_full_refresh_needs_a_reason_and_empty_targets_need_a_full_refresh():
    with pytest.raises(UsageError, match="needs a `reason`"):
        RunRequest(pipeline_code="P", full_refresh=True)
    with pytest.raises(UsageError, match="confirms a full refresh"):
        RunRequest(pipeline_code="P", empty_targets=("mart.orders",))


def test_a_task_code_only_narrows_the_scope_of_a_full_refresh():
    request = refresh(task_code="load", with_downstream=True)
    assert request.task_code == "load" and request.with_downstream


@pytest.mark.parametrize(
    "plan",
    [FullRefresh(), FullRefresh(("a", "b"), ("mart.orders",)), FullRefresh(None, ("x", "y"))],
)
def test_a_plan_round_trips_through_its_stored_form(plan):
    assert FullRefresh.deserialize(plan.serialize()) == plan


def test_a_plan_covers_every_task_unless_it_names_some():
    assert FullRefresh().covers("anything")
    named = FullRefresh(("load",))
    assert named.covers("load") and not named.covers("report")
