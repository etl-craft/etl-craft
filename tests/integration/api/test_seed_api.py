"""Seed apply uses the project action through the authenticated HTTP interface."""

from fastapi.testclient import TestClient

from etl_craft.api.app import create_app
from etl_craft.core.enums import ActionName, ApiRole
from fixtures.actions import act
from fixtures.seeds import seed_project as seed_project


def test_project_seed_route_and_role(seed_project):
    ctx, _, _ = seed_project
    developer = act(ctx, ActionName.TOKEN_CREATE, name="deployer", role=ApiRole.DEVELOPER)
    viewer = act(ctx, ActionName.TOKEN_CREATE, name="reader", role=ApiRole.VIEWER)
    with TestClient(create_app(ctx)) as client:
        denied = client.post(
            "/api/v1/projects/default/seeds",
            headers={"Authorization": f"Bearer {viewer.token}"},
            json={},
        )
        assert denied.status_code == 403
        result = client.post(
            "/api/v1/projects/default/seeds",
            headers={"Authorization": f"Bearer {developer.token}"},
            json={},
        )
        assert result.status_code == 200, result.text
        assert result.json()["loads"][0]["status"] == "LOADED"


def test_developer_validation_retains_seed_failures(seed_project):
    ctx, folder, publish = seed_project
    (folder / "data.csv").write_text("id|name\nnot-an-integer|Ada\n")
    publish()
    developer = act(ctx, ActionName.TOKEN_CREATE, name="deployer", role=ApiRole.DEVELOPER)
    with TestClient(create_app(ctx)) as client:
        response = client.get(
            "/api/v1/projects/default/validation",
            headers={"Authorization": f"Bearer {developer.token}"},
        )
    assert response.status_code == 200, response.text
    failures = [row for row in response.json()["findings"] if row["status"] == "FAIL"]
    assert any("not-an-integer" in row["message"] for row in failures)
