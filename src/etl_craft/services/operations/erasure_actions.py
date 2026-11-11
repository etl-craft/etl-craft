"""Project erasure contracts use one admin operation for every interface."""

from etl_craft.core.enums import ActionName, ActionScope, ApiRole, Audit, HttpMethod
from etl_craft.core.erasure import ErasureReport
from etl_craft.services.operations import erasure
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.requests import NoInput

ERASURE_ACTIONS = (
    Action(
        ActionName.ERASE,
        erasure.erase,
        erasure.EraseInput,
        ErasureReport,
        ApiRole.ADMIN,
        HttpMethod.POST,
        "/api/v1/erasure",
        Audit.REQUEST,
        scope=ActionScope.PROJECT,
    ),
    Action(
        ActionName.ERASURE_LIST,
        erasure.entries,
        NoInput,
        erasure.ErasureList,
        ApiRole.ADMIN,
        HttpMethod.GET,
        "/api/v1/erasure",
        scope=ActionScope.PROJECT,
    ),
)
