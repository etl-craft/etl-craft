"""Page controls share role admission and exact target refusals with their public actions."""

from fastapi.testclient import TestClient
from test_action_availability import PROJECT, credential

from etl_craft.api.app import create_app
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole, HttpMethod
from etl_craft.core.enums_access import EnvironmentType, Governance
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import ACTIONS
from etl_craft.services.operations.permissions import has_role
from fixtures.actions import act


def answers(client, headers, **selection):
    response = client.get("/api/v1/capabilities", headers=headers, params=selection)
    assert response.status_code == 200, response.text
    return {a["action"]: a for a in response.json()["actions"]}


def test_page_read_actions_have_server_availability(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        for role in (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER, ApiRole.ADMIN):
            headers = credential(ctx, role)
            deployment = answers(client, headers)
            explain = deployment[ActionName.ACCESS_EXPLAIN]
            required = ACTIONS[ActionName.ACCESS_EXPLAIN].role
            assert explain["available"] is has_role(role, required)
            if not explain["available"]:
                assert f"{required} role is required" in explain["reason"]
            response = client.get(
                f"{PROJECT}/capabilities",
                headers=headers,
                params={"definition": True, "pipeline_code": "P"},
            )
            assert response.status_code == 200, response.text
            validation = next(
                a for a in response.json()["actions"] if a["action"] == ActionName.VALIDATE
            )
            assert validation["available"]


def test_deployment_page_role_matrix(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        callers = {
            role: credential(ctx, role)
            for role in (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER)
        }
        callers[ApiRole.ADMIN] = admin
        code, output = cli_project.run(
            "run", "--pipeline-code", "P", "--reason", "Exercise exact-run page actions"
        )
        assert code == 0, output
        history = client.get(
            f"{PROJECT}/history", headers=admin, params={"pipeline_code": "P", "all": True}
        )
        assert history.status_code == 200, history.text
        run_id = history.json()["entries"][0]["pipeline_run_id"]
        for environment in EnvironmentType:
            for governance in Governance:
                changed = client.post(
                    "/api/v1/projects/set",
                    headers=admin,
                    json={
                        "project": "default",
                        "environment_type": environment,
                        "governance": governance,
                        "reason": "Exercise page action policy",
                    },
                )
                if environment == EnvironmentType.PROD and governance == Governance.RELAXED:
                    assert changed.status_code == 400, changed.text
                    assert "PROD requires STRICT" in changed.json()["message"]
                    continue
                assert changed.status_code == 200, changed.text
                for role, headers in callers.items():
                    found = answers(client, headers)
                    for name, answer in found.items():
                        action = ACTIONS[ActionName(name)]
                        if (
                            action.role in (None, ApiRole.AGENT)
                            or action.name == ActionName.PASSWORD_CHANGE
                        ):
                            continue
                        if action.name in (ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE):
                            assert answer["available"] is (role == ApiRole.ADMIN)
                            if role != ApiRole.ADMIN:
                                assert "expected a deployment administrator" in answer["reason"]
                            continue
                        assert answer["available"] is has_role(role, action.role), (
                            role,
                            name,
                            answer,
                        )
                        if not answer["available"]:
                            assert f"{action.role} role is required" in answer["reason"]
                    response = client.get(
                        f"{PROJECT}/capabilities",
                        headers=headers,
                        params={
                            "definition": True,
                            "pipeline_code": "P",
                            "task_code": "load",
                            "run_id": run_id,
                            "attempt_id": 987654,
                        },
                    )
                    assert response.status_code == 200, response.text
                    project_actions = {a["action"]: a for a in response.json()["actions"]}
                    for name in (
                        ActionName.VALIDATE,
                        ActionName.LOGS,
                        ActionName.RUN_LOG,
                        ActionName.RUN_ZIP,
                    ):
                        assert name in project_actions
                    for name, answer in project_actions.items():
                        action = ACTIONS[ActionName(name)]
                        if action.name in (ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE):
                            continue
                        if not has_role(role, action.role):
                            assert not answer["available"], (role, name, answer)
                            if name not in (ActionName.GENERATE_DOCS, ActionName.PIPELINE_REPARSE):
                                assert str(action.role) in answer["reason"], answer
                        if not answer["available"]:
                            assert answer["reason"], answer
                    for path, params, action_name in (
                        (
                            f"{PROJECT}/capabilities",
                            {"pipeline_code": "P", "run_id": run_id},
                            ActionName.CONTROL,
                        ),
                        (
                            f"{PROJECT}/pipelines/P/runs/{run_id}/tasks/load/items",
                            {},
                            ActionName.ITEM_CONTROL,
                        ),
                    ):
                        response = client.get(path, headers=headers, params=params)
                        assert response.status_code == 200, response.text
                        choices = response.json().get(
                            "actions", response.json().get("availability")
                        )
                        assert choices
                        for answer in choices:
                            if not has_role(role, ACTIONS[action_name].role):
                                assert not answer["available"]
                                assert str(ACTIONS[action_name].role) in answer["reason"]
                            if not answer["available"]:
                                assert answer["reason"]
                    assert ActionName.ACCESS_EXPLAIN in found
                    assert any(a["method"] == HttpMethod.GET for a in found.values())


def test_group_targets_preserve_membership_semantics_and_role_precedence(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    act(ctx, ActionName.GROUP_ADD, name="readers")
    act(
        ctx,
        ActionName.ACCOUNT_ADD,
        name="member",
        role=ApiRole.VIEWER,
        password="long enough password",
    )
    act(ctx, ActionName.GROUP_ADD_MEMBER, name="readers", account="member")
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        for role in (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER):
            selected = answers(
                client, credential(ctx, role), group_name="missing", member_name="missing"
            )
            for answer in selected.values():
                assert not answer["available"]
                assert "admin role is required" in answer["reason"]
        selected = answers(client, admin, group_name="readers", member_name="member")
        assert all(a["available"] for a in selected.values())
        act(ctx, ActionName.GROUP_DISABLE, name="readers")
        selected = answers(client, admin, group_name="readers", member_name="member")
        assert not selected[ActionName.GROUP_ADD_MEMBER]["available"]
        # Removing from a disabled group is explicitly supported by the operation.
        assert selected[ActionName.GROUP_REMOVE_MEMBER]["available"]
        refused = client.post(
            "/api/v1/groups/members", headers=admin, json={"name": "readers", "account": "member"}
        )
        assert refused.status_code == 400, refused.text
        assert selected[ActionName.GROUP_ADD_MEMBER]["reason"] == refused.json()["message"]


def test_project_and_account_targets_report_exact_public_refusal(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    act(ctx, ActionName.ACCOUNT_ADD, name="service", role=ApiRole.VIEWER, kind="SERVICE")
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        selected = answers(client, admin, account_name="service")
        reset = selected[ActionName.ACCOUNT_RESET_PASSWORD]
        assert not reset["available"]
        refused = client.post(
            "/api/v1/accounts/password",
            headers=admin,
            json={"name": "service", "password": "another long password"},
        )
        assert reset["reason"] == refused.json()["message"]
        selected = answers(client, admin, project_code="missing")[ActionName.PROJECT_DISABLE]
        refused = client.post(
            "/api/v1/projects/disable",
            headers=admin,
            json={"project": "missing", "reason": "Inspect target"},
        )
        assert not selected["available"]
        assert selected["reason"] == refused.json()["message"]


def test_task_definition_and_log_refusals_are_read_only_public_answers(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        selected = client.get(
            f"{PROJECT}/capabilities",
            headers=admin,
            params={
                "definition": True,
                "pipeline_code": "P",
                "task_code": "load",
                "attempt_id": 987654,
            },
        )
        assert selected.status_code == 200, selected.text
        found = {a["action"]: a for a in selected.json()["actions"]}
        assert not found[ActionName.ERASE]["available"]
        refused_erasure = client.post(
            f"{PROJECT}/erasure",
            headers=admin,
            json={
                "table": "main.missing",
                "column": "id",
                "value": "subject",
                "reason": "Check erasure configuration",
            },
        )
        assert found[ActionName.ERASE]["reason"] == refused_erasure.json()["message"]
        assert not found[ActionName.DATA_PROVENANCE]["available"]
        assert (
            "HANDLER=PYTHON; expected SQL SCD1/SCD2" in found[ActionName.DATA_PROVENANCE]["reason"]
        )
        assert not found[ActionName.LOGS]["available"]
        refused = client.get(f"{PROJECT}/attempts/987654/log", headers=admin)
        assert found[ActionName.LOGS]["reason"] == refused.json()["message"]
        response = client.get(
            f"{PROJECT}/capabilities",
            headers=admin,
            params={
                "definition": True,
                "pipeline_code": "P",
                "run_id": 987654,
            },
        )
        assert response.status_code == 404, response.text
        for endpoint in ("/run-log", "/run-zip"):
            refused = client.get(
                PROJECT + endpoint,
                headers=admin,
                params={"pipeline_code": "P", "run_id": 987654},
            )
            assert response.json()["message"] == refused.json()["message"]
        code, output = cli_project.run(
            "run", "--pipeline-code", "P", "--reason", "Check log availability"
        )
        assert code == 0, output
        history = client.get(
            f"{PROJECT}/history", headers=admin, params={"pipeline_code": "P", "all": True}
        )
        assert history.status_code == 200, history.text
        run_id = history.json()["entries"][0]["pipeline_run_id"]
        selected = client.get(
            f"{PROJECT}/capabilities",
            headers=admin,
            params={
                "definition": True,
                "pipeline_code": "P",
                "run_id": run_id,
            },
        )
        assert selected.status_code == 200, selected.text
        found = {a["action"]: a for a in selected.json()["actions"]}
        assert found[ActionName.RUN_LOG]["available"]
        assert found[ActionName.RUN_ZIP]["available"]


def test_role_commands_and_channel_state_match_public_refusals(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    act(ctx, ActionName.ROLE_CREATE, name="analyst")
    with TestClient(create_app(ctx)) as client:
        admin = credential(ctx, ApiRole.ADMIN)
        malformed = client.get(
            "/api/v1/capabilities", headers=admin, params={"role_action": str(ActionName.RUN)}
        )
        assert malformed.status_code == 400, malformed.text
        assert "role_action requires role_name" in malformed.json()["message"]
        selected = answers(client, admin, role_name="analyst", role_action=str(ActionName.RUN))
        assert selected[ActionName.ROLE_ADD_ACTION]["available"]
        assert not selected[ActionName.ROLE_REMOVE_ACTION]["available"]
        refused = client.post(
            "/api/v1/roles/actions/remove",
            headers=admin,
            json={"name": "analyst", "action": ActionName.RUN},
        )
        assert selected[ActionName.ROLE_REMOVE_ACTION]["reason"] == refused.json()["message"]
        for role in (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER):
            selected = answers(
                client, credential(ctx, role), role_name="analyst", role_action=str(ActionName.RUN)
            )
            assert all(
                not a["available"] and "admin role is required" in a["reason"]
                for a in selected.values()
            )
        selected = answers(client, admin, project_code="default", channel_name="missing")
        refused = client.post(
            "/api/v1/alert-channels/disable",
            headers=admin,
            json={"project": "default", "name": "missing", "reason": "Inspect target"},
        )
        assert not selected[ActionName.ALERT_CHANNEL_DISABLE]["available"]
        assert selected[ActionName.ALERT_CHANNEL_DISABLE]["reason"] == refused.json()["message"]


def test_rehash_target_contract_is_the_same_read_only_refusal(cli_project):
    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    with TestClient(create_app(ctx)) as client:
        for role in (ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.DEVELOPER, ApiRole.ADMIN):
            headers = credential(ctx, role)
            response = client.get(
                f"{PROJECT}/capabilities",
                headers=headers,
                params={
                    "definition": True,
                    "rehash_target": "main.missing",
                },
            )
            assert response.status_code == 200, response.text
            answer = next(
                a for a in response.json()["actions"] if a["action"] == ActionName.REHASH_PLAN
            )
            assert not answer["available"]
            refused = client.get(
                f"{PROJECT}/rehash", headers=headers, params={"target": "main.missing"}
            )
            assert answer["reason"] == refused.json()["message"]
            required = ACTIONS[ActionName.REHASH_PLAN].role
            if not has_role(role, required):
                assert f"{required} role is required" in answer["reason"]
            else:
                assert (
                    "expected one common ordered MERGE_COMPARE_COLUMNS contract" in answer["reason"]
                )


def test_binding_availability_uses_its_exact_pipeline_and_tag(cli_project):
    import json

    from sqlalchemy import text

    ctx = OperationContext(cli_project.engine, cli_project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    headers = credential(ctx, ApiRole.DEVELOPER, "pipeline-manager")
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS=:tags WHERE PIPELINE_CODE='P'"),
            {"tags": json.dumps({"TAGS": ["team"]})},
        )
    for scope in ({"pipeline": "P"}, {"tag": "team"}):
        act(
            ctx,
            ActionName.ACCESS_GRANT,
            project="default",
            account="pipeline-manager",
            role="CAN_MANAGE",
            reason="Delegate the exact scope",
            **scope,
        )
    with TestClient(create_app(ctx)) as client:
        for selection in ({"pipeline_code": "P"}, {"binding_tag": "team"}):
            response = client.get(
                f"{PROJECT}/capabilities", headers=headers, params={"definition": True, **selection}
            )
            assert response.status_code == 200, response.text
            found = {a["action"]: a for a in response.json()["actions"]}
            assert found[ActionName.ACCESS_GRANT]["available"]
            assert found[ActionName.ACCESS_REVOKE]["available"]
        response = client.get(
            f"{PROJECT}/capabilities", headers=headers, params={"definition": True}
        )
        assert response.status_code == 200, response.text
        found = {a["action"]: a for a in response.json()["actions"]}
        assert not found[ActionName.ACCESS_REVOKE]["available"]
        assert "expected CAN_MANAGE" in found[ActionName.ACCESS_REVOKE]["reason"]
