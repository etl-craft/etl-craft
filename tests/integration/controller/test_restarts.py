"""A pipeline restarts when its last run ends in a status its AUTO_RESTART_CONDITION names."""

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import text

from etl_craft.controller.restarts import COOLDOWN, Restarts
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ApiRole
from etl_craft.core.time import as_utc
from etl_craft.services.operations import OperationContext
from fixtures.metadata import add_pipeline, finish_run, start_run


def context(db, allowed="SCHEDULE|ALWAYS"):
    config = replace(db.config, allowed_auto_restarts=allowed)
    return OperationContext(
        db.engine, config, Actor("controller", ActorKind.SERVICE), role=ApiRole.ADMIN
    )


def ended(db, condition, status, code="WATCH"):
    """A pipeline whose latest run ended ``status``; returns the pipeline, the run and its end."""
    with db.engine.begin() as conn:
        pipeline = add_pipeline(conn, code)
        conn.execute(
            text("UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION=:c WHERE PIPELINE_ID=:i"),
            {"c": condition, "i": pipeline},
        )
        run = start_run(conn, pipeline)
        finish_run(conn, run, status)
        end = conn.execute(
            text("SELECT END_DATE AS ended FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:r"),
            {"r": run},
        ).scalar_one()
    return pipeline, run, as_utc(end)


def runs(db, pipeline):
    with db.engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT PIPELINE_RUN_ID AS id, STATUS AS status, TRIGGER_KIND AS kind, "
                "RUN_KEY AS key FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:p ORDER BY 1"
            ),
            {"p": pipeline},
        ).all()


def test_a_run_ending_in_a_listed_status_is_followed_once_after_the_cooldown(engine_db):
    pipeline, run, end = ended(engine_db, "SUCCESS|SKIPPED", "SUCCESS")
    ctx = context(engine_db)
    Restarts().refresh(ctx, end + COOLDOWN - timedelta(seconds=1))
    assert len(runs(engine_db, pipeline)) == 1  # too soon after the end
    Restarts().refresh(ctx, end + COOLDOWN)
    Restarts().refresh(ctx, end + COOLDOWN + timedelta(minutes=1))  # a second controller's pass
    made = runs(engine_db, pipeline)[1:]
    assert [(r.status, r.kind, r.key) for r in made] == [("QUEUED", "RESTART", f"restart:{run}")]


def test_a_failure_not_listed_stops_the_chain_and_a_later_success_continues_it(engine_db):
    pipeline, _run, end = ended(engine_db, "SUCCESS|SKIPPED", "FAILED")
    Restarts().refresh(context(engine_db), end + timedelta(hours=1))
    assert len(runs(engine_db, pipeline)) == 1  # the chain stopped at the failure
    with engine_db.engine.begin() as conn:  # an operator's recovery ends SUCCESS under a new run
        again = start_run(conn, pipeline)
        finish_run(conn, again, "SUCCESS")
        later = as_utc(
            conn.execute(
                text("SELECT END_DATE FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:r"),
                {"r": again},
            ).scalar_one()
        )
    Restarts().refresh(context(engine_db), later + COOLDOWN)
    assert runs(engine_db, pipeline)[-1].key == f"restart:{again}"


def test_a_cancelled_run_never_restarts_even_when_always(engine_db):
    pipeline, _run, end = ended(engine_db, "ALWAYS", "CANCELLED")
    Restarts().refresh(context(engine_db), end + timedelta(hours=1))
    assert len(runs(engine_db, pipeline)) == 1


def test_the_schedule_and_none_conditions_never_restart(engine_db):
    for code, condition in (("A", "SCHEDULE"), ("B", "NONE")):
        pipeline, _run, end = ended(engine_db, condition, "SUCCESS", code)
        Restarts().refresh(context(engine_db), end + timedelta(hours=1))
        assert len(runs(engine_db, pipeline)) == 1


def test_the_environment_suppresses_endings_it_does_not_allow(engine_db):
    pipeline, _run, end = ended(engine_db, "ALWAYS", "SUCCESS")
    later = end + timedelta(hours=1)
    Restarts().refresh(context(engine_db, "NONE"), later)
    Restarts().refresh(context(engine_db, "SCHEDULE|FAILURE"), later)
    assert len(runs(engine_db, pipeline)) == 1  # dev and test: configured, but not started
    Restarts().refresh(context(engine_db, "SCHEDULE|SUCCESS"), later)
    assert len(runs(engine_db, pipeline)) == 2


def test_a_paused_pipeline_does_not_restart(engine_db):
    paused, _run, end = ended(engine_db, "SUCCESS", "SUCCESS", "PAUSED")
    with engine_db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO AUD_PIPELINE_PAUSES (PIPELINE_ID, PAUSED_BY, REASON) "
                "VALUES (:p, 'owner', 'maintenance')"
            ),
            {"p": paused},
        )
    Restarts().refresh(context(engine_db), end + timedelta(hours=1))
    assert len(runs(engine_db, paused)) == 1


def test_a_disabled_project_does_not_restart(engine_db):
    pipeline, _run, end = ended(engine_db, "SUCCESS", "SUCCESS", "OFF")
    with engine_db.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_PROJECTS SET ACTIVE_FLAG='N'"))
    Restarts().refresh(context(engine_db), end + timedelta(hours=1))
    assert len(runs(engine_db, pipeline)) == 1
