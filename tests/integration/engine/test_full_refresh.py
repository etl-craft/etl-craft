"""A one-time full refresh: what it covers, what it asks to confirm, and what it records."""

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ApiRole, RefreshType
from etl_craft.core.errors import ConfirmationRequiredError, UsageError
from etl_craft.core.full_refresh import FullRefresh
from etl_craft.engine import runlog, transitions
from etl_craft.engine.run_creation import RunCreation, create
from etl_craft.execution.context import build_task_context
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.full_refresh import plan
from etl_craft.services.operations.requests import RunRequest
from fixtures.metadata import add_dependency, add_pipeline, add_task, task_run

LOAD = {
    "SQL_ACTION": "APPEND_TABLE",
    "WATERMARK_COLUMN": "id",
    "WATERMARK_TYPE": "NUMBER",
    "WATERMARK_START": "0",
    "SELECT_QUERY": "SELECT 1 AS id",
}


@pytest.fixture
def scene(engine_db):
    """ingest and load feed merge, which report reads; report overwrites, so never refreshes."""
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET REFRESH_TYPE='INCREMENTAL' WHERE PIPELINE_ID=:id"),
            {"id": pipeline},
        )
        ingest = add_task(conn, pipeline, "ingest", "PYTHON", SCRIPT_FILE="ingest.py")
        load = add_task(conn, pipeline, "load", "SQL", TARGET_OBJECT="mart.orders", **LOAD)
        merge = add_task(
            conn,
            pipeline,
            "merge",
            "SQL",
            TARGET_OBJECT="mart.facts",
            **{**LOAD, "SQL_ACTION": "SCD1_MERGE", "MERGE_KEY": "id"},
        )
        report = add_task(
            conn,
            pipeline,
            "report",
            "SQL",
            TARGET_OBJECT="mart.report",
            SQL_ACTION="OVERWRITE_TABLE",
            SELECT_QUERY="SELECT 1 AS id",
        )
        add_dependency(conn, pipeline, merge, load)
        add_dependency(conn, pipeline, report, merge)
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    return ctx, pipeline, {"ingest": ingest, "load": load, "merge": merge, "report": report}


def refresh(**values):
    values.setdefault("reason", "profile history corrected")
    return RunRequest(pipeline_code="P", full_refresh=True, **values)


def test_a_whole_pipeline_refresh_asks_before_emptying_an_append_target(scene):
    ctx, _, _ = scene
    with pytest.raises(ConfirmationRequiredError) as asked:
        plan(ctx, refresh())
    assert asked.value.targets == ("mart.orders",)
    message = str(asked.value)
    assert "load: mart.orders" in message and "merge" not in message
    assert "empty_targets" in message and "cannot restore" in message
    assert plan(ctx, refresh(empty_targets=("mart.orders",))) == FullRefresh(None, ("mart.orders",))


@pytest.mark.parametrize(
    "given", [("mart.facts",), ("mart.orders", "mart.facts"), ("MART.ORDERS",)]
)
def test_a_confirmation_must_name_exactly_the_targets_that_would_be_emptied(scene, given):
    ctx, _, _ = scene
    with pytest.raises(ConfirmationRequiredError) as asked:
        plan(ctx, refresh(empty_targets=given))
    assert asked.value.targets == ("mart.orders",)


def test_a_task_scope_covers_that_task_and_optionally_what_reads_it(scene):
    ctx, _, _ = scene
    # merge is a merge, so nothing is emptied and nothing needs confirming.
    assert plan(ctx, refresh(task_code="merge")) == FullRefresh(("merge",), ())
    assert plan(ctx, refresh(task_code="merge", with_downstream=True)) == FullRefresh(
        ("merge", "report"), ()
    )
    # load appends, and merge reads it: the append target is asked about.
    with pytest.raises(ConfirmationRequiredError):
        plan(ctx, refresh(task_code="load", with_downstream=True))
    confirmed = refresh(task_code="load", with_downstream=True, empty_targets=("mart.orders",))
    assert plan(ctx, confirmed) == FullRefresh(("load", "merge", "report"), ("mart.orders",))


def test_a_refresh_of_tasks_that_read_everything_anyway_is_refused(scene):
    ctx, _, _ = scene
    with pytest.raises(UsageError, match="refresh of report has nothing to refresh"):
        plan(ctx, refresh(task_code="report"))


def test_an_append_target_with_another_writer_is_refused_before_asking(scene):
    ctx, pipeline, _ = scene
    with ctx.engine.begin() as conn:
        add_task(conn, pipeline, "extra", "SQL", TARGET_OBJECT="mart.orders", **LOAD)
    with pytest.raises(UsageError, match=r"mart\.orders.*also written by extra"):
        plan(ctx, refresh(empty_targets=("mart.orders",)))


def test_the_run_records_its_plan_and_each_task_sees_only_its_own_scope(scene):
    ctx, pipeline, tasks = scene
    chosen = FullRefresh(("load", "merge"), ("mart.orders",))
    with ctx.engine.begin() as conn:
        run = create(conn, pipeline, SYSTEM_ACTOR, RunCreation(full_refresh=chosen))
        runs = {code: task_run(conn, task, run) for code, task in tasks.items()}
        row = conn.execute(
            text(
                "SELECT FULL_REFRESH AS flag, FULL_REFRESH_PLAN AS plan FROM AUD_PIPELINES_RUN_LOG"
            )
        ).one()
        assert row.flag == "Y" and FullRefresh.deserialize(row.plan) == chosen
        assert runlog.fetch_run_kind(conn, run).full_refresh
    seen = {
        code: build_task_context(ctx.engine, ctx.config, task_run_id)
        for code, task_run_id in runs.items()
    }
    assert {code: c.full_refresh for code, c in seen.items()} == {
        "ingest": False,
        "load": True,
        "merge": True,
        "report": False,
    }
    assert seen["load"].refresh_type == RefreshType.FULL
    assert seen["load"].empty_targets == ("mart.orders",)
    assert seen["report"].refresh_type == RefreshType.INCREMENTAL


def test_a_run_without_a_plan_is_an_ordinary_run(scene):
    ctx, pipeline, tasks = scene
    with ctx.engine.begin() as conn:
        run = transitions.create_run(conn, pipeline, SYSTEM_ACTOR)
        loaded = task_run(conn, tasks["load"], run)
        assert not runlog.fetch_run_kind(conn, run).full_refresh
    context = build_task_context(ctx.engine, ctx.config, loaded)
    assert not context.full_refresh and context.empty_targets == ()


def test_the_database_refuses_a_plan_without_the_flag_and_the_flag_without_a_plan(scene):
    ctx, pipeline, _ = scene
    with ctx.engine.begin() as conn:
        run = transitions.create_run(conn, pipeline, SYSTEM_ACTOR)
    for statement in (
        "UPDATE AUD_PIPELINES_RUN_LOG SET FULL_REFRESH_PLAN='{}' WHERE PIPELINE_RUN_ID=:run",
        "UPDATE AUD_PIPELINES_RUN_LOG SET FULL_REFRESH='Y' WHERE PIPELINE_RUN_ID=:run",
    ):
        with (
            pytest.raises(Exception, match=r"(?i)ck_run_full_refresh_plan|check|violat"),
            ctx.engine.begin() as conn,
        ):
            conn.execute(text(statement), {"run": run})


def test_admission_records_the_run_before_it_executes_and_hands_on_exactly_that_run(scene):
    from etl_craft.services.operations.full_refresh import admit

    ctx, pipeline, _ = scene
    request = admit(ctx, refresh(task_code="merge", with_downstream=True))
    assert not request.full_refresh and request.task_code is None and request.empty_targets == ()
    with ctx.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS id, STATUS AS status, FULL_REFRESH AS flag, "
                "FULL_REFRESH_PLAN AS plan FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:p"
            ),
            {"p": pipeline},
        ).one()
    assert request.run_id == row.id and row.status == "QUEUED" and row.flag == "Y"
    assert FullRefresh.deserialize(row.plan) == FullRefresh(("merge", "report"), ())


def test_admission_refuses_while_another_run_is_active_and_writes_nothing(scene):
    from etl_craft.core.errors import RunStateError
    from etl_craft.services.operations.full_refresh import admit

    ctx, pipeline, _ = scene
    with ctx.engine.begin() as conn:
        busy = transitions.create_run(conn, pipeline, SYSTEM_ACTOR)
    with pytest.raises(RunStateError, match=rf"pipeline_run_id={busy} is IN-PROGRESS.*own run"):
        admit(ctx, refresh(task_code="merge"))
    with ctx.engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one()
    assert count == 1


def test_admission_asks_before_it_writes_anything(scene):
    from etl_craft.services.operations.full_refresh import admit

    ctx, _, _ = scene
    with pytest.raises(ConfirmationRequiredError):
        admit(ctx, refresh())
    with ctx.engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one()
    assert count == 0


def test_two_simultaneous_full_refreshes_admit_exactly_one_run(scene):
    from etl_craft.core.errors import RunStateError
    from etl_craft.services.operations.full_refresh import admit
    from fixtures.races import two_at_once

    ctx, _, _ = scene

    def attempt():
        try:
            return admit(ctx, refresh(task_code="merge"))
        except RunStateError as refused:
            return refused

    outcomes = two_at_once(attempt, attempt, at="etl_craft.services.operations.full_refresh.plan")
    assert sorted(type(o).__name__ for o in outcomes) == ["RunRequest", "RunStateError"]
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 1
