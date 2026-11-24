"""Every action's admission crosses the CLI client and generated HTTP route with scoped roles.

Operations are replaced with an admission probe so this matrix cannot start tasks or mutate
unrelated resources. Their own validation and effects are covered by the operation suites.
"""

import base64
import json
import logging
import re
from dataclasses import fields, replace
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api import routes
from etl_craft.api.app import create_app
from etl_craft.cli.client import ApiClient
from etl_craft.core.actor import SYSTEM_ACTOR, Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ActionScope, ApiRole, HttpMethod, Placement
from etl_craft.core.enums_access import Permission
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.services.operations import OperationContext, authorization
from etl_craft.services.operations.actions import (
    ACTIONS,
    PROJECT_MANAGE_ACTIONS,
    action_path,
    admitted,
)
from etl_craft.services.operations.roles import bindable
from etl_craft.services.operations.serialization import encode
from fixtures.actions import act, build
from fixtures.metadata import add_pipeline


class AdmittedError(Exception):
    """The action passed admission; its business operation must not run in this matrix."""


@pytest.fixture
def matrix(engine_db, monkeypatch):
    admin = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    token = act(admin, ActionName.TOKEN_CREATE, name="matrix", role=ApiRole.VIEWER)
    with acting_as(SYSTEM_ACTOR), admin.engine.begin() as conn:
        add_pipeline(conn, "P")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS=:tags WHERE PIPELINE_CODE='P'"),
            {"tags": json.dumps({"TAGS": ["team"]})},
        )
    caller = replace(
        admin,
        actor=Actor("matrix", ActorKind.SERVICE),
        role=ApiRole.VIEWER,
        project="default",
        project_id=1,
    )
    # Identity-to-pipeline resolution is covered by the real ID and cross-project refusal tests.
    monkeypatch.setattr(
        authorization,
        "request_codes",
        lambda conn, spec, request: ["P"] if spec.scope == ActionScope.PIPELINE else [],
    )

    def probe(ctx, name, request):
        with admitted(ctx, name, request):
            raise AdmittedError(name)

    monkeypatch.setattr(logging.getLogger("etl_craft.api.app"), "disabled", True)
    monkeypatch.setattr(routes, "invoke", probe)
    client = TestClient(create_app(admin))
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)

    class Opener:
        def open(self, request, timeout):
            url = urlsplit(request.full_url)
            response = client.request(
                request.get_method(),
                url.path + ("?" + url.query if url.query else ""),
                content=request.data,
                headers=dict(request.header_items()),
            )
            from io import BytesIO
            from urllib.error import HTTPError

            raise HTTPError(
                request.full_url, response.status_code, response.text, {}, BytesIO(response.content)
            )

    monkeypatch.setattr("etl_craft.core.http_client.build_opener", lambda *args: Opener())
    return admin, caller, client, token.token


def accepted(ctx, name, request):
    try:
        with admitted(ctx, name, request):
            return True
    except (PermissionDeniedError, ResourceNotFoundError):
        return False


def built_in_allows(spec, role, reach, required):
    """Independent account-viewer plus built-in-level oracle for the admission-only probe."""
    if required == ApiRole.AGENT:
        return False
    if required is None:
        return True
    project_level = role if reach in {"deployment", "project"} else Permission.CAN_VIEW
    if spec.name == ActionName.PIPELINE_REFRESH:
        return False  # standalone refresh needs a RELAXED project; the default project is STRICT
    if spec.name in PROJECT_MANAGE_ACTIONS:
        return project_level == Permission.CAN_MANAGE and required != ApiRole.ADMIN
    if spec.scope == ActionScope.PIPELINE:
        if spec.name == ActionName.LINEAGE_REFRESH:
            return False
        effective = (
            ApiRole.OPERATOR
            if role in {Permission.CAN_RUN, Permission.CAN_MANAGE}
            else ApiRole.VIEWER
        )
        # Upload is CAN_UPLOAD's own action: CAN_VIEW alone never admits it.
        if spec.name == ActionName.UPLOAD and role == Permission.CAN_VIEW:
            return False
        return tuple(ApiRole).index(effective) >= tuple(ApiRole).index(required)
    return required == ApiRole.VIEWER


@pytest.mark.parametrize("role", [*Permission, "custom"])
@pytest.mark.parametrize("reach", ["deployment", "project", "pipeline", "tag"])
def test_action_table_role_admission_through_cli_and_api(matrix, monkeypatch, role, reach):
    admin, caller, client, token = matrix
    requests = {}
    for name, spec in ACTIONS.items():
        request = build(spec.request)
        if name == ActionName.DEPLOY:
            request = replace(
                request,
                files={
                    "craft-connector.yml": base64.b64encode(
                        b"Secrets: {Source_type: ENVIRONMENT}\n"
                        b"Engine: {local: {Jdbc_url: 'jdbc:sqlite:/tmp/matrix.db', "
                        b"Auth_mode: NONE}}\n"
                        b"Orchestration: {Project: default}\n"
                    ).decode()
                },
            )
        names = {f.name for f in fields(request)}
        values = {}
        if "project" in names:
            values["project"] = "default"
        if "pipeline_code" in names:
            values["pipeline_code"] = "P"
        if name == ActionName.CONTROL_BULK:
            values["requests"] = tuple(
                replace(item, pipeline_code="P") for item in request.requests
            )
        requests[name] = replace(request, **values)
    scope = {"deployment": True} if reach == "deployment" else {"project": "default"}
    if reach in {"pipeline", "tag"}:
        scope[reach] = "P" if reach == "pipeline" else "team"
        # Built-in narrowed levels retain the separate project-admission requirement.
        act(
            admin,
            ActionName.ACCESS_GRANT,
            project="default",
            account="matrix",
            role="CAN_VIEW",
            reason="container",
        )
    if role == "custom" and reach == "project":
        act(
            admin,
            ActionName.ACCESS_GRANT,
            project="default",
            account="matrix",
            role="CAN_VIEW",
            reason="container",
        )
    baseline = {name: accepted(caller, name, request) for name, request in requests.items()}
    if role == "custom":
        held = ("run", "mark") if reach != "deployment" else ("run", "mark", "pool list")
        act(admin, ActionName.ROLE_CREATE, name="custom", actions=held)
    act(admin, ActionName.ACCESS_GRANT, account="matrix", role=role, reason="matrix", **scope)
    for name, spec in ACTIONS.items():
        request = requests[name]
        allowed = accepted(caller, name, request)
        if role != "custom":
            try:
                with selected_project(1):  # required_role read directly, below invoke
                    needed = spec.required_role(caller, request)
                expected = built_in_allows(spec, role, reach, needed)
            except PermissionDeniedError:
                expected = False
            assert allowed == expected, name
        if role == "custom":
            extra = name in held and (
                reach in {"project", "deployment"} or spec.scope == ActionScope.PIPELINE
            )
            assert allowed == (baseline[name] or extra), name
        if spec.path is None or name == ActionName.UPLOAD:
            # Host-only actions have no HTTP route; uploads use their real multipart suite.
            continue
        path = action_path(spec)
        given = {k: v for k, v in encode(request).items() if v is not None}
        if "{project}" in path:
            given["project"] = "default"
        path = path.format(**{key: given.pop(key) for key in re.findall(r"{([a-z_]+)}", path)})
        headers = {"Authorization": "Bearer " + token}
        if allowed:
            with pytest.raises(AdmittedError):
                if spec.method == HttpMethod.GET:
                    response = client.get(path, params=given, headers=headers)
                else:
                    response = client.post(path, json=given, headers=headers)
                pytest.fail(f"{name}: {response.status_code}: {response.text}")
        else:
            response = (
                client.get(path, params=given, headers=headers)
                if spec.method == HttpMethod.GET
                else client.post(path, json=given, headers=headers)
            )
            assert response.status_code in {403, 404}, (name, response.text)
        if allowed:
            with pytest.raises(AdmittedError):
                list(ApiClient("http://127.0.0.1:8000", "default").invoke(name, request))
        else:
            with pytest.raises((PermissionDeniedError, ResourceNotFoundError)):
                list(ApiClient("http://127.0.0.1:8000", "default").invoke(name, request))


def test_every_action_is_either_bindable_or_refused_by_its_action_table_policy(matrix):
    from etl_craft.services.operations.roles import role_actions

    _, caller, _, _ = matrix
    with caller.engine.connect() as conn:
        stored = {action for actions in role_actions(conn).values() for action in actions}
    for name, spec in ACTIONS.items():
        forbidden = (
            spec.role in {None, ApiRole.AGENT}
            or spec.placement == Placement.CONTROLLER_HOST
            or name.startswith(("account ", "token ", "group ", "role ", "project "))
            or name in {ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE}
        )
        if forbidden:
            with pytest.raises(UsageError, match="action"):
                bindable(name)
        else:
            assert bindable(name) == name
        if authorization.allows(caller, name, SimpleNamespace(pipeline_code="P")):
            assert str(name) in stored, name


def test_every_delegable_project_action_belongs_to_a_built_in_role(engine_db):
    """A new view- or run-level project action must be placed in a stored CAN_* role."""
    from etl_craft.services.operations.roles import role_actions

    with engine_db.engine.connect() as conn:
        stored = {
            action
            for role, actions in role_actions(conn).items()
            if role in {str(p) for p in Permission}
            for action in actions
        }
    missing = sorted(
        str(name)
        for name, spec in ACTIONS.items()
        if spec.scope != ActionScope.DEPLOYMENT
        and spec.role in {ApiRole.VIEWER, ApiRole.OPERATOR}
        and spec.placement == Placement.ANYWHERE
        and str(name) not in stored
    )
    assert missing == [], "add these actions to a built-in role in both schema.sql files"
