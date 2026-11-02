"""Hash-only immutable intents and terminal-creator recovery on both Engine DBs."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums_protection import ProtectionEvidence, ProtectionKind, ProtectionStatus
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.core.protection import (
    MAX_PROTECTION_EVENTS,
    ProtectionEvent,
    ProtectionReport,
)
from etl_craft.engine import transitions
from etl_craft.engine.protection_events import append, read
from fixtures.metadata import add_pipeline, add_task

ACTOR = Actor("steward", ActorKind.USER)
RECOVERER = Actor("recovery", ActorKind.SERVICE)
TARGET = '"warehouse"."main"."people"'
EVENT = ProtectionEvent(ProtectionKind.WRITE, "a" * 32, ("name",), ("b" * 32,))


def creator(conn, *, expired=False):
    pipeline = add_pipeline(conn, "P")
    task = add_task(conn, pipeline, "T")
    run = transitions.create_run(conn, pipeline, ACTOR)
    summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
    attempt = transitions.queue_attempt(conn, summary, ACTOR)
    transitions.claim_attempt(
        conn,
        attempt,
        ACTOR,
        owner="owner-A",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=-60 if expired else 60),
    )
    return attempt


@pytest.mark.parametrize("expired", [False, True])
def test_recovery_refuses_live_or_unreconciled_creator(engine_db, expired):
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        attempt = creator(conn, expired=expired)
        request = append(
            conn, TARGET, ProtectionReport(ProtectionStatus.PENDING, (EVENT,)), attempt
        )
    with acting_as(RECOVERER), engine_db.engine.begin() as conn:
        for evidence, status in (
            (ProtectionEvidence.STAMP_PRESENT, ProtectionStatus.COMMITTED),
            (ProtectionEvidence.STAMP_ABSENT, ProtectionStatus.ABANDONED),
        ):
            with pytest.raises(
                PermissionDeniedError, match=rf"attempt 999.*creating attempt {attempt}.*reconcile"
            ):
                append(
                    conn,
                    TARGET,
                    ProtectionReport(status, request_id=request, evidence=evidence),
                    999,
                )
        assert len(read(conn, TARGET).records) == 1


@pytest.mark.parametrize(
    ("kind", "status", "evidence"),
    [
        (ProtectionKind.WRITE, ProtectionStatus.COMMITTED, ProtectionEvidence.STAMP_PRESENT),
        (ProtectionKind.WRITE, ProtectionStatus.ABANDONED, ProtectionEvidence.STAMP_ABSENT),
        (ProtectionKind.HARD_DELETE, ProtectionStatus.COMMITTED, ProtectionEvidence.KEYS_ABSENT),
        (ProtectionKind.ERASURE, ProtectionStatus.ABANDONED, ProtectionEvidence.KEYS_PRESENT),
    ],
)
def test_reconciled_creator_recovery_preserves_identity_and_is_idempotent(
    engine_db, kind, status, evidence
):
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        attempt = creator(conn, expired=True)
        event = ProtectionEvent(kind, EVENT.key_hash, EVENT.columns, EVENT.value_hashes)
        request = append(
            conn, TARGET, ProtectionReport(ProtectionStatus.PENDING, (event,)), attempt
        )
        transitions.lose_attempt(conn, attempt, RECOVERER, owner="owner-A")
        # A second real attempt supplies recovery attribution.
        summary = conn.execute(
            text("SELECT TASK_RUN_ID AS task_run_id FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:id"),
            {"id": attempt},
        ).scalar_one()
        retry = transitions.queue_attempt(conn, summary, RECOVERER)
    report = ProtectionReport(status, request_id=request, evidence=evidence)
    with acting_as(RECOVERER), engine_db.engine.begin() as conn:
        with pytest.raises(PermissionDeniedError, match="creator-only"):
            append(conn, TARGET, ProtectionReport(status, request_id=request), retry)
        append(conn, TARGET, report, retry)
        append(conn, TARGET, report, retry)
        assert read(conn, TARGET).records == ()
        rows = (
            conn.execute(
                text(
                    "SELECT ATTEMPT_ID AS attempt_id,"
                    "RECOVERING_ATTEMPT_ID AS recovering_attempt_id,"
                    "RECOVERY_ACTOR AS recovery_actor,CREATED_BY AS created_by,STATUS AS status,"
                    "KEY_HASH AS key_hash,COLUMN_NAMES AS column_names,"
                    "VALUE_HASHES AS value_hashes "
                    "FROM AUD_PROTECTION_EVENTS WHERE REQUEST_ID=:request ORDER BY EVENT_ID"
                ),
                {"request": request},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2
    assert rows[-1]["attempt_id"] == attempt
    assert rows[-1]["recovering_attempt_id"] == retry
    assert rows[-1]["recovery_actor"] == RECOVERER.name
    assert rows[-1]["created_by"] == RECOVERER.name
    assert rows[-1]["status"] == status
    assert "private-business-value" not in str(rows)


def test_pending_pages_keep_every_hash_and_normal_finalization_is_creator_only(engine_db):
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        request = append(
            conn,
            TARGET,
            ProtectionReport(ProtectionStatus.PENDING, (EVENT,) * MAX_PROTECTION_EVENTS),
            None,
        )
        append(
            conn,
            TARGET,
            ProtectionReport(
                ProtectionStatus.PENDING,
                (EVENT,),
                request_id=request,
            ),
            None,
        )
        first = read(conn, TARGET)
        assert len(first.records) == MAX_PROTECTION_EVENTS
        assert first.cursor is not None
        second = read(conn, TARGET, first.cursor)
        assert len(second.records) == 1 and second.cursor is None
        append(conn, TARGET, ProtectionReport(ProtectionStatus.COMMITTED, request_id=request), None)
        assert not read(conn, TARGET).records


def test_recovery_refuses_missing_creator_history(engine_db):
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        request = append(conn, TARGET, ProtectionReport(ProtectionStatus.PENDING, (EVENT,)), 999)
    with acting_as(RECOVERER), engine_db.engine.begin() as conn:
        with pytest.raises(
            PermissionDeniedError, match=r"creating-attempt history is missing.*restore"
        ):
            append(
                conn,
                TARGET,
                ProtectionReport(
                    ProtectionStatus.COMMITTED,
                    request_id=request,
                    evidence=ProtectionEvidence.STAMP_PRESENT,
                ),
                1000,
            )
        assert len(read(conn, TARGET).records) == 1
