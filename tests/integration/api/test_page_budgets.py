"""Statement budgets for the page feeds, independent of the number of task and pipeline rows."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.identity import authenticated_context
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run, task_run
from fixtures.round_trips import count_round_trips

BUDGETS = Path(__file__).parents[2] / "fixtures" / "sql-statement-budgets.json"


@pytest.fixture
def pages(engine_db):
    actor = Actor("owner", ActorKind.USER)
    ctx = OperationContext(engine_db.engine, engine_db.config, actor, role=ApiRole.ADMIN)
    with acting_as(actor), engine_db.engine.begin() as conn:
        grid = {}
        for code, task_count in (("SMALL", 2), ("LARGE", 26)):
            pipeline_id = add_pipeline(conn, code)
            tasks = [add_task(conn, pipeline_id, f"T{i}") for i in range(task_count)]
            for _ in range(25):
                run_id = start_run(conn, pipeline_id)
                for task_id in tasks:
                    task_run(conn, task_id, run_id)
                finish_run(conn, run_id)
            grid[code] = task_count * 25
    token = act(
        ctx, ActionName.TOKEN_CREATE, name="operator", role=ApiRole.OPERATOR, expires="365d"
    )
    operator = authenticated_context(ctx, token.metadata)
    return replace(operator, project="default", project_id=1), grid


def measured(ctx, action, **params):
    act(ctx, action, **params)
    with count_round_trips(ctx.engine) as counter:
        result = act(ctx, action, **params)
    return result, {k: v for k, v in counter.result().items() if k.startswith("engine_")}


def test_grid_statement_budget(pages):
    ctx, expected = pages
    budget = json.loads(BUDGETS.read_text())
    counts = []
    for code, cells in expected.items():
        view, count = measured(
            ctx, ActionName.HISTORY, pipeline_code=code, all=True, limit=25, cells=True
        )
        assert len(view.entries) == 25
        assert len(view.cells) == cells
        counts.append(count)
    assert counts[0] == counts[1]
    assert counts[1] == budget["pipeline_grid"][ctx.engine.dialect.name]


def test_capabilities_and_project_history_statement_budgets(pages):
    ctx, initial = pages
    budget = json.loads(BUDGETS.read_text())
    codes = list(initial)
    counts = []
    for pipeline_count in (2, 12):
        with acting_as(ctx.actor), ctx.engine.begin() as conn:
            for i in range(len(codes), pipeline_count):
                code = f"P{i}"
                start_run(conn, add_pipeline(conn, code))
                codes.append(code)
        view, capabilities = measured(
            ctx, ActionName.CAPABILITIES, definition=True, pipeline_codes=tuple(codes)
        )
        assert set(view.pipelines) == set(codes)
        history, project = measured(ctx, ActionName.HISTORY, all=True, limit=50)
        assert len(history.entries) == 50
        assert bool(history.before) == (pipeline_count > 2)
        counts.append((capabilities, project))
    assert counts[0] == counts[1]
    assert counts[1][0] == budget["pipeline_capabilities"][ctx.engine.dialect.name]
    assert counts[1][1] == budget["project_history"][ctx.engine.dialect.name]
