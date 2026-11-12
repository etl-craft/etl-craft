"""Only administrators authorize routing, with reference names rather than secret values."""

from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR, Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import PermissionDeniedError, UsageError
from etl_craft.services.operations import OperationContext
from fixtures.actions import act


@pytest.fixture
def admin(engine_db):
    return OperationContext(
        engine_db.engine,
        engine_db.config,
        SYSTEM_ACTOR,
        role=ApiRole.ADMIN,
        project="default",
        project_id=1,
    )


def set_channel(ctx, **fields):
    return act(
        ctx,
        ActionName.ALERT_CHANNEL_SET,
        project="default",
        name="ops",
        kind="WEBHOOK",
        url_secret="OPS_URL",
        signing_secret="OPS_KEY",
        reason="Approved routing",
        **fields,
    )


def test_admin_channel_lifecycle_has_typed_attributed_history(admin):
    ctx = replace(admin, actor=Actor("channel_owner", ActorKind.USER))
    result = set_channel(ctx)
    channel = result.channels[0]
    assert channel.channel_name == "ops" and channel.url_secret == "OPS_URL"
    assert channel.default_alert_on == "FAILURE"
    act(ctx, ActionName.ALERT_CHANNEL_DISABLE, project="default", name="ops", reason="Retire route")
    retired = act(ctx, ActionName.ALERT_CHANNEL_LIST, project="default").channels[0]
    assert retired.active_flag == "N"
    assert set_channel(ctx).channels[0].channel_id == channel.channel_id
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ACTOR AS actor FROM AUD_CFG_ALERT_CHANNELS_HISTORY WHERE CHANNEL_NAME='ops'"
            )
        ).all()
    assert len(rows) >= 3 and all(row.actor == "channel_owner" for row in rows)


@pytest.mark.parametrize("role", [ApiRole.DEVELOPER, ApiRole.OPERATOR, ApiRole.VIEWER])
def test_project_developers_cannot_manage_or_read_channel_references(admin, role):
    set_channel(admin)
    caller = replace(admin, role=role)
    for action, fields in (
        (ActionName.ALERT_CHANNEL_LIST, {}),
        (ActionName.ALERT_CHANNEL_DISABLE, {"name": "ops", "reason": "unauthorized"}),
    ):
        with pytest.raises(PermissionDeniedError, match="admin"):
            act(caller, action, project="default", **fields)
    with pytest.raises(PermissionDeniedError, match="admin"):
        set_channel(caller)
    assert (
        act(admin, ActionName.ALERT_CHANNEL_LIST, project="default").channels[0].active_flag == "Y"
    )


def test_admin_channel_refuses_literal_url_without_echoing_it(admin):
    private = "https://receiver.invalid/private-token"
    with pytest.raises(UsageError, match=r"channel ops.*URL_SECRET.*variable") as caught:
        act(
            admin,
            ActionName.ALERT_CHANNEL_SET,
            project="default",
            name="ops",
            kind="WEBHOOK",
            url_secret=private,
            signing_secret="OPS_KEY",
            reason="Bad input",
        )
    assert private not in str(caught.value)
    with admin.engine.connect() as conn:
        assert not conn.execute(text("SELECT CHANNEL_ID AS id FROM CFG_ALERT_CHANNELS")).first()


def test_relaxed_project_sql_cannot_change_admin_routing(admin, engine_db):
    from sqlalchemy.exc import DBAPIError
    from test_environments import governance, outside

    set_channel(admin)
    governance(engine_db, "RELAXED")
    with pytest.raises(DBAPIError, match=r"admin, audit|etl_craft_actor|written only"):
        outside(engine_db, "UPDATE CFG_ALERT_CHANNELS SET URL_SECRET='OTHER_URL'")
    channel = act(admin, ActionName.ALERT_CHANNEL_LIST, project="default").channels[0]
    assert channel.url_secret == "OPS_URL"
