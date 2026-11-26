"""Re-parse admission and read-only availability through public interfaces."""

import pytest
from fastapi.testclient import TestClient

from etl_craft.api.app import create_app
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.enums_access import EnvironmentType, Governance
from etl_craft.core.errors import ExitCode
from etl_craft.engine.project_files import collect
from etl_craft.services.operations import OperationContext
from fixtures.actions import act

PROJECT = "/api/v1/projects/default"


def credential(ctx, role, name=None):
    pool = "default" if role == ApiRole.AGENT else None
    token = act(ctx, ActionName.TOKEN_CREATE, name=name or role, role=role, pool=pool)
    return {"Authorization": f"Bearer {token.token}"}


def test_refresh_availability_matches_public_admission(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        callers = {role: credential(ctx, role) for role in ApiRole if role != ApiRole.ADMIN}
        callers[ApiRole.ADMIN] = admin
        for environment in EnvironmentType:
            for governance in Governance:
                changed = client.post(
                    "/api/v1/projects/set",
                    headers=admin,
                    json={
                        "project": "default",
                        "environment_type": environment,
                        "governance": governance,
                        "reason": "Exercise re-parse admission",
                    },
                )
                if (environment, governance) == (EnvironmentType.PROD, Governance.RELAXED):
                    assert changed.status_code == 400, changed.text
                    assert changed.json()["exit_code"] == ExitCode.USAGE
                    assert "PROD requires STRICT" in changed.json()["message"]
                    continue
                assert changed.status_code == 200, changed.text
                for role, headers in callers.items():
                    for selection in ({}, {"pipeline_code": "P"}):
                        assert_reparse_availability(client, role, headers, governance, selection)


def assert_reparse_availability(client, role, headers, governance, selection):
    view = client.get(
        f"{PROJECT}/capabilities", headers=headers, params={"definition": True, **selection}
    )
    response = client.post(f"{PROJECT}/pipelines/re-parse", headers=headers, json=selection)
    if role == ApiRole.AGENT:
        assert view.status_code == response.status_code == 403
        assert response.json()["exit_code"] == ExitCode.PERMISSION_DENIED
        return
    assert view.status_code == 200, view.text
    reparse = next(a for a in view.json()["actions"] if a["action"] == ActionName.PIPELINE_REPARSE)
    allowed = role == ApiRole.ADMIN and governance == Governance.RELAXED
    assert reparse["available"] is allowed, (role, governance, reparse)
    assert response.status_code == (200 if allowed else 403), response.text
    if not allowed:
        assert reparse["reason"] == response.json()["message"]
        assert response.json()["exit_code"] == ExitCode.PERMISSION_DENIED


@pytest.mark.parametrize("role", (ApiRole.ADMIN, ApiRole.VIEWER))
def test_deployment_availability_without_an_active_project(engine_db, role):
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        response = client.post(
            "/api/v1/projects/disable",
            headers=admin,
            json={"project": "default", "reason": "Leave no active project"},
        )
        assert response.status_code == 200, response.text
        headers = admin if role == ApiRole.ADMIN else credential(ctx, role)
        response = client.get("/api/v1/capabilities", headers=headers)
        assert response.status_code == 200, response.text
        add = next(a for a in response.json()["actions"] if a["action"] == ActionName.PROJECT_ADD)
        assert add["available"] is (role == ApiRole.ADMIN)
        if role == ApiRole.VIEWER:
            assert "admin role is required" in add["reason"]


def test_cli_refuses_strict_refresh_and_deploy_still_refreshes(cli_project):
    p = cli_project
    for selection in ((), ("--pipeline", "P")):
        code, output = p.run("pipelines", "re-parse", *selection)
        assert code == ExitCode.PERMISSION_DENIED, output
        for part in ("default", "STRICT", "RELAXED", "etl-craft deploy"):
            assert part in output
    code, output = p.run("deploy", "--format", "json")
    assert code == 0 and '"reparses": [' in output and '"pipeline_code": "P"' in output, output
    code, output = p.run(
        "project",
        "set",
        "--project",
        "default",
        "--governance",
        "RELAXED",
        "--reason",
        "Test standalone re-parse",
    )
    assert code == 0, output
    for selection in ((), ("--pipeline", "P")):
        code, output = p.run("pipelines", "re-parse", *selection)
        assert code == 0, output


def assert_self_disable_reason(name, message):
    for part in (
        name,
        "signed-in account",
        "expected a different account",
        "another administrator",
    ):
        assert part in message


def test_authorized_deploy_can_refresh_without_a_standalone_refresh_grant(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    headers = credential(ctx, ApiRole.DEVELOPER, "release-service")
    act(
        ctx,
        ActionName.ACCESS_GRANT,
        project="default",
        account="release-service",
        action=ActionName.DEPLOY,
        reason="Permit this service to deploy",
    )
    with TestClient(create_app(ctx)) as client:
        denied = client.post(f"{PROJECT}/pipelines/re-parse", headers=headers, json={})
        assert denied.status_code == 403, denied.text
        forged = client.post(
            f"{PROJECT}/pipelines/re-parse", headers=headers, json={"internal": True}
        )
        assert forged.status_code == 400, forged.text
        deployed = client.post(
            f"{PROJECT}/deploy",
            headers=headers,
            json={"files": collect(cli_project.config.project_dir)},
        )
        assert deployed.status_code == 200, deployed.text
        assert any(
            row["pipeline_code"] == "P" and row["status"] == "SUCCESS"
            for row in deployed.json()["reparses"]
        )


def test_account_disable_and_its_availability_share_self_protection(engine_db):
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    headers = credential(ctx, ApiRole.ADMIN, "owner")
    credential(ctx, ApiRole.ADMIN, "other-admin")
    credential(ctx, ApiRole.VIEWER, "reader")
    with TestClient(create_app(ctx)) as client:
        for name in ("owner", "reader"):
            answer = client.get(
                "/api/v1/capabilities", params={"account_name": name}, headers=headers
            )
            assert answer.status_code == 200, answer.text
            disable = next(
                action
                for action in answer.json()["actions"]
                if action["action"] == ActionName.ACCOUNT_DISABLE
            )
            response = client.post("/api/v1/accounts/disable", json={"name": name}, headers=headers)
            assert disable["available"] is (name == "reader")
            if name == "owner":
                assert response.status_code == 403, response.text
                refusal = response.json()
                assert refusal["exit_code"] == ExitCode.PERMISSION_DENIED
                assert_self_disable_reason(name, refusal["message"])
                assert disable["reason"] == refusal["message"]
            else:
                assert response.status_code == 200, response.text
                rows = response.json()["accounts"]
                assert (
                    next(account for account in rows if account["name"] == name)["active_flag"]
                    == "N"
                )


def test_cli_cannot_disable_the_signed_in_account(cli_project):
    p = cli_project
    code, output = p.run(
        "account", "add", "--name", "other-admin", "--kind", "SERVICE", "--role", "admin"
    )
    assert code == 0, output

    code, output = p.run("account", "disable", "--name", "test-admin")
    assert code == ExitCode.PERMISSION_DENIED, output
    assert_self_disable_reason("test-admin", output)
    code, output = p.run("account", "disable", "--name", "other-admin")
    assert code == 0, output


def test_definition_pause_actions_follow_permission_and_current_state(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    admin = credential(ctx, ApiRole.ADMIN)
    viewer = credential(ctx, ApiRole.VIEWER)
    with TestClient(create_app(ctx)) as client:
        for task in (None, "load"):
            scope = {"pipeline_code": "P", **({"task_code": task} if task is not None else {})}
            request = {"definition": True, **scope}

            def controls(headers, request=request):
                response = client.get(f"{PROJECT}/capabilities", headers=headers, params=request)
                assert response.status_code == 200, response.text
                return {
                    (answer["control"], answer["replacement"]): answer
                    for answer in response.json()["actions"]
                    if answer["action"] == ActionName.CONTROL
                }

            before = controls(admin)
            assert before[("PAUSE", False)]["available"]
            assert not before[("RESUME", False)]["available"]
            assert any(
                part in before[("RESUME", False)]["reason"] for part in ("no active", "not paused")
            )
            assert not before[("PAUSE", True)]["available"]
            assert all(
                not answer["available"] and answer["reason"] for answer in controls(viewer).values()
            )
            response = client.post(
                f"{PROJECT}/controls",
                headers=admin,
                json={
                    **scope,
                    "action": "PAUSE",
                    "reason": "Check pause availability",
                    **({"outcome": "SKIPPED"} if task is not None else {}),
                },
            )
            assert response.status_code == 200, response.text
            after = controls(admin)
            assert not after[("PAUSE", False)]["available"]
            assert "already" in after[("PAUSE", False)]["reason"]
            assert after[("RESUME", False)]["available"]
            assert after[("PAUSE", True)]["available"]


def test_platform_availability_tracks_token_and_announcement_state(engine_db):
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    admin = credential(ctx, ApiRole.ADMIN)
    viewer = credential(ctx, ApiRole.VIEWER)
    revoked = act(ctx, ActionName.TOKEN_CREATE, name="retired", role=ApiRole.VIEWER)
    with TestClient(create_app(ctx)) as client:
        created = client.post(
            "/api/v1/announcements",
            headers=admin,
            json={"message": "Maintenance", "reason": "Exercise the announcement action"},
        )
        assert created.status_code == 200, created.text
        notice = next(
            row for row in created.json()["announcements"] if row["message"] == "Maintenance"
        )
        for endpoint, selection, body in (
            (
                "/tokens/revoke",
                {"token_id": revoked.metadata.token_id},
                {"token_id": revoked.metadata.token_id},
            ),
            (
                "/announcements/end",
                {"announcement_id": notice["announcement_id"]},
                {"announcement_id": notice["announcement_id"], "reason": "Maintenance ended"},
            ),
        ):

            def read(headers, selection=selection):
                response = client.get("/api/v1/capabilities", headers=headers, params=selection)
                assert response.status_code == 200, response.text
                return response.json()["actions"][0]

            assert read(admin)["available"]
            viewer_refusal = read(viewer)
            assert not viewer_refusal["available"]
            assert "admin role is required" in viewer_refusal["reason"]
            applied = client.post(f"/api/v1{endpoint}", headers=admin, json=body)
            assert applied.status_code == 200, applied.text
            unavailable = read(admin)
            assert not unavailable["available"]
            refused = client.post(f"/api/v1{endpoint}", headers=admin, json=body)
            assert unavailable["reason"] == refused.json()["message"]
