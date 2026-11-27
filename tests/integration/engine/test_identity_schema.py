"""Identity constraints and historical attempts on both Engine DB dialects."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from etl_craft.core.errors import RunStateError
from etl_craft.engine import transitions
from fixtures.metadata import add_pipeline, add_pipeline_dependency, add_task, start_run

pytestmark = pytest.mark.usefixtures("selected_default_project")


def test_attempt_identity_and_active_uniqueness(engine_db):
    with engine_db.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        t = add_task(conn, p, "load")
        r = start_run(conn, p)
        task_run = transitions.find_or_create_task_run(conn, t, r).task_run_id
    insert = text(
        "INSERT INTO AUD_TASK_ATTEMPTS (TASK_RUN_ID, ATTEMPT_NUMBER, STATUS) VALUES (:t, :n, :s)"
    )
    with engine_db.engine.begin() as conn:
        conn.execute(insert, {"t": task_run, "n": 1, "s": "SUCCESS"})
        conn.execute(insert, {"t": task_run, "n": 2, "s": "QUEUED"})
    for number, status in ((1, "FAILED"), (3, "CLAIMED"), (3, "RUNNING"), (3, "SKIPPED")):
        with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
            conn.execute(insert, {"t": task_run, "n": number, "s": status})
    with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
        conn.execute(insert, {"t": task_run + 100, "n": 1, "s": "SUCCESS"})


def test_run_keys_and_trigger_kinds(engine_db):
    with engine_db.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        r = transitions.create_active_run(conn, p, backfill=True)
        key, kind = conn.execute(
            text(
                "SELECT RUN_KEY, TRIGGER_KIND FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:r"
            ),
            {"r": r},
        ).one()
        assert key.startswith("backfill:") and kind == "BACKFILL"
        transitions.end_run_if(conn, r, "IN-PROGRESS", "SUCCESS")
    for value, trigger in ((key, "MANUAL"), ("other", "INVALID")):
        with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO AUD_PIPELINES_RUN_LOG "
                    "(PIPELINE_ID, STATUS, RUN_KEY, TRIGGER_KIND) "
                    "VALUES (:p, 'SUCCESS', :k, :t)"
                ),
                {"p": p, "k": value, "t": trigger},
            )
    with engine_db.engine.begin() as conn:
        p2 = add_pipeline(conn, "OTHER")
        conn.execute(
            text(
                "INSERT INTO AUD_PIPELINES_RUN_LOG (PIPELINE_ID, STATUS, RUN_KEY) "
                "VALUES (:p, 'SUCCESS', :k)"
            ),
            {"p": p2, "k": key},
        )


def test_gate_decision_dependency_and_result_constraints(engine_db):
    with engine_db.engine.begin() as conn:
        p = add_pipeline(conn, "DOWN")
        up = add_pipeline(conn, "UP")
        dep = add_pipeline_dependency(conn, p, up)
        r = start_run(conn, p)
        assert (
            conn.execute(
                text("SELECT CONSUME_REPAIRS FROM CFG_PIPELINES WHERE PIPELINE_CODE='DOWN'")
            ).scalar_one()
            == "Y"
        )
    insert = text(
        "INSERT INTO AUD_GATE_DECISIONS (PIPELINE_RUN_ID, PIPELINE_DEPENDENCY_ID, "
        "RESULT, REASON) VALUES (:r, :d, :s, 'gate reason')"
    )
    for dependency, result in ((None, "UNSATISFIED"), (dep, "INVALID"), (dep + 100, "SATISFIED")):
        with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
            conn.execute(insert, {"r": r, "d": dependency, "s": result})
    with engine_db.engine.begin() as conn:
        for result in ("SATISFIED", "UNSATISFIED", "BYPASSED"):
            conn.execute(insert, {"r": r, "d": dep, "s": result})
    with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_PIPELINES SET CONSUME_REPAIRS='X'"))


@pytest.mark.parametrize("trigger_kind,prefix", [("MANUAL", "manual:"), ("STAND_IN", "stand-in:")])
def test_new_run_identity_kind(engine_db, trigger_kind, prefix):
    with engine_db.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        transitions.create_active_run(conn, p, trigger_kind=trigger_kind)
        key, kind = conn.execute(
            text("SELECT RUN_KEY, TRIGGER_KIND FROM AUD_PIPELINES_RUN_LOG")
        ).one()
        assert key.startswith(prefix) and kind == trigger_kind


def test_inconsistent_trigger_kind_is_refused_before_inserting(engine_db):
    with engine_db.engine.begin() as conn:
        p = add_pipeline(conn, "P")
        with pytest.raises(RunStateError, match="expected MANUAL, BACKFILL or STAND_IN"):
            transitions.create_active_run(conn, p, backfill=True, trigger_kind="STAND_IN")
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0
