"""Role administration and explanations use the generated, authenticated HTTP routes."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api.app import create_app
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.metadata import add_pipeline


def test_roles_bindings_and_explanations_take_effect_on_the_next_request(engine_db):
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    admin = act(ctx, ActionName.TOKEN_CREATE, name="owner", role=ApiRole.ADMIN)
    viewer = act(ctx, ActionName.TOKEN_CREATE, name="analyst", role=ApiRole.VIEWER)
    with ctx.engine.begin() as conn:
        add_pipeline(conn, "P")
    client = TestClient(create_app(ctx))
    headers = {"Authorization": "Bearer " + admin.token}
    reader = {"Authorization": "Bearer " + viewer.token}
    role = {"name": "runner", "actions": ["run"]}
    assert client.post("/api/v1/roles", json=role, headers=reader).status_code == 403
    made = client.post("/api/v1/roles", json=role, headers=headers)
    assert made.status_code == 200, made.text
    listed = client.get("/api/v1/roles", headers=reader)
    assert listed.status_code == 200
    assert any(r["name"] == "runner" and r["actions"] == ["run"] for r in listed.json()["roles"])
    binding = {"project": "default", "account": "analyst", "role": "runner", "reason": "test"}
    given = client.post("/api/v1/access/grants", json=binding, headers=headers)
    assert given.status_code == 200, given.text
    assert given.json()["schema"] == "etl-craft/access/2"
    assert given.json()["change"]["binding"]["role"] == "runner"
    probe = {"project": "default", "account": "analyst", "action": "run", "pipeline": "P"}
    assert client.get("/api/v1/access/explain", params=probe, headers=reader).status_code == 403
    explained = client.get("/api/v1/access/explain", params=probe, headers=headers)
    assert explained.status_code == 200, explained.text
    assert explained.json()["allowed"] and explained.json()["allowed_by"]
    revoked = client.post("/api/v1/access/revocations", json=binding, headers=headers)
    assert revoked.status_code == 200, revoked.text
    refused = client.get("/api/v1/access/explain", params=probe, headers=headers)
    assert refused.status_code == 200 and not refused.json()["allowed"]
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM CFG_ROLES WHERE ROLE_NAME='runner'")
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM AUD_ACTIONS WHERE COMMAND='role create' "
                    "AND OUTCOME='REFUSED'"
                )
            ).scalar_one()
            == 1
        )
