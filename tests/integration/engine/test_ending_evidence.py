"""Uncertain old writers stay fenced until verified or explicitly attested."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft.config import ConnectionProfile
from etl_craft.core.actor import SYSTEM_ACTOR, Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole, AttemptStatus, OffsetType
from etl_craft.core.enums_access import Permission
from etl_craft.core.errors import LockTimeoutError, PermissionDeniedError, RunRefusedError
from etl_craft.engine import transitions
from etl_craft.engine.repository.offsets import StoredOffset
from etl_craft.engine.timestamp_windows import WindowDefinition, admit_window
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.requests import ReconcileInput
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, start_run
from fixtures.services import POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, require


@pytest.fixture
def legacy_writer(engine_db, monkeypatch, request):
    service = require("postgres")
    monkeypatch.setenv("EVIDENCE_WAREHOUSE_PASSWORD", POSTGRES_PASSWORD)
    config = replace(
        engine_db.config,
        warehouse=ConnectionProfile(
            "WAREHOUSE",
            "test",
            f"jdbc:postgresql://{service.address}/{POSTGRES_DB}",
            POSTGRES_USER,
            "PASSWORD",
            {"secret_var": "EVIDENCE_WAREHOUSE_PASSWORD"},
        ),
    )
    admin = OperationContext(engine_db.engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    token = act(
        admin, ActionName.TOKEN_CREATE, name="writer-agent", role=ApiRole.AGENT, pool="default"
    )
    owner = str(token.metadata.token_id)
    from etl_craft.engine import timestamp_windows

    original_clock = timestamp_windows.checked_clock
    past = datetime.now(UTC) - timedelta(minutes=5)
    monkeypatch.setattr(timestamp_windows, "checked_clock", lambda conn: past)
    live = getattr(request.node, "callspec", None)
    live = live is not None and live.params.get("condition") == "lease"
    expiry = datetime.now(UTC) + timedelta(hours=1) if live else past + timedelta(seconds=60)
    with engine_db.engine.begin() as conn:
        source = add_pipeline(conn, "SOURCE")
        task = add_task(conn, source, "load", "PYTHON")
        run = start_run(conn, source)
        summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
        attempt = transitions.queue_attempt(conn, summary, SYSTEM_ACTOR)
        transitions.claim_attempt(
            conn,
            attempt,
            SYSTEM_ACTOR,
            owner=owner,
            lease_expires_at=expiry,
            host="deleted-pod",
        )
        transitions.start_attempt(
            conn,
            attempt,
            SYSTEM_ACTOR,
            owner=owner,
            host="deleted-pod",
            pid=91,
            process_start="deleted-instance-birth",
        )
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET AGENT_INSTANCE_ID=:instance WHERE ATTEMPT_ID=:id"),
            {
                "id": attempt,
                "instance": None
                if getattr(request.node, "callspec", None) is not None
                and request.node.callspec.params.get("legacy_instance")
                else "old-pod-uid",
            },
        )
        real_parameters = transitions.actor_parameters
        with monkeypatch.context() as ending_clock:
            ending_clock.setattr(
                transitions,
                "actor_parameters",
                lambda actor: {**real_parameters(actor), "now": past},
            )
            transitions.finish_attempt(
                conn, attempt, AttemptStatus.FAILED, SYSTEM_ACTOR, owner=owner
            )
        conn.execute(
            text(
                "INSERT INTO AUD_AGENTS (AGENT_ID,POOL,HOST,VERSION,PYTHON_SLOTS,"
                "WAREHOUSE_SLOTS,STARTED_AT,HEARTBEAT_AT,STATUS,RESOURCE_REPORT,INSTANCE_ID) "
                "VALUES (:id,'default','new-pod','test',1,0,:now,:now,'ACTIVE','{}','new-pod-uid')"
            ),
            {"id": int(owner), "now": datetime.now(UTC)},
        )
    monkeypatch.setattr(timestamp_windows, "checked_clock", original_clock)
    operator = replace(admin, actor=Actor("operator", ActorKind.USER), role=ApiRole.OPERATOR)
    return operator, attempt, source, task


def high_mark(ctx):
    with ctx.engine.begin() as conn:
        p = add_pipeline(conn, "DM")
        t = add_task(conn, p, "dm")
        run = start_run(conn, p)
        summary = transitions.find_or_create_task_run(conn, t, run).task_run_id
        definition = WindowDefinition(
            StoredOffset(OffsetType.TIMESTAMP, "2000-01-01T00:00:00+00:00"), ("SOURCE",)
        )
        return admit_window(conn, t, summary, datetime.now(UTC), definition).high


@pytest.mark.parametrize("legacy_instance", [False, True])
def test_attested_legacy_ending_advances_the_window_and_names_operator(
    legacy_writer, legacy_instance
):
    ctx, attempt, _, _ = legacy_writer
    before = high_mark(ctx)
    result = invoke(
        ctx,
        ActionName.RECONCILE,
        ReconcileInput(
            pipeline_code="SOURCE", attest_ended=True, reason="Deleted pod ending attested by owner"
        ),
    )
    assert "1 ending evidence" in result.message
    with ctx.engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT KIND AS kind,EVIDENCE_KIND AS evidence_kind,ACTOR AS actor,"
                    "REASON AS reason,VERIFIED_CHECKS AS checks "
                    "FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS WHERE ATTEMPT_ID=:id"
                ),
                {"id": attempt},
            )
            .mappings()
            .all()
        )
    evidence = {row["kind"]: row for row in rows}
    assert evidence["PROCESS"]["evidence_kind"] == "ATTESTED"
    assert evidence["QUERIES"]["evidence_kind"] == "VERIFIED"
    assert all(row["actor"] == "operator" and "Deleted pod" in row["reason"] for row in rows)
    assert "tagged_queries_absent" in evidence["PROCESS"]["checks"]
    with ctx.engine.begin() as conn:
        p = add_pipeline(conn, "DM_NEXT")
        t = add_task(conn, p, "dm")
        run = start_run(conn, p)
        summary = transitions.find_or_create_task_run(conn, t, run).task_run_id
        after = admit_window(
            conn,
            t,
            summary,
            datetime.now(UTC),
            WindowDefinition(
                StoredOffset(OffsetType.TIMESTAMP, "2000-01-01T00:00:00+00:00"), ("SOURCE",)
            ),
        ).high
    assert after > before


@pytest.mark.parametrize("condition", ["lease", "query", "instance", "unverified"])
def test_attestation_refuses_unverified_endings_without_writes(
    legacy_writer, monkeypatch, condition
):
    ctx, attempt, _, _ = legacy_writer
    if condition == "lease":
        pass
    elif condition == "instance":
        with ctx.engine.begin() as conn:
            conn.execute(text("UPDATE AUD_AGENTS SET INSTANCE_ID='old-pod-uid'"))
    error = LockTimeoutError if condition == "query" else RunRefusedError
    from contextlib import ExitStack

    from etl_craft.core.ownership import attempt_holder
    from etl_craft.engine.queries import statement
    from etl_craft.engine.resource_locks import holder_tag
    from etl_craft.warehouse.connection import build_warehouse_engine

    with ExitStack() as stack:
        if condition == "query":
            with ctx.engine.connect() as conn:
                identity = conn.execute(
                    statement(conn, "reconcile_ending_identity"), {"attempt_id": attempt}
                ).one()
            tag = holder_tag(attempt_holder(attempt, identity.token_digest))
            warehouse = build_warehouse_engine(ctx.config, session_tag=tag)
            stack.callback(warehouse.dispose)
            stack.enter_context(warehouse.connect())
        with pytest.raises(error):
            invoke(
                ctx,
                ActionName.RECONCILE,
                ReconcileInput(
                    pipeline_code="SOURCE",
                    attest_ended=condition != "unverified",
                    reason="Refusal fixture",
                ),
            )
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) AS n FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS WHERE ATTEMPT_ID=:id"),
                {"id": attempt},
            ).scalar_one()
            == 0
        )


def test_can_run_grant_does_not_grant_attestation(legacy_writer):
    ctx, _, _, _ = legacy_writer
    admin = replace(ctx, role=ApiRole.ADMIN)
    act(admin, ActionName.TOKEN_CREATE, name="runner", role=ApiRole.VIEWER)
    act(
        admin,
        ActionName.ACCESS_GRANT,
        project="default",
        account="runner",
        permission=Permission.CAN_RUN,
        reason="Fixture grant",
    )
    viewer = replace(ctx, actor=Actor("runner", ActorKind.SERVICE), role=ApiRole.VIEWER)
    with pytest.raises(PermissionDeniedError, match="operator"):
        invoke(
            viewer,
            ActionName.RECONCILE,
            ReconcileInput(pipeline_code="SOURCE", attest_ended=True, reason="Must refuse"),
        )


def test_attestation_does_not_ignore_an_active_source_attempt(legacy_writer):
    ctx, _, source, task = legacy_writer
    with ctx.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS run_id FROM AUD_PIPELINES_RUN_LOG "
                "WHERE PIPELINE_ID=:pipeline"
            ),
            {"pipeline": source},
        ).one()
        summary = transitions.find_or_create_task_run(conn, task, row.run_id).task_run_id
        active = transitions.queue_attempt(conn, summary, SYSTEM_ACTOR)
    with pytest.raises(RunRefusedError, match="terminal fence"):
        invoke(
            ctx,
            ActionName.RECONCILE,
            ReconcileInput(
                pipeline_code="SOURCE", attest_ended=True, reason="Must refuse live work"
            ),
        )
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT STATUS AS status FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:id"),
                {"id": active},
            ).scalar_one()
            == "QUEUED"
        )
