"""Run input records retain their values after configuration edits."""

from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ApiRole
from etl_craft.core.errors import UsageError
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import RunRequest
from fixtures.metadata import add_pipeline, add_task


@pytest.fixture
def scene(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "load", "PYTHON", INPUT_PARAMS='{"day":1}')
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    return ctx, pipeline, task


def request(**values):
    return RunRequest(
        pipeline_code="P",
        params=('load.INPUT_PARAMS={"day":2}',),
        request_key="one",
        init_only=True,
        **values,
    )


def test_recorded_values_and_duplicate_submission_ignore_later_metadata(scene):
    from etl_craft.engine.repository.tasks import admitted_parameters
    from etl_craft.engine.run_definitions import read
    from etl_craft.services.operations.run_parameters import admit

    ctx, _pipeline, task = scene
    selected, run_id, duplicate = admit(ctx, request())
    assert selected.run_id == run_id and not duplicate
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='changed' "
                "WHERE TASK_ID=:task AND PARAMETER_NAME='INPUT_PARAMS'"
            ),
            {"task": task},
        )
    assert admit(ctx, request())[1:] == (run_id, True)
    with ctx.engine.connect() as conn:
        definition, _ = read(conn, run_id)
        assert admitted_parameters(definition, task)["INPUT_PARAMS"] == '{"day":2}'
        assert (
            conn.execute(text("SELECT COUNT(*) FROM AUD_RUN_PARAMETER_OVERRIDES")).scalar_one() == 1
        )
    from etl_craft.engine.repository.tasks import fetch_all_task_parameters
    from etl_craft.engine.run_definitions import for_run

    with for_run(ctx.engine, run_id), ctx.engine.connect() as conn:
        assert fetch_all_task_parameters(conn)[task]["INPUT_PARAMS"] == '{"day":2}'
    with pytest.raises(UsageError, match="payload differs"):
        admit(ctx, replace(request(), params=('load.INPUT_PARAMS={"day":3}',)))


@pytest.mark.parametrize(
    "params", [("missing.INPUT_PARAMS={}",), ("load.UNKNOWN=x",), ("load.INPUT_PARAMS=not-json",)]
)
def test_bad_run_inputs_refused_before_admission(scene, params):
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, _ = scene
    with pytest.raises(UsageError):
        admit(ctx, replace(request(), params=params))
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0


def test_absent_overrides_keep_base_parameters(scene):
    from etl_craft.engine import run_overrides, transitions
    from etl_craft.engine.repository.tasks import admitted_parameters
    from etl_craft.engine.run_definitions import read

    ctx, pipeline, task = scene
    with ctx.engine.begin() as conn:
        run = transitions.create_run(conn, pipeline, SYSTEM_ACTOR)
        definition, _ = read(conn, run)
        assert run_overrides.recorded(conn, run) == {}
        assert admitted_parameters(definition, task)["INPUT_PARAMS"] == '{"day":1}'


def test_override_requires_submission_key_and_new_run(scene):
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, _ = scene
    for changes in ({"request_key": None}, {"run_id": 42}, {"skip": True}):
        with pytest.raises(UsageError):
            admit(ctx, replace(request(), **changes))


def test_restart_copies_inputs_and_refuses_incompatible_new_base(scene):
    from etl_craft.core.enums import ControlAction, RunStatus
    from etl_craft.engine import run_overrides, transitions
    from etl_craft.engine.runlog import RunSelector, select_run
    from etl_craft.services.operations.recovery import prepare_recovery
    from etl_craft.services.operations.requests import ControlRequest
    from etl_craft.services.operations.run_parameters import admit, copy_for_restart

    ctx, pipeline, task = scene
    _, source, _ = admit(ctx, request())
    with ctx.engine.begin() as conn:
        transitions.finalize_pipeline_run(conn, source, RunStatus.FAILED)
        selected = select_run(conn, pipeline, RunSelector(run_id=source))
        prepare_recovery(
            conn,
            ctx,
            selected,
            ControlRequest(
                pipeline_code="P", run_id=source, action=ControlAction.RESTART, reason="test"
            ),
            100,
        )
        replacement = select_run(conn, pipeline, RunSelector(run_key="control-restart:100"))
        assert run_overrides.recorded(conn, replacement.pipeline_run_id) == {
            "load": {"INPUT_PARAMS": '{"day":2}'}
        }
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET ACTIVE_FLAG='N' WHERE "
                "TASK_ID=:task AND PARAMETER_NAME='INPUT_PARAMS'"
            ),
            {"task": task},
        )
        with pytest.raises(UsageError, match="existing data-input"):
            copy_for_restart(conn, source, pipeline)


def test_duplicate_override_admissions_race_to_one_record(scene):
    from etl_craft.services.operations.run_parameters import admit
    from fixtures.races import two_at_once

    ctx, _, _ = scene
    answers = two_at_once(
        lambda: admit(ctx, request()), lambda: admit(ctx, request()), at=(ctx.engine, "begin")
    )
    assert answers[0][1] == answers[1][1]
    assert sorted(answer[2] for answer in answers) == [False, True]


def test_effective_parameters_reach_retry_scope_and_dispatched_task_context(scene):
    from etl_craft.engine import transitions
    from etl_craft.engine.repository.tasks import fetch_task_parameters
    from etl_craft.engine.run_definitions import for_run
    from etl_craft.execution.context import build_task_context
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, task = scene
    _, run, _ = admit(ctx, request())
    with ctx.engine.begin() as conn:
        binding = transitions.find_or_create_task_run(conn, task, run)
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='current' WHERE "
                "TASK_ID=:task AND PARAMETER_NAME='INPUT_PARAMS'"
            ),
            {"task": task},
        )
    with for_run(ctx.engine, run), ctx.engine.connect() as conn:
        assert fetch_task_parameters(conn, task)["INPUT_PARAMS"] == '{"day":2}'
    context = build_task_context(ctx.engine, ctx.config, binding.task_run_id)
    assert context.task_params["INPUT_PARAMS"] == '{"day":2}'


def test_shared_run_operation_returns_recorded_admission_and_refuses_viewer(scene):
    from etl_craft.core.enums import ActionName
    from etl_craft.core.errors import PermissionDeniedError
    from etl_craft.services.operations.actions import invoke

    ctx, _, _ = scene
    with pytest.raises(PermissionDeniedError):
        invoke(
            replace(ctx, role=ApiRole.VIEWER),
            ActionName.RUN,
            replace(request(), reason="override test"),
        )
    first = invoke(ctx, ActionName.RUN, replace(request(), reason="override test"))
    duplicate = invoke(ctx, ActionName.RUN, replace(request(), reason="override test"))
    assert duplicate.run.pipeline_run_id == first.run.pipeline_run_id
    assert duplicate.run.parameter_overrides == {"load": {"INPUT_PARAMS": '{"day":2}'}}


@pytest.mark.parametrize(
    "name,value",
    [
        ("ALLOW_EMPTY", "maybe"),
        ("REJECT_LIMIT", "not-a-count"),
        ("WATERMARK_START", "not-a-number"),
    ],
)
def test_sql_input_types_use_handler_validation_before_creation(scene, name, value):
    from etl_craft.services.operations.run_parameters import admit

    ctx, pipeline, _ = scene
    with ctx.engine.begin() as conn:
        add_task(
            conn,
            pipeline,
            "sql_load",
            "SQL",
            SQL_ACTION="APPEND_TABLE",
            ALLOW_EMPTY="Y",
            REJECT_LIMIT="1%",
            WATERMARK_START="0",
            WATERMARK_TYPE="NUMBER",
            WATERMARK_COLUMN="id",
        )
    with pytest.raises(UsageError) as caught:
        admit(ctx, replace(request(), params=(f"sql_load.{name}={value}",)))
    for part in ("sql_load", name, value, "correct --param"):
        assert part in str(caught.value)
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0


def test_submission_keys_and_task_names_are_isolated_by_project(scene):
    from etl_craft.engine.repository.pipelines import selected_project
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, _ = scene
    _, first, _ = admit(ctx, request())
    with ctx.engine.begin() as conn:
        project = conn.execute(
            text(
                "INSERT INTO CFG_PROJECTS "
                "(PROJECT_CODE,PROJECT_NAME,DEFAULT_POOL) VALUES "
                "('OTHER','Other','default') RETURNING PROJECT_ID"
            )
        ).scalar_one()
        pipeline = add_pipeline(conn, "P", project_id=project)
        add_task(conn, pipeline, "load", "PYTHON", INPUT_PARAMS='{"day":9}')
    with selected_project(project):
        _, second, duplicate = admit(replace(ctx, project_id=project, project="OTHER"), request())
    assert first != second and not duplicate
    with ctx.engine.connect() as conn:
        ids = (
            conn.execute(
                text(
                    "SELECT PROJECT_ID AS project FROM "
                    "AUD_RUN_PARAMETER_OVERRIDES ORDER BY PIPELINE_RUN_ID"
                )
            )
            .scalars()
            .all()
        )
        assert ids == [1, project]


def test_automatic_retry_keeps_override_and_pinned_retry_budget(scene):
    from datetime import UTC, datetime, timedelta

    from etl_craft.core.enums import AttemptStatus, FailureClass
    from etl_craft.core.failures import Failure
    from etl_craft.engine import transitions
    from etl_craft.execution.context import build_task_context
    from etl_craft.execution.retries import refresh_retries
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, task = scene
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO "
                "CFG_TASK_PARAMETERS(TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "VALUES(:task,'RETRIES','2')"
            ),
            {"task": task},
        )
    _, run, _ = admit(ctx, request())
    with ctx.engine.begin() as conn:
        transitions.admit_run(conn, run, SYSTEM_ACTOR)
        summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
        attempt = transitions.queue_attempt(conn, summary, SYSTEM_ACTOR)
        transitions.claim_attempt(
            conn,
            attempt,
            SYSTEM_ACTOR,
            owner="first",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        transitions.record_attempt_failure(
            conn, attempt, Failure(FailureClass.TRANSIENT, "TransientError")
        )
        transitions.finish_attempt(conn, attempt, AttemptStatus.FAILED, SYSTEM_ACTOR, owner="first")
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='0' WHERE "
                "TASK_ID=:task AND PARAMETER_NAME='RETRIES'"
            ),
            {"task": task},
        )
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='current' WHERE "
                "TASK_ID=:task AND PARAMETER_NAME='INPUT_PARAMS'"
            ),
            {"task": task},
        )
    waiting, exhausted = refresh_retries(ctx.engine, ctx.config, run, {task})
    assert task in waiting and not exhausted
    context = build_task_context(ctx.engine, ctx.config, summary)
    assert context.task_params["INPUT_PARAMS"] == '{"day":2}'
    assert context.task_params["RETRIES"] == "2"


def test_standalone_sql_run_records_inputs_with_its_existing_selection(scene):
    from etl_craft.engine.repository.tasks import admitted_parameters
    from etl_craft.engine.run_definitions import read
    from etl_craft.engine.run_scopes import fetch_selection
    from etl_craft.services.operations.run_parameters import admit

    ctx, pipeline, _ = scene
    with ctx.engine.begin() as conn:
        task = add_task(
            conn, pipeline, "sql_load", "SQL", SQL_ACTION="CREATE_TABLE", ALLOW_EMPTY="false"
        )
    selected, run, duplicate = admit(
        ctx,
        replace(
            request(),
            init_only=False,
            standalone=True,
            task_code="sql_load",
            params=("sql_load.ALLOW_EMPTY=true",),
        ),
    )
    assert selected.run_id == run and not duplicate
    with ctx.engine.connect() as conn:
        assert fetch_selection(conn, run).task_ids == (task,)
        definition, _ = read(conn, run)
        assert admitted_parameters(definition, task)["ALLOW_EMPTY"] == "true"


def test_run_and_override_record_roll_back_together_after_an_interrupted_write(scene):
    from sqlalchemy import event

    from etl_craft.services.operations.run_parameters import admit

    ctx, _, _ = scene

    def interrupted(conn, cursor, sql, parameters, context, executemany):
        if "INSERT INTO AUD_RUN_PARAMETER_OVERRIDES" in sql.upper():
            raise RuntimeError("simulated crash after override insert")

    event.listen(ctx.engine, "after_cursor_execute", interrupted)
    try:
        with pytest.raises(RuntimeError, match="simulated crash"):
            admit(ctx, request())
    finally:
        event.remove(ctx.engine, "after_cursor_execute", interrupted)
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0
        assert (
            conn.execute(text("SELECT COUNT(*) FROM AUD_RUN_PARAMETER_OVERRIDES")).scalar_one() == 0
        )


def test_override_admission_uses_the_project_timezone_for_implicit_run_date(scene, monkeypatch):
    from datetime import date

    from etl_craft.engine import runlog
    from etl_craft.services.operations.run_parameters import admit

    ctx, _, _ = scene
    ctx = replace(ctx, config=replace(ctx.config, timezone="Asia/Kolkata"))
    monkeypatch.setattr(
        runlog,
        "today",
        lambda zone="UTC": date(2026, 11, 12) if zone == "Asia/Kolkata" else date(2026, 11, 11),
    )
    _, run, _ = admit(ctx, request())
    with ctx.engine.connect() as conn:
        logical = conn.execute(
            text(
                "SELECT RUN_DATE AS logical_date FROM AUD_PIPELINES_RUN_LOG "
                "WHERE PIPELINE_RUN_ID=:run"
            ),
            {"run": run},
        ).scalar_one()
        assert str(logical) == "2026-11-12"


def test_override_task_names_are_scoped_to_the_run_pipeline_with_upstream_namesakes(scene):
    from etl_craft.engine.repository.tasks import admitted_parameters
    from etl_craft.engine.run_definitions import read
    from etl_craft.services.operations.run_parameters import admit
    from fixtures.metadata import add_dependency

    ctx, pipeline, task = scene
    with ctx.engine.begin() as conn:
        upstream = add_pipeline(conn, "UPSTREAM")
        other = add_task(conn, upstream, "load", "PYTHON", INPUT_PARAMS='{"outside":1}')
        add_dependency(conn, pipeline, task, other, upstream_pipeline=upstream)
    _, run, _ = admit(ctx, request())
    with ctx.engine.connect() as conn:
        definition, _ = read(conn, run)
        assert admitted_parameters(definition, task)["INPUT_PARAMS"] == '{"day":2}'
        assert not any(row["task_id"] == other for row in definition.rows["CFG_TASK_PARAMETERS"])
