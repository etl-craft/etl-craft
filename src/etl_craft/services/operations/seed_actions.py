"""The deploy workflow's project-scoped seed action."""

from etl_craft.core.enums import ActionName, ActionScope, ApiRole, Audit, HttpMethod
from etl_craft.services.operations import seeds
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.requests import NoInput

SEED_ACTIONS = (
    Action(
        ActionName.SEED_APPLY,
        seeds.apply,
        NoInput,
        seeds.SeedLoads,
        ApiRole.DEVELOPER,
        HttpMethod.POST,
        "/api/v1/seeds",
        Audit.REQUEST,
        scope=ActionScope.PROJECT,
    ),
)
