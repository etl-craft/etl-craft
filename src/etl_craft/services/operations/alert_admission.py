"""Observe durable source events and admit only the configured alert task."""

from datetime import UTC, datetime, timedelta

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.alerts import AlertStatus, triggers
from etl_craft.core.enums import YesNo
from etl_craft.core.errors import MetadataError
from etl_craft.engine.alert_deliveries import AlertEvent, append
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.engine.repository.tasks import fetch_task_parameters
from etl_craft.engine.run_scopes import TaskSelection, create_manual_run
from etl_craft.services.operations.context import OperationContext

ADMISSION_BATCH = 100


def admit_pending(ctx: OperationContext, now: datetime | None = None) -> tuple[int, ...]:
    """Commit selected ordinary runs and event receipts together, without making HTTP calls."""
    now = now or datetime.now(UTC)
    admitted = []
    with ctx.engine.connect() as conn:
        subscriptions = conn.execute(statement(conn, "alert_subscriptions")).all()
    for subscription in subscriptions:
        with (
            acting_as(SYSTEM_ACTOR),
            selected_project(subscription.project_id),
            ctx.engine.begin() as conn,
        ):
            conn.execute(
                statement(conn, "run_overrides_lock"), {"project_id": subscription.project_id}
            ).one()
            params = fetch_task_parameters(conn, subscription.task_id)
            channel = conn.execute(
                statement(conn, "alert_channel"),
                {
                    "project_id": subscription.project_id,
                    "channel_name": subscription.channel_name,
                },
            ).one_or_none()
            if channel is None:
                raise MetadataError(
                    f"task {subscription.task_code}: ALERT_CHANNEL={subscription.channel_name!r} "
                    "is missing; expected a project channel; ask an administrator to configure it"
                )
            if channel.active_flag != YesNo.YES:
                continue
            for selector in triggers(params.get("ALERT_ON", channel.default_alert_on)):
                minutes = (
                    int(selector.rsplit("_", 1)[1]) if selector.startswith("GATE_WAIT_OVER_") else 0
                )
                prefix = f"task:{subscription.task_id}:channel:{channel.channel_id}:{selector}:"
                events = conn.execute(
                    statement(conn, "alert_events"),
                    {
                        "pipeline_id": subscription.pipeline_id,
                        "channel_id": channel.channel_id,
                        "selector": selector,
                        "gate_before": now - timedelta(minutes=minutes),
                        "event_prefix": prefix,
                    },
                ).all()
                for row in events:
                    run_id = create_manual_run(
                        conn,
                        subscription.pipeline_id,
                        SYSTEM_ACTOR,
                        TaskSelection((subscription.task_id,), ignore_dependencies=True),
                        "alert:" + row.event_id,
                        row.run_date,
                    )
                    source = AlertEvent(
                        row.source_run_id,
                        channel.channel_id,
                        row.event_id,
                        selector,
                        row.source_task_id,
                        row.source_attempt_id,
                    )
                    append(conn, run_id, source, AlertStatus.ADMITTED)
                    admitted.append(run_id)
                    if len(admitted) >= ADMISSION_BATCH:
                        return tuple(admitted)
    return tuple(admitted)
