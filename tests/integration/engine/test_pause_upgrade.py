"""Forward pause migration refuses development-only holds and retains valid audit identities."""

from contextvars import Context
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.errors import MigrationError
from etl_craft.engine import migrations
from fixtures.metadata import add_pipeline, add_task, insert, start_run
from fixtures.released_schema import install

REFUSAL = (
    "this Engine DB contains holds or wait pauses from an unreleased development build; "
    "recreate this development Engine DB"
)


@pytest.fixture
def development_db(empty_engine_db, monkeypatch):
    db = empty_engine_db
    install(db, "0.3.0")
    original = migrations.migration_streams

    def through_0095(*args, **kwargs):
        return [
            replace(stream, files=tuple(f for f in stream.files if f.version < "0096"))
            for stream in original(*args, **kwargs)
        ]

    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_streams", through_0095)
        migrations.apply_pending_migrations(db.engine)
    with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "T", "EMAIL_ALERT")
        run = start_run(conn, pipeline)
    return db, pipeline, task, run


def seed_pause(conn, pipeline, task=None, outcome=None):
    return insert(
        conn,
        "INSERT INTO AUD_PIPELINE_PAUSES (PIPELINE_ID,TASK_ID,OUTCOME,PAUSED_BY,REASON) "
        "VALUES (:pipeline,:task,:outcome,'operator','retained pause')",
        "PIPELINE_PAUSE_ID",
        pipeline=pipeline,
        task=task,
        outcome=outcome,
    )


@pytest.mark.parametrize("invalid", ["hold", "wait", "both"])
def test_pause_upgrade_refuses_development_holds_and_wait_pauses_without_changes(
    development_db, invalid
):
    db, pipeline, task, run = development_db
    with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
        if invalid in {"hold", "both"}:
            conn.execute(
                text(
                    "INSERT INTO AUD_CONTROL_REQUESTS "
                    "(REQUEST_KEY,PIPELINE_RUN_ID,ACTION,STATUS,ATTEMPT_IDS,REQUESTED_BY,"
                    "REQUESTED_BY_KIND,REASON,REQUESTED_AT,MESSAGE) VALUES "
                    "('legacy-hold',:run,'HOLD','COMPLETED','[]','operator','USER',"
                    "'maintenance',CURRENT_TIMESTAMP,'held')"
                ),
                {"run": run},
            )
        if invalid in {"wait", "both"}:
            seed_pause(conn, pipeline, task)
    with pytest.raises(MigrationError, match=REFUSAL) as refused:
        migrations.apply_pending_migrations(db.engine)
    if db.dialect.name == "postgresql":
        assert f"HOLD/RELEASE controls={int(invalid in {'hold', 'both'})}" in str(refused.value)
        assert f"wait pauses={int(invalid in {'wait', 'both'})}" in str(refused.value)
    with db.engine.connect() as conn:
        assert "ACTIVE_RUNS" not in db.dialect.column_names(conn, "AUD_PIPELINE_PAUSES")
        assert not conn.execute(
            text("SELECT 1 FROM SCHEMA_MIGRATIONS WHERE VERSION LIKE '0096%'")
        ).first()


def test_pause_upgrade_retains_pipeline_finish_and_task_outcomes_with_guards(development_db):
    db, pipeline, task, _ = development_db
    with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
        original = seed_pause(conn, pipeline)
        task_pause = seed_pause(conn, pipeline, task, "SKIPPED")
    migrations.apply_pending_migrations(db.engine)
    with db.engine.connect() as conn:
        rows = {
            row.pause_id: row
            for row in conn.execute(
                text(
                    "SELECT PIPELINE_PAUSE_ID AS pause_id,ACTIVE_RUNS AS "
                    "active_runs,OUTCOME AS outcome,"
                    "PAUSED_BY AS actor,REASON AS reason FROM AUD_PIPELINE_PAUSES"
                )
            )
        }
        assert rows[original].active_runs == "FINISH"
        assert rows[original].outcome is None
        assert rows[task_pause].active_runs is None
        assert rows[task_pause].outcome == "SKIPPED"
        assert all(
            row.actor == "operator" and row.reason == "retained pause" for row in rows.values()
        )

    def unattributed_delete():
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM AUD_PIPELINE_PAUSES"))

    with pytest.raises(DBAPIError, match=r"written only|actor"):
        Context().run(unattributed_delete)


@pytest.mark.parametrize(
    "task_scope,outcome,active_runs",
    [
        (False, None, None),
        (True, None, None),
        (True, "SKIPPED", "DRAIN"),
        (False, "SUCCESS", "FINISH"),
    ],
)
def test_pause_upgrade_check_refuses_null_or_mixed_scope_values(
    development_db, task_scope, outcome, active_runs
):
    db, pipeline, task, _ = development_db
    migrations.apply_pending_migrations(db.engine)
    with (
        acting_as(SYSTEM_ACTOR),
        pytest.raises(DBAPIError, match=r"check|CHECK"),
        db.engine.begin() as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO AUD_PIPELINE_PAUSES "
                "(PIPELINE_ID,TASK_ID,OUTCOME,ACTIVE_RUNS,PAUSED_BY,REASON) "
                "VALUES (:pipeline,:task,:outcome,:active_runs,'operator','invalid scope')"
            ),
            {
                "pipeline": pipeline,
                "task": task if task_scope else None,
                "outcome": outcome,
                "active_runs": active_runs,
            },
        )


@pytest.mark.parametrize("action", ["HOLD", "RELEASE"])
def test_pause_upgrade_rejects_removed_control_actions(development_db, action):
    db, _, _, run = development_db
    migrations.apply_pending_migrations(db.engine)
    with acting_as(SYSTEM_ACTOR), pytest.raises(DBAPIError), db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO AUD_CONTROL_REQUESTS "
                "(REQUEST_KEY,PIPELINE_RUN_ID,ACTION,STATUS,ATTEMPT_IDS,REQUESTED_BY,"
                "REQUESTED_BY_KIND,REASON,REQUESTED_AT,MESSAGE) "
                "VALUES "
                "('removed',:run,:action,'COMPLETED','[]','operator','USER','test',"
                "CURRENT_TIMESTAMP,'invalid')"
            ),
            {"run": run, "action": action},
        )


def test_pause_upgrade_preserves_control_rows_guards_and_allocated_identifiers(development_db):
    from etl_craft.core.actor import purpose

    db, pipeline, _, run = development_db

    def control(conn, key):
        return insert(
            conn,
            "INSERT INTO AUD_CONTROL_REQUESTS "
            "(REQUEST_KEY,PIPELINE_RUN_ID,ACTION,STATUS,ATTEMPT_IDS,REQUESTED_BY,"
            "REQUESTED_BY_KIND,REASON,REQUESTED_AT,MESSAGE) VALUES "
            "(:key,:run,'STOP','COMPLETED','[]','operator','USER',"
            "'maintenance',CURRENT_TIMESTAMP,'retained')",
            "CONTROL_ID",
            key=key,
            run=run,
        )

    with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
        retained = control(conn, "retained")
        removed = control(conn, "removed")
        removed_pause = seed_pause(conn, pipeline)
    token = purpose.set("retention")
    try:
        with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM AUD_CONTROL_REQUESTS WHERE CONTROL_ID=:id"), {"id": removed}
            )
            conn.execute(text("DELETE FROM AUD_PIPELINE_PAUSES"))
    finally:
        purpose.reset(token)
    migrations.apply_pending_migrations(db.engine)
    with acting_as(SYSTEM_ACTOR), db.engine.begin() as conn:
        assert control(conn, "next") > removed
        row = conn.execute(
            text(
                "SELECT ACTION AS action,MESSAGE AS message,REQUESTED_BY AS actor "
                "FROM AUD_CONTROL_REQUESTS WHERE CONTROL_ID=:id"
            ),
            {"id": retained},
        ).one()
        assert (row.action, row.message, row.actor) == ("STOP", "retained", "operator")
        next_pause = insert(
            conn,
            "INSERT INTO AUD_PIPELINE_PAUSES (PIPELINE_ID,ACTIVE_RUNS,PAUSED_BY,REASON) "
            "VALUES (:pipeline,'DRAIN','operator','new policy')",
            "PIPELINE_PAUSE_ID",
            pipeline=pipeline,
        )
        assert next_pause > removed_pause
    with (
        acting_as(SYSTEM_ACTOR),
        pytest.raises(DBAPIError, match="immutable"),
        db.engine.begin() as conn,
    ):
        conn.execute(
            text("UPDATE AUD_CONTROL_REQUESTS SET MESSAGE='changed' WHERE CONTROL_ID=:id"),
            {"id": retained},
        )
