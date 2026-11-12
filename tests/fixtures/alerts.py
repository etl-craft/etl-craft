"""Real project channel metadata shared by API and browser delivery-history tests."""

from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.alerts import AlertStatus
from etl_craft.core.enums import ApiRole, RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.alert_deliveries import DeliveryAttempt, append, event
from etl_craft.services.operations.alert_admission import admit_pending
from etl_craft.services.operations.context import OperationContext
from fixtures.metadata import add_task


def failed_delivery(ctx, pipeline, source):
    """Admit a real event, then append a controlled failure without contacting a receiver."""
    with acting_as(SYSTEM_ACTOR), ctx.engine.begin() as conn:
        add_task(conn, pipeline, "notify", "EMAIL_ALERT", ALERT_CHANNEL="ops", ALERT_ON="FAILURE")
        conn.execute(
            text(
                "INSERT INTO CFG_ALERT_CHANNELS(PROJECT_ID,CHANNEL_NAME,KIND,URL_SECRET,"
                "SIGNING_SECRET,BODY_FORMAT,DEFAULT_ALERT_ON) VALUES"
                "(1,'ops','WEBHOOK','ALERT_URL','ALERT_KEY','JSON','FAILURE')"
            )
        )
        transitions.finalize_pipeline_run(conn, source, RunStatus.FAILED)
    system = OperationContext(
        ctx.engine, ctx.config, SYSTEM_ACTOR, role=ApiRole.ADMIN, project_id=1, project="default"
    )
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(system)
        with ctx.engine.begin() as conn:
            recorded = event(conn, run)
            append(conn, run, recorded, AlertStatus.FAILED, DeliveryAttempt(status_code=503))
    return run
