"""Deploy, including its seed loads, goes through the authenticated HTTP interface."""

from fastapi.testclient import TestClient

from etl_craft.api.app import create_app
from etl_craft.core.enums import ActionName, ApiRole
from fixtures.actions import act
from fixtures.seeds import seed_project as seed_project


def test_project_deploy_route_loads_seeds_and_checks_the_role(seed_project):
    from etl_craft.engine.project_files import collect

    ctx, _, _ = seed_project
    admin = act(ctx, ActionName.TOKEN_CREATE, name="deployer", role=ApiRole.ADMIN)
    viewer = act(ctx, ActionName.TOKEN_CREATE, name="reader", role=ApiRole.VIEWER)
    body = {"files": collect(ctx.config.project_dir)}
    with TestClient(create_app(ctx)) as client:
        denied = client.post(
            "/api/v1/projects/default/deploy",
            headers={"Authorization": f"Bearer {viewer.token}"},
            json=body,
        )
        assert denied.status_code == 403
        result = client.post(
            "/api/v1/projects/default/deploy",
            headers={"Authorization": f"Bearer {admin.token}"},
            json=body,
        )
        assert result.status_code == 200, result.text
        assert result.json()["seed_loads"][0]["status"] == "LOADED"


def test_developer_validation_retains_seed_failures(seed_project):
    ctx, folder, deploy = seed_project
    (folder / "data.csv").write_text("id|name\nnot-an-integer|Ada\n")
    deploy()  # publishes, then its seed load fails
    developer = act(ctx, ActionName.TOKEN_CREATE, name="deployer", role=ApiRole.DEVELOPER)
    with TestClient(create_app(ctx)) as client:
        response = client.get(
            "/api/v1/projects/default/validation",
            headers={"Authorization": f"Bearer {developer.token}"},
        )
    assert response.status_code == 200, response.text
    failures = [row for row in response.json()["findings"] if row["status"] == "FAIL"]
    assert any("not-an-integer" in row["message"] for row in failures)
