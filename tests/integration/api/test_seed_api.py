"""Deploy, including its seed loads, goes through the authenticated HTTP interface."""

import pytest
from fastapi.testclient import TestClient

from etl_craft.api.app import create_app
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.engine.project_files import collect
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task
from fixtures.seeds import seed_project as seed_project


def test_project_deploy_route_loads_seeds_and_checks_the_role(seed_project):
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


@pytest.mark.parametrize("operation", ["plan", "deploy", "validation"])
def test_missing_alert_channel_names_admin_remedy(seed_project, operation):
    ctx, _, _ = seed_project
    config = ctx.config.project_dir / "config"
    config.mkdir()
    (config / "pipelines.csv").write_text(
        "PIPELINE_CODE,PIPELINE_NAME,REFRESH_TYPE,ACTIVE_FLAG\nALERTS,Alerts,FULL,Y\n"
    )
    (config / "tasks.csv").write_text(
        "PIPELINE_CODE,TASK_CODE,TASK_TYPE,HANDLER,ACTIVE_FLAG\nALERTS,notify,ETL,ALERT,Y\n"
    )
    (config / "task_parameters.csv").write_text(
        "PIPELINE_CODE,TASK_CODE,PARAMETER_NAME,PARAMETER_VALUE,ACTIVE_FLAG\n"
        "ALERTS,notify,ALERT_CHANNEL,missing_ops,Y\n"
    )
    admin = act(ctx, ActionName.TOKEN_CREATE, name="alert-deployer", role=ApiRole.ADMIN)
    developer = act(ctx, ActionName.TOKEN_CREATE, name="alert-validator", role=ApiRole.DEVELOPER)
    with TestClient(create_app(ctx)) as client:
        if operation == "validation":
            with ctx.engine.begin() as conn:
                add_task(
                    conn,
                    add_pipeline(conn, "ALERTS"),
                    "notify",
                    "ALERT",
                    ALERT_CHANNEL="missing_ops",
                )
            response = client.get(
                "/api/v1/projects/default/validation",
                headers={"Authorization": f"Bearer {developer.token}"},
            )
        else:
            response = client.post(
                "/api/v1/projects/default/deploy",
                headers={"Authorization": f"Bearer {admin.token}"},
                json={"files": collect(ctx.config.project_dir), "plan": operation == "plan"},
            )
    assert response.status_code == 200, response.text
    report = response.json()
    if operation != "validation":
        report = report["config"]
        assert report["failed"]
        assert not report["applied"]
    failures = [row for row in report["findings"] if row["status"] == "FAIL"]
    failure = next(
        row
        for row in failures
        if row["where"] == "ALERTS.notify" and "ALERT_CHANNEL" in row["message"]
    )
    assert "missing_ops" in failure["message"]
    assert "missing or inactive" in failure["message"]
    assert "administrator" in failure["message"]
    assert "etl-craft alert-channel set" in failure["message"]
