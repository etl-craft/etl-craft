"""Role administration and access explanation share one operation per action."""

from etl_craft.core.enums import ActionName, ActionScope, ApiRole, Audit, HttpMethod
from etl_craft.services.operations import bindings, roles
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.requests import NoInput

API = "/api/v1"

ROLE_ACTIONS = (
    Action(
        ActionName.ROLE_LIST,
        roles.list_roles,
        NoInput,
        roles.Roles,
        ApiRole.VIEWER,
        HttpMethod.GET,
        f"{API}/roles",
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ROLE_DESCRIBE,
        roles.describe_role,
        roles.RoleName,
        roles.Roles,
        ApiRole.VIEWER,
        HttpMethod.GET,
        f"{API}/roles/describe",
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ROLE_CREATE,
        roles.create_role,
        roles.RoleCreate,
        roles.Roles,
        ApiRole.ADMIN,
        HttpMethod.POST,
        f"{API}/roles",
        Audit.REQUEST,
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ROLE_ADD_ACTION,
        roles.add_action,
        roles.RoleAction,
        roles.Roles,
        ApiRole.ADMIN,
        HttpMethod.POST,
        f"{API}/roles/actions",
        Audit.REQUEST,
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ROLE_REMOVE_ACTION,
        roles.remove_action,
        roles.RoleAction,
        roles.Roles,
        ApiRole.ADMIN,
        HttpMethod.POST,
        f"{API}/roles/actions/remove",
        Audit.REQUEST,
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ROLE_DISABLE,
        roles.disable_role,
        roles.RoleName,
        roles.Roles,
        ApiRole.ADMIN,
        HttpMethod.POST,
        f"{API}/roles/disable",
        Audit.REQUEST,
        scope=ActionScope.DEPLOYMENT,
    ),
    Action(
        ActionName.ACCESS_EXPLAIN,
        bindings.explain,
        bindings.ExplainInput,
        bindings.Explanation,
        ApiRole.ADMIN,
        HttpMethod.GET,
        f"{API}/access/explain",
        scope=ActionScope.DEPLOYMENT,
    ),
)
