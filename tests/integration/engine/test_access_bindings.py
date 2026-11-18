"""One access model: WHO gets a role or one command, WHERE (deployment, environment, project)."""

from dataclasses import replace

import pytest

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import admitted
from etl_craft.services.operations.requests import RunRequest
from fixtures.actions import act
from fixtures.metadata import add_pipeline

OWNER = Actor("owner", ActorKind.USER)


@pytest.fixture
def estate(engine_db):
    """Projects sales (DEV) and hr (PROD), each with two pipelines, and a viewer account ana."""
    admin = OperationContext(engine_db.engine, engine_db.config, OWNER, role=ApiRole.ADMIN)
    act(admin, ActionName.ACCOUNT_ADD, name="ana", role=ApiRole.VIEWER, oidc_subject="ana-sub")
    projects = {}
    for code, environment in (("sales", "DEV"), ("hr", "PROD")):
        act(
            admin,
            ActionName.PROJECT_ADD,
            project=code,
            environment_type=environment,
            reason="estate",
        )
        with admin.engine.connect() as conn:
            from sqlalchemy import text

            projects[code] = conn.execute(
                text("SELECT PROJECT_ID FROM CFG_PROJECTS WHERE PROJECT_CODE=:c"), {"c": code}
            ).scalar_one()
        with acting_as(OWNER), admin.engine.begin() as conn:
            for pipeline in ("P1", "P2"):
                add_pipeline(conn, pipeline, project_id=projects[code])
    act(admin, ActionName.ROLE_CREATE, name="runner", actions=("run",))
    ana = replace(admin, actor=Actor("ana", ActorKind.USER), role=ApiRole.VIEWER)
    return admin, ana, projects


def grant(admin, **values):
    return act(admin, ActionName.ACCESS_GRANT, reason="test", **values)


def may_run(ctx, project, project_id, pipeline):
    scoped = replace(ctx, project=project, project_id=project_id)
    try:
        with admitted(scoped, ActionName.RUN, RunRequest(pipeline_code=pipeline)):
            return True
    except (PermissionDeniedError, ResourceNotFoundError):
        return False


def explain(admin, **values):
    return act(admin, ActionName.ACCESS_EXPLAIN, account="ana", action="run", **values)


def test_one_account_holds_different_commands_in_different_projects(estate):
    admin, ana, projects = estate
    grant(admin, account="ana", role="runner", project="sales")
    grant(admin, account="ana", action="run", project="hr", pipeline="P2")
    assert may_run(ana, "sales", projects["sales"], "P1")
    assert may_run(ana, "sales", projects["sales"], "P2")
    assert not may_run(ana, "hr", projects["hr"], "P1")
    assert may_run(ana, "hr", projects["hr"], "P2")
    told = explain(admin, project="hr", pipeline="P2")
    assert told.allowed and "run to account:ana on pipeline P2" in told.allowed_by[0]
    refused = explain(admin, project="hr", pipeline="P1")
    assert not refused.allowed and refused.refusal and "runner" in refused.roles_with_action


def test_an_environment_binding_reaches_every_project_of_that_type(estate):
    admin, ana, projects = estate
    grant(admin, account="ana", role="runner", environment="PROD")
    assert may_run(ana, "hr", projects["hr"], "P1")
    assert not may_run(ana, "sales", projects["sales"], "P1")


def test_revoking_and_disabling_stop_on_the_next_request(estate):
    admin, ana, projects = estate
    grant(admin, account="ana", role="runner", project="sales")
    assert may_run(ana, "sales", projects["sales"], "P1")
    act(admin, ActionName.ROLE_DISABLE, name="runner")
    assert not may_run(ana, "sales", projects["sales"], "P1")
    grant(admin, account="ana", action="run", project="sales")
    assert may_run(ana, "sales", projects["sales"], "P1")
    act(admin, ActionName.ACCESS_REVOKE, account="ana", action="run", project="sales", reason="x")
    assert not may_run(ana, "sales", projects["sales"], "P1")


def test_groups_and_audiences_are_principals_too(estate):
    admin, ana, projects = estate
    act(admin, ActionName.GROUP_ADD, name="analysts")
    act(admin, ActionName.GROUP_ADD_MEMBER, name="analysts", account="ana")
    grant(admin, group="analysts", role="runner", project="sales")
    assert may_run(ana, "sales", projects["sales"], "P1")
    grant(admin, audience="viewer", action="run", project="hr")
    assert may_run(ana, "hr", projects["hr"], "P2")


def test_deployment_actions_bind_only_deployment_wide_and_admin_tasks_never(estate):
    admin, _, _ = estate
    act(admin, ActionName.ROLE_CREATE, name="pool-keeper", actions=("pool set",))
    with pytest.raises(UsageError, match="act on the whole deployment; bind it with --deployment"):
        grant(admin, account="ana", role="pool-keeper", project="sales")
    grant(admin, account="ana", role="pool-keeper", deployment=True)
    for action in ("account add", "access grant", "role create", "agent claim", "setup"):
        with pytest.raises(UsageError, match="action"):
            act(admin, ActionName.ROLE_ADD_ACTION, name="pool-keeper", action=action)
    with pytest.raises(UsageError, match="not a known etl-craft action"):
        act(admin, ActionName.ROLE_CREATE, name="typo", actions=("rnu",))
    with pytest.raises(UsageError, match="built-in roles cannot be changed"):
        act(admin, ActionName.ROLE_ADD_ACTION, name="CAN_VIEW", action="run")


def test_only_administrators_bind_beyond_one_project(estate):
    admin, ana, _ = estate
    with pytest.raises(PermissionDeniedError):
        act(ana, ActionName.ACCESS_GRANT, account="ana", role="runner", deployment=True, reason="x")
    with pytest.raises(UsageError, match="exactly one of --deployment, --environment or --project"):
        grant(admin, account="ana", role="runner", deployment=True, project="sales")


def test_built_in_levels_still_replace_and_custom_bindings_add(estate):
    admin, _, _ = estate
    grant(admin, account="ana", role="CAN_VIEW", project="sales")
    changed = grant(admin, account="ana", role="CAN_RUN", project="sales")
    assert changed.change.previous_role == "CAN_VIEW"
    grant(admin, account="ana", role="runner", project="sales")
    listed = act(admin, ActionName.ACCESS_LIST, project="sales", account="ana").bindings
    assert sorted(b.role for b in listed if b.active_flag == "Y") == ["CAN_RUN", "runner"]
    roles = act(admin, ActionName.ROLE_DESCRIBE, name="CAN_RUN").roles[0]
    assert roles.built_in and "run" in roles.actions and "config apply" not in roles.actions
    assert "config plan" not in roles.actions


def test_custom_authority_does_not_bypass_temporary_password_replacement(estate):
    from sqlalchemy import text

    admin, ana, projects = estate
    grant(admin, account="ana", action="run", project="sales")
    with acting_as(OWNER), admin.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_ACCOUNTS SET MUST_CHANGE_PASSWORD='Y' WHERE ACCOUNT_NAME='ana'")
        )
    scoped = replace(ana, project="sales", project_id=projects["sales"])
    with (
        pytest.raises(PermissionDeniedError, match="temporary password requires replacement"),
        admitted(scoped, ActionName.RUN, RunRequest(pipeline_code="P1")),
    ):
        pytest.fail("a custom binding bypassed the password boundary")
    explained = explain(admin, project="sales", pipeline="P1")
    assert not explained.allowed and "temporary password" in explained.refusal


def test_custom_pipeline_view_is_narrow_and_survives_another_principals_restriction(estate):
    admin, ana, projects = estate
    grant(admin, account="ana", action="run", project="sales", pipeline="P1")
    grant(admin, audience="developer", role="CAN_RUN", project="sales", pipeline="P1")
    scoped = replace(ana, project="sales", project_id=projects["sales"])
    assert {p.pipeline_code for p in act(scoped, ActionName.PIPELINES).pipelines} == {"P1"}
    act(admin, ActionName.ROLE_CREATE, name="narrow", actions=("run",))
    grant(admin, account="ana", role="narrow", project="hr", pipeline="P2")
    hr = replace(ana, project="hr", project_id=projects["hr"])
    assert {p.pipeline_code for p in act(hr, ActionName.PIPELINES).pipelines} == {"P2"}
    act(admin, ActionName.ROLE_DISABLE, name="narrow")
    with pytest.raises(ResourceNotFoundError):
        act(hr, ActionName.PIPELINES)


def test_deployment_custom_actions_do_not_imply_deployment_read_access(estate):
    admin, ana, projects = estate
    grant(admin, account="ana", action="run", deployment=True)
    assert may_run(ana, "sales", projects["sales"], "P1")
    assert may_run(ana, "hr", projects["hr"], "P2")
    with pytest.raises(ResourceNotFoundError):
        act(replace(ana, project="sales", project_id=projects["sales"]), ActionName.PIPELINES)
    act(admin, ActionName.ROLE_CREATE, name="pool-reader", actions=("pool list",))
    grant(admin, account="ana", role="pool-reader", deployment=True)
    assert act(ana, ActionName.POOL_LIST, reason="test").pools


def test_disabled_roles_cannot_receive_new_bindings(estate):
    admin, _, _ = estate
    grant(admin, account="ana", role="runner", project="sales")
    act(admin, ActionName.ROLE_DISABLE, name="runner")
    with pytest.raises(UsageError, match="not an active role"):
        grant(admin, account="ana", role="runner", project="hr")
    revoked = act(
        admin,
        ActionName.ACCESS_REVOKE,
        account="ana",
        role="runner",
        project="sales",
        reason="retire disabled role",
    )
    assert revoked.change.binding.active_flag == "N"


def test_adding_a_deployment_action_refuses_a_role_with_narrower_bindings(estate):
    admin, _, _ = estate
    grant(admin, account="ana", role="runner", project="sales")
    with pytest.raises(UsageError, match=r"runner.*pool list.*deployment-only.*revoke"):
        act(admin, ActionName.ROLE_ADD_ACTION, name="runner", action="pool list")
    assert act(admin, ActionName.ROLE_DESCRIBE, name="runner").roles[0].actions == ("run",)


def test_access_lists_refuse_ambiguous_or_unknown_scopes(estate):
    admin, _, _ = estate
    with pytest.raises(UsageError, match="exactly one"):
        act(admin, ActionName.ACCESS_LIST, project="sales", deployment=True)
    with pytest.raises(UsageError, match=r"environment 'PRDO'.*expected one of.*correct"):
        act(admin, ActionName.ACCESS_LIST, environment="PRDO")


def test_explain_handles_action_inputs_and_checks_delegation_rights(estate):
    admin, _, _ = estate
    grant(admin, account="ana", action="mark", project="sales", pipeline="P1")
    marked = act(
        admin,
        ActionName.ACCESS_EXPLAIN,
        account="ana",
        action="mark",
        project="sales",
        pipeline="P1",
    )
    assert marked.allowed and marked.allowed_by
    delegated = act(
        admin,
        ActionName.ACCESS_EXPLAIN,
        account="ana",
        action="access grant",
        project="sales",
        pipeline="P1",
    )
    assert not delegated.allowed and "CAN_MANAGE" in delegated.refusal


def test_single_action_bindings_store_the_canonical_command(estate):
    admin, ana, projects = estate
    given = grant(admin, account="ana", action=" run ", project="sales")
    assert given.change.binding.action == "run"
    assert may_run(ana, "sales", projects["sales"], "P1")
    act(
        admin,
        ActionName.ACCESS_REVOKE,
        account="ana",
        action=" run ",
        project="sales",
        reason="done",
    )
    assert not may_run(ana, "sales", projects["sales"], "P1")


def test_custom_batch_admission_requires_every_named_pipeline(estate):
    from etl_craft.core.enums import ControlAction
    from etl_craft.services.operations.requests import BulkControlRequest, ControlRequest

    admin, ana, projects = estate
    scoped = replace(ana, project="sales", project_id=projects["sales"])
    batch = BulkControlRequest(
        requests=tuple(
            ControlRequest(pipeline_code=code, action=ControlAction.PAUSE, reason="test")
            for code in ("P1", "P2")
        )
    )
    grant(admin, account="ana", action="control bulk", project="sales", pipeline="P1")
    # P2 is reached by no binding of ana's, so it is masked rather than refused.
    with pytest.raises(ResourceNotFoundError), admitted(scoped, ActionName.CONTROL_BULK, batch):
        pytest.fail("one binding admitted a batch naming an unbound pipeline")
    grant(admin, account="ana", action="control bulk", project="sales", pipeline="P2")
    with admitted(scoped, ActionName.CONTROL_BULK, batch):
        pass
