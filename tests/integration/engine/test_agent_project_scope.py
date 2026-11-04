"""Owned attempt operations retain their project at the common operation boundary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft import __version__
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, AgentReport, ApiRole
from etl_craft.engine import transitions
from etl_craft.engine.repository.hash_versions import fetch_hash_version, save_hash_version
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.engine.task_store import LocalTaskStore, TargetPublication, TaskIdentity
from etl_craft.handlers.resources import LocalLocker
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import ACTIONS, invoke
from etl_craft.services.operations.agent_models import AgentTask
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, start_run


@pytest.fixture
def owned_project_attempt(engine_db):
    admin = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    act(admin, ActionName.PROJECT_ADD, project="second", reason="Project isolation fixture")
    token = act(admin, ActionName.TOKEN_CREATE, name="agent", role=ApiRole.AGENT, pool="default")
    owner = str(token.metadata.token_id)
    with engine_db.engine.begin() as conn:
        project = conn.execute(
            text("SELECT PROJECT_ID AS project_id FROM CFG_PROJECTS WHERE PROJECT_CODE='second'")
        ).scalar_one()
        with selected_project(project):
            pipeline = add_pipeline(conn, "P", project_id=project)
            task = add_task(conn, pipeline, "setup")
            run = start_run(conn, pipeline)
            summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
            attempt = transitions.queue_attempt(conn, summary, SYSTEM_ACTOR)
            transitions.claim_attempt(
                conn,
                attempt,
                SYSTEM_ACTOR,
                owner=owner,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
            )
    return (
        replace(admin, role=ApiRole.AGENT, credential_token_id=token.metadata.token_id),
        project,
        pipeline,
        task,
        run,
        summary,
        attempt,
    )


def test_agent_operation_publishes_and_reads_only_its_project(owned_project_attempt, monkeypatch):
    ctx, project, pipeline, task, run, summary, attempt = owned_project_attempt
    target = "warehouse.main.people"
    with ctx.engine.begin() as conn, selected_project(1):
        save_hash_version(conn, target, 1)

    def write(context, request):
        store = LocalTaskStore(
            context.engine,
            context.config,
            TaskIdentity(pipeline, task, run, summary, None, None),
            LocalLocker(context.engine, context.config),
        )
        assert store.target(target).hash_version is None
        store.publish(TargetPublication(target, hash_version=2))
        return store.target(target).hash_version

    monkeypatch.setitem(
        ACTIONS, ActionName.AGENT_REPORT, replace(ACTIONS[ActionName.AGENT_REPORT], call=write)
    )
    result = invoke(
        ctx,
        ActionName.AGENT_REPORT,
        AgentTask(
            version=__version__,
            attempt_id=attempt,
            operation=AgentReport.PUBLISH,
            publication=TargetPublication(target, hash_version=2),
        ),
    )
    assert result == 2
    with ctx.engine.connect() as conn:
        with selected_project(project):
            assert fetch_hash_version(conn, target) == 2
        with selected_project(1):
            assert fetch_hash_version(conn, target) == 1


def test_other_project_token_cannot_publish_an_owned_attempt(owned_project_attempt, monkeypatch):
    from etl_craft.core.errors import PermissionDeniedError

    ctx, _, _, _, _, _, attempt = owned_project_attempt
    admin = replace(ctx, role=ApiRole.ADMIN, credential_token_id=None)
    token = act(admin, ActionName.TOKEN_CREATE, name="other", role=ApiRole.AGENT, pool="default")
    foreign = replace(ctx, project="second", credential_token_id=token.metadata.token_id)

    def forbidden(context, request):
        pytest.fail("foreign agent reached the write")

    monkeypatch.setitem(
        ACTIONS, ActionName.AGENT_REPORT, replace(ACTIONS[ActionName.AGENT_REPORT], call=forbidden)
    )
    with pytest.raises(PermissionDeniedError) as caught:
        invoke(
            foreign,
            ActionName.AGENT_REPORT,
            AgentTask(
                version=__version__,
                attempt_id=attempt,
                operation=AgentReport.PUBLISH,
                publication=TargetPublication("warehouse.main.people", hash_version=2),
            ),
        )
    for part in (str(attempt), "not owned", "admitted project", "use the credential"):
        assert part in str(caught.value)
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) AS n FROM AUD_TARGET_HASH_VERSION")).scalar_one()
            == 0
        )
        refused = conn.execute(
            text("SELECT COUNT(*) AS n FROM AUD_ACTIONS WHERE OUTCOME='REFUSED'")
        ).scalar_one()
        assert refused == 1


def test_rehash_candidate_lookup_is_project_scoped(owned_project_attempt):
    from etl_craft.engine.queries import statement

    ctx, project, pipeline, _, _, _, _ = owned_project_attempt
    with ctx.engine.begin() as conn:
        with selected_project(1):
            other = add_pipeline(conn, "OTHER")
            foreign = add_task(
                conn, other, "merge", SQL_ACTION="SCD1_MERGE", TARGET_OBJECT="main.people"
            )
        with selected_project(project):
            own = add_task(
                conn, pipeline, "merge", SQL_ACTION="SCD1_MERGE", TARGET_OBJECT="main.people"
            )
            found = set(conn.execute(statement(conn, "rehash_tasks")).scalars())
    assert own in found
    assert foreign not in found
