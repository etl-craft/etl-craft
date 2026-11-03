"""Exercise the real fenced HTTP report schema with an agent-side task store."""

from contextlib import contextmanager
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft import __version__
from etl_craft.agent.task_store import RemoteTaskStore
from etl_craft.api.app import create_app
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole, AttemptStatus, DeploymentProfile, RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.migrations import mark_packaged_migrations_applied
from etl_craft.engine.repository.tasks import resolve_task_id
from etl_craft.engine.resource_locks import holder_tag
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.agent_models import AgentReply
from etl_craft.services.operations.serialization import encode
from etl_craft.warehouse.fencing import confirm_stopped
from fixtures.actions import act
from fixtures.agents import resources


@contextmanager
def recovery_agent(w, task_code="load"):
    """Return an actual remote store whose requests cross the authenticated HTTP boundary."""
    config = replace(w.config, deployment=DeploymentProfile.CONTROLLER_AGENTS)
    ctx = OperationContext(w.engine_db, config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with w.engine_db.begin() as conn:
        mark_packaged_migrations_applied(conn)
        status = conn.execute(
            text("SELECT STATUS AS status FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:id"),
            {"id": w.pipeline_run_id},
        ).scalar_one()
        if status == RunStatus.IN_PROGRESS:
            transitions.finalize_pipeline_run(conn, w.pipeline_run_id, RunStatus.CANCELLED)
        recovery_run = transitions.create_run(conn, w.pipeline_id, SYSTEM_ACTOR)
        task_run = transitions.find_or_create_task_run(
            conn, resolve_task_id(conn, w.pipeline_id, task_code), recovery_run
        )
        attempt = transitions.queue_attempt(conn, task_run.task_run_id, SYSTEM_ACTOR)
    token = act(
        ctx, ActionName.TOKEN_CREATE, name="recovery-agent", role=ApiRole.AGENT, pool="default"
    )
    with TestClient(create_app(ctx)) as client:
        headers = {"Authorization": "Bearer " + token.token}
        registered = client.post(
            "/api/v1/agent/register",
            headers=headers,
            json={
                "version": __version__,
                "pool": "default",
                "resources": encode(resources()),
            },
        )
        assert registered.status_code == 200, registered.text
        claimed = client.post(
            "/api/v1/agent/claim",
            headers=headers,
            json={
                "version": __version__,
                "free_kinds": ["warehouse"],
            },
        )
        assert claimed.status_code == 200, claimed.text
        claim = claimed.json()["data"]
        assert claim["task"]["attempt_id"] == attempt
        holder = claim["holder_id"]
        credential = {"Authorization": "Bearer " + claim["credential"]}
        replies = []

        class Client:
            def call(self, action, request, timeout=None):
                response = client.post(
                    "/api/v1/agent/report", headers=credential, json=encode(request)
                )
                assert response.status_code == 200, response.text
                replies.append(response.text)
                return AgentReply(response.json()["data"])

        try:
            yield (
                RemoteTaskStore(
                    Client(), attempt, lambda old: confirm_stopped(config, holder_tag(old)), holder
                ),
                replies,
            )
        finally:
            with w.engine_db.begin() as conn:
                transitions.finish_attempt(
                    conn,
                    attempt,
                    AttemptStatus.CANCELLED,
                    SYSTEM_ACTOR,
                    owner=claim["task"]["owner"],
                )
                transitions.finalize_pipeline_run(conn, recovery_run, RunStatus.CANCELLED)
