"""Every run and task run carries a readable label beside its integer id, fixed at creation."""

from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.engine import transitions
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, start_run


def test_a_run_and_its_task_run_are_labelled_when_created_and_shown(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ORDERS")
        task = add_task(conn, pipeline, "extract")
        run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
    with engine_db.engine.connect() as conn:
        started, label = conn.execute(
            text("SELECT START_DATE AS started, RUN_LABEL AS label FROM AUD_PIPELINES_RUN_LOG")
        ).one()
        task_label = conn.execute(
            text("SELECT TASK_RUN_LABEL AS l FROM AUD_TASK_RUN_LOG")
        ).scalar_one()
    stamp = started.strftime("%Y-%m-%d %H:%M:%S") if hasattr(started, "strftime") else started[:19]
    assert label == f"ORDERS-{stamp}-{run}"
    assert task_label.startswith("ORDERS-extract-") and task_label.endswith(f"-{summary}")

    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    shown = act(ctx, ActionName.STATUS, pipeline_code="ORDERS", run_id=run)
    assert shown.run.run_label == label


def test_the_migration_backfill_names_existing_runs_as_creation_does(engine_db):
    from etl_craft.dialects.engine import for_engine

    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ORDERS")
        task = add_task(conn, pipeline, "extract")
        run = start_run(conn, pipeline)
        transitions.find_or_create_task_run(conn, task, run)
        created = conn.execute(
            text(
                "SELECT RUN_LABEL AS a, (SELECT TASK_RUN_LABEL FROM AUD_TASK_RUN_LOG) AS b "
                "FROM AUD_PIPELINES_RUN_LOG"
            )
        ).one()
        conn.execute(text("UPDATE AUD_PIPELINES_RUN_LOG SET RUN_LABEL=''"))
        conn.execute(text("UPDATE AUD_TASK_RUN_LOG SET TASK_RUN_LABEL=''"))
        migration = for_engine(engine_db.engine).migrations_dir() / "0087_run_labels.sql"
        backfill = migration.read_text().split("CREATE TRIGGER")[
            0
        ]  # the statements before the triggers
        for step in backfill.split(";"):
            if step.strip().startswith("UPDATE"):
                conn.execute(text(step))
        backfilled = conn.execute(
            text(
                "SELECT RUN_LABEL AS a, (SELECT TASK_RUN_LABEL FROM AUD_TASK_RUN_LOG) AS b "
                "FROM AUD_PIPELINES_RUN_LOG"
            )
        ).one()
    assert tuple(backfilled) == tuple(created)
