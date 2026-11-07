"""A pipeline's restart condition shows in its view and in the catalog, in words."""

from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.catalog.collect import build_catalog
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.metadata import add_pipeline


def test_the_view_and_the_catalog_say_how_a_watcher_restarts(engine_db):
    with engine_db.engine.begin() as conn:
        add_pipeline(conn, "SCHEDULED")
        watcher = add_pipeline(conn, "WATCH")
        conn.execute(
            text(
                "UPDATE CFG_PIPELINES SET AUTO_RESTART_CONDITION='SUCCESS|SKIPPED' "
                "WHERE PIPELINE_ID=:i"
            ),
            {"i": watcher},
        )
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    views = {p.pipeline_code: p for p in act(ctx, ActionName.PIPELINES).pipelines}
    assert views["SCHEDULED"].auto_restart_condition == "SCHEDULE"
    assert views["SCHEDULED"].restart_note is None
    assert views["WATCH"].auto_restart_condition == "SUCCESS|SKIPPED"
    assert views["WATCH"].restart_note == "Restarts after a success or a skipped run"
    catalog = build_catalog(engine_db.engine, engine_db.config)
    assert catalog.pipelines["WATCH"].row.auto_restart_condition == "SUCCESS|SKIPPED"


def test_the_list_and_the_detail_carry_the_pipelines_description(engine_db):
    with engine_db.engine.begin() as conn:
        documented = add_pipeline(conn, "DOCUMENTED")
        add_pipeline(conn, "PLAIN")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET DESCRIPTION=:text WHERE PIPELINE_ID=:i"),
            {"text": "Loads the orders and publishes the mart.", "i": documented},
        )
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    listed = {p.pipeline_code: p for p in act(ctx, ActionName.PIPELINES).pipelines}
    assert listed["DOCUMENTED"].description == "Loads the orders and publishes the mart."
    assert listed["PLAIN"].description is None
    detail = act(ctx, ActionName.PIPELINE, pipeline_code="DOCUMENTED")
    assert detail.description == "Loads the orders and publishes the mart."
