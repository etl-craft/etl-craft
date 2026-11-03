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
from etl_craft.engine.protection_events import append as append_event
from etl_craft.engine.protection_events import read
from fixtures.metadata import add_pipeline, add_task


def append(*args, **kwargs):
    return append_event(*args, privacy_key="test-only-project-privacy", **kwargs)


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


def test_guarded_event_upload_identity_check_and_null_non_upload_events(engine_db):
    from sqlalchemy.exc import IntegrityError

    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        attempt = creator(conn)
        ids = (
            conn.execute(
                text(
                    "SELECT p.PIPELINE_ID AS pipeline_id,p.PIPELINE_RUN_ID AS run_id "
                    "FROM AUD_PIPELINES_RUN_LOG p JOIN AUD_TASK_RUN_LOG t "
                    "ON t.PIPELINE_RUN_ID=p.PIPELINE_RUN_ID JOIN AUD_TASK_ATTEMPTS a "
                    "ON a.TASK_RUN_ID=t.TASK_RUN_ID WHERE a.ATTEMPT_ID=:attempt"
                ),
                {"attempt": attempt},
            )
            .mappings()
            .one()
        )
        upload = conn.execute(
            text(
                "INSERT INTO AUD_UPLOADS (PIPELINE_ID,ACCOUNT,FILE_NAME,STORED_NAME,SHA256,"
                "SIZE_BYTES,PIPELINE_RUN_ID,STATUS,UPLOADED_AT) "
                "VALUES (:pipeline,'steward','file.csv','file.csv',:hash,1,:run,'QUEUED',:now) "
                "RETURNING UPLOAD_ID AS upload_id"
            ),
            {
                "pipeline": ids["pipeline_id"],
                "run": ids["run_id"],
                "hash": "a" * 64,
                "now": datetime.now(UTC),
            },
        ).scalar_one()
    insert = text(
        "INSERT INTO AUD_PROTECTION_EVENTS (PROJECT_ID,TARGET_ID,REQUEST_ID,KIND,KEY_HASH,"
        "COLUMN_NAMES,VALUE_HASHES,STATUS,CREATED_BY,CREATED_AT,UPLOAD_ID,KEY_CHECK) "
        "VALUES (1,:target,:request,:kind,:key,'[]','[]','PENDING','steward',:now,:upload,:check)"
    )
    for kind in (ProtectionKind.REHASH, ProtectionKind.HARD_DELETE, ProtectionKind.ERASURE):
        with acting_as(ACTOR), pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
            conn.execute(
                insert,
                {
                    "target": TARGET,
                    "request": "check-" + kind,
                    "kind": kind,
                    "key": "a" * 64,
                    "check": "c" * 64,
                    "now": datetime.now(UTC),
                    "upload": upload,
                },
            )
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        request = append(
            conn, TARGET, ProtectionReport(ProtectionStatus.PENDING, (EVENT,)), attempt
        )
        assert (
            conn.execute(
                text(
                    "SELECT UPLOAD_ID AS upload_id FROM AUD_PROTECTION_EVENTS "
                    "WHERE REQUEST_ID=:request"
                ),
                {"request": request},
            ).scalar_one()
            is None
        )


def test_first_privacy_secret_wins_atomically_for_the_project(engine_db):
    from etl_craft.core.errors import ConfigurationError
    from etl_craft.engine import protection_events
    from etl_craft.engine.privacy import guarded
    from fixtures.races import two_at_once

    def record(key, target):
        try:
            with acting_as(ACTOR), guarded(engine_db.config), engine_db.engine.begin() as conn:
                return protection_events.append(
                    conn,
                    target,
                    ProtectionReport(ProtectionStatus.PENDING, (EVENT,)),
                    None,
                    privacy_key=key,
                )
        except ConfigurationError as error:
            return error

    result = two_at_once(
        lambda: record("first-secret", TARGET),
        lambda: record("second-secret", TARGET + "_other"),
        at=(engine_db.engine, "begin"),
    )
    assert sum(isinstance(value, str) for value in result) == 1
    failure = next(value for value in result if isinstance(value, ConfigurationError))
    for part in ("Privacy.Hmac_secret", "differs", "restore the original secret"):
        assert part in str(failure)
    with engine_db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS")).scalar_one() == 1


def test_validate_and_doctor_refuse_stewardship_without_project_privacy_secret(engine_db):
    from etl_craft.engine.migrations import mark_packaged_migrations_applied
    from etl_craft.services.doctor import run_checks
    from etl_craft.services.validate import validate

    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "STEWARDSHIP")
        add_task(
            conn,
            pipeline,
            "merge",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="main.people",
            SELECT_QUERY="SELECT 1 AS id",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="id",
        )
        conn.execute(
            text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y' WHERE PIPELINE_ID=:id"),
            {"id": pipeline},
        )
        mark_packaged_migrations_applied(conn)
    validation = validate(engine_db.engine, engine_db.config)
    assert any(
        "Privacy.Hmac_secret" in f.message and "configure" in f.message for f in validation.findings
    )
    doctor = run_checks(engine_db.config)
    assert any("Privacy.Hmac_secret" in c.detail and "configure" in c.detail for c in doctor)


def test_erasure_normalizes_unquoted_managed_sql_targets(engine_db):
    from dataclasses import replace

    from etl_craft.config import ConnectionProfile
    from etl_craft.core.erasure import ErasureEntry
    from etl_craft.handlers.erasure import coverage, project_coverage

    config = replace(
        engine_db.config,
        warehouse=ConnectionProfile(
            "WAREHOUSE",
            "dev",
            "jdbc:snowflake://account.snowflakecomputing.com/?db=database&schema=schema",
            "",
            "NONE",
            extra={"database": "database", "schema": "schema"},
        ),
    )
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(
            conn,
            pipeline,
            "T",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="database.schema.people",
            SELECT_QUERY="SELECT 1 AS id",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="id",
        )
    graph = project_coverage(engine_db.engine, config)
    reached, _ = coverage(
        config, ErasureEntry("DATABASE.SCHEMA.PEOPLE", "ID", "1", "a" * 64), graph
    )
    assert reached == [("DATABASE.SCHEMA.PEOPLE", "id")]


def test_native_key_labels_and_canonical_cells_share_private_value_identity(engine_db):
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        append(
            conn,
            TARGET,
            ProtectionReport(
                ProtectionStatus.PENDING,
                (
                    ProtectionEvent(ProtectionKind.KEY, "a" * 32, ("ID",), ("b" * 32,)),
                    ProtectionEvent(ProtectionKind.LOCK, "a" * 32, ("id",), ("b" * 32,)),
                ),
            ),
            None,
        )
        records = read(conn, TARGET).records
    values = [record.event.value_hashes for record in records]
    assert len(values) == 2 and values[0] == values[1]
    assert values[0] != ("b" * 32,)


def test_candidate_matching_uses_one_checked_privacy_key_snapshot(engine_db, monkeypatch):
    from dataclasses import replace

    from etl_craft.config import ConnectionProfile, resolve
    from etl_craft.core.errors import ConfigurationError
    from etl_craft.core.protection import ProtectionCandidates
    from etl_craft.engine import locks
    from etl_craft.engine.task_store import LocalTaskStore
    from etl_craft.handlers.resources import LocalLocker

    config = replace(
        engine_db.config,
        warehouse=ConnectionProfile(
            "WAREHOUSE", "dev", "jdbc:duckdb:warehouse.db", "", "NONE", schema="main"
        ),
        privacy_hmac_secret="TEST_PRIVACY",
    )
    event = ProtectionEvent(ProtectionKind.ERASURE, "a" * 32, ("id",), (None,))
    with acting_as(ACTOR), engine_db.engine.begin() as conn:
        request = append(conn, TARGET, ProtectionReport(ProtectionStatus.PENDING, (event,)), None)
        event_id = read(conn, TARGET).records[0].event_id
    original = resolve.resolve_named_secret
    seen = []

    def rotating(config, name):
        if name != "TEST_PRIVACY":
            return original(config, name)
        seen.append(name)
        return "test-only-project-privacy" if len(seen) == 1 else "changed"

    monkeypatch.setattr(resolve, "resolve_named_secret", rotating)
    locker = LocalLocker(engine_db.engine, config)
    store = LocalTaskStore.standalone(engine_db.engine, config, locker)
    lock = locks.target("main.people", "warehouse")
    query = ProtectionCandidates(request, ("id",), ("a" * 32,))
    with acting_as(ACTOR), store.hold(lock.key, lock.name, 30):
        result = store.protection_match("main.people", query)
        assert result.matched == (event_id,)
        assert seen == ["TEST_PRIVACY"]
        with pytest.raises(ConfigurationError, match="restore the original secret"):
            store.protection_match("main.people", query)
