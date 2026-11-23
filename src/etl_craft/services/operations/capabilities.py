"""Expose the control policy and its data effects without executing a control."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from etl_craft.core.enums import (
    DEFINITION_CONTROLS,
    ActionName,
    ActionScope,
    AgentCommand,
    ControlAction,
    HttpMethod,
    PositionKind,
    RunStatus,
)
from etl_craft.core.errors import EtlCraftError, RunStateError
from etl_craft.engine import run_scopes, runlog
from etl_craft.engine.repository.pipelines import resolve_pipeline_id
from etl_craft.engine.repository.tasks import resolve_task_id
from etl_craft.engine.run_definitions import for_run
from etl_craft.execution.interventions import (
    open_pause,
    require_markable_task,
    require_pause_state,
    require_resettable_offset,
)
from etl_craft.services.operations import access, announcements, tokens
from etl_craft.services.operations.access_inputs import Resolved
from etl_craft.services.operations.accounts import AccountName, inspect_account_action
from etl_craft.services.operations.admin_metadata import PoolIdentity, require_unused_pool
from etl_craft.services.operations.agent_models import AgentControl
from etl_craft.services.operations.agents import require_live_agent
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.controls import check_control, control_scope
from etl_craft.services.operations.documents import DocsInput, require_warehouse_check
from etl_craft.services.operations.maintenance import RehashInput, require_cloning
from etl_craft.services.operations.personal import require_local_password
from etl_craft.services.operations.pipeline_refresh import RefreshInput
from etl_craft.services.operations.pipeline_resume import require_open_pause
from etl_craft.services.operations.previews import PreviewInput, preview_parts
from etl_craft.services.operations.recovery import control_effect
from etl_craft.services.operations.requests import (
    BulkControlRequest,
    CapabilitiesInput,
    ControlRequest,
    LineageRefreshInput,
    MarkRequest,
    NoInput,
    PipelineInput,
    ReconcileInput,
    Request,
    RunRequest,
)
from etl_craft.services.operations.retention import PurgeInput
from etl_craft.services.operations.roles import RoleName, custom_role_id
from etl_craft.services.operations.task_pauses import inspect_task_pause
from etl_craft.services.operations.uploads import UploadRequest, require_upload_pipeline
from etl_craft.services.operations.values import require_human_unlock


@dataclass(frozen=True)
class Capability:
    """One action and the concrete reason it is available or refused now."""

    action: ControlAction
    available: bool
    reason: str
    preserves_successful_work: bool
    retains_checkpoints: bool = True


@dataclass(frozen=True)
class CapabilitiesView:
    """A current snapshot; actions revalidate under the same locks before acceptance."""

    SCHEMA: ClassVar[str] = "etl-craft/capabilities/1"
    pipeline_code: str
    pipeline_run_id: int
    task_code: str | None
    actions: tuple[Capability, ...]

    run_label: str = ""


@dataclass(frozen=True)
class ActionAvailability:
    """The admission decision for an action in the requested scope."""

    action: ActionName
    endpoint: str
    method: HttpMethod
    available: bool
    reason: str
    control: ControlAction | None = None
    replacement: bool = False


@dataclass(frozen=True)
class ActionAvailabilityView:
    """Availability answers for controls on a project, pipeline or deployment."""

    SCHEMA: ClassVar[str] = "etl-craft/action-availability/1"
    actions: tuple[ActionAvailability, ...]


@dataclass(frozen=True, kw_only=True)
class DeploymentCapabilitiesInput(Request):
    """Optionally inspect actions on one account or agent."""

    account_name: str | None = None
    agent_id: int | None = None
    role_name: str | None = None
    pool_name: str | None = None
    token_id: int | None = None
    announcement_id: int | None = None


def action_availability(
    ctx: OperationContext, name: ActionName, request: object
) -> ActionAvailability:
    """Return the admission decision without recording an attempted change."""
    from etl_craft.services.operations.actions import ACTIONS, authorize_action

    action = ACTIONS[name]
    assert action.path is not None and action.method is not None
    control = (
        request.requests[0]
        if isinstance(request, BulkControlRequest)
        else request
        if isinstance(request, ControlRequest)
        else None
    )
    reason = ""
    try:
        authorize_action(ctx, action, request, action.required_role(ctx, request))
        inspect_action_state(ctx, name, request)
        if isinstance(request, BulkControlRequest):
            choices = tuple(
                action_availability(ctx, ActionName.CONTROL, control)
                for control in request.requests
            )
            if not any(choice.available for choice in choices):
                reason = choices[0].reason
    except EtlCraftError as error:
        reason = str(error)
    return ActionAvailability(
        name,
        action.path,
        action.method,
        not reason,
        reason,
        control.action if control else None,
        control.replace if control else False,
    )


def inspect_action_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Evaluate action-specific read-only preconditions after authorization."""
    from etl_craft.services.operations.actions import project_settings

    if isinstance(request, DocsInput):
        require_warehouse_check(ctx, request)
    if isinstance(request, PreviewInput):
        preview_parts(ctx, request)
    if name == ActionName.CLONE:
        require_cloning(project_settings(ctx, name, request))
    if name == ActionName.DATA_UNLOCK:
        require_human_unlock(ctx)
    if isinstance(request, access.AccessWrite):
        with ctx.engine.connect() as conn:
            project_id = None if request.reaches_beyond_project else ctx.project_id
            access.authorize(conn, ctx, Resolved(request, project_id, None, None))
    if isinstance(request, RunRequest):
        pause = open_pause(ctx.engine, request.pipeline_code, selector=request.selector)
        if pause is not None:
            raise RunStateError(
                f"pipeline {request.pipeline_code!r}: {pause.describe()}; "
                "resume it before starting a run"
            )
    if isinstance(request, ControlRequest) and request.action in DEFINITION_CONTROLS:
        inspect_definition_control(ctx, request)
    if isinstance(request, MarkRequest):
        inspect_mark(ctx, request)
    if isinstance(request, UploadRequest):
        require_upload_pipeline(ctx, request)
    inspect_deployment_state(ctx, name, request)


def inspect_mark(ctx: OperationContext, request: MarkRequest) -> None:
    """Share exact task and position admission with the requested mark."""
    assert request.task_code is not None
    task = f"{request.pipeline_code}.{request.task_code}"
    with ctx.engine.connect() as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        selected = runlog.select_run(conn, pipeline_id, request.selector)
        with for_run(conn, selected.pipeline_run_id):
            task_id = resolve_task_id(conn, pipeline_id, request.task_code)
            if request.status is not None:
                require_markable_task(conn, task, task_id, selected.pipeline_run_id)
            else:
                label = "watermark" if request.watermark is not None else "offset"
                require_resettable_offset(conn, task, task_id, label)


def inspect_deployment_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Check the permitted deployment action against its target object."""
    if name == ActionName.PASSWORD_CHANGE:
        require_local_password(ctx)
    if isinstance(request, AccountName):
        inspect_account_action(ctx, name, request)
    if isinstance(request, AgentControl):
        with ctx.engine.connect() as conn:
            require_live_agent(conn, request.agent_id)
    if name == ActionName.ROLE_DISABLE and isinstance(request, RoleName):
        with ctx.engine.connect() as conn:
            custom_role_id(conn, request.name)
    if name == ActionName.POOL_DISABLE and isinstance(request, PoolIdentity):
        with ctx.engine.connect() as conn:
            require_unused_pool(conn, request.name)
    if isinstance(request, tokens.TokenRevoke):
        tokens.require_revocable_token(ctx, request.token_id)
    if isinstance(request, announcements.AnnouncementEnd):
        announcements.require_open_announcement(ctx, request.announcement_id)


def inspect_definition_control(ctx: OperationContext, request: ControlRequest) -> None:
    """Apply the same standing pause state rules without taking a writer lock."""
    if request.task_code is not None:
        with ctx.engine.connect() as conn:
            pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
            inspect_task_pause(conn, pipeline_id, request, datetime.now(UTC))
        return
    active = open_pause(ctx.engine, request.pipeline_code)
    if request.action == ControlAction.RESUME:
        require_open_pause(request.pipeline_code, active)
    else:
        require_pause_state(request.pipeline_code, active, replace_pause=request.replace)


def deployment_capabilities(
    ctx: OperationContext, request: DeploymentCapabilitiesInput
) -> ActionAvailabilityView:
    """Inspect deployment action permissions without selecting a project."""
    from etl_craft.services.operations.actions import ACTIONS

    if request.account_name is not None:
        account = AccountName(name=request.account_name)
        return ActionAvailabilityView(
            tuple(
                action_availability(ctx, name, account)
                for name in (ActionName.ACCOUNT_DISABLE, ActionName.ACCOUNT_UNLOCK)
            )
        )
    if request.agent_id is not None:
        return ActionAvailabilityView(
            (
                action_availability(
                    ctx,
                    ActionName.AGENT_CONTROL,
                    AgentControl(agent_id=request.agent_id, command=AgentCommand.STOP),
                ),
            )
        )
    if request.role_name is not None:
        return ActionAvailabilityView(
            (action_availability(ctx, ActionName.ROLE_DISABLE, RoleName(name=request.role_name)),)
        )
    if request.pool_name is not None:
        return ActionAvailabilityView(
            (
                action_availability(
                    ctx, ActionName.POOL_DISABLE, PoolIdentity(name=request.pool_name, reason="")
                ),
            )
        )
    if request.token_id is not None:
        return ActionAvailabilityView(
            (
                action_availability(
                    ctx, ActionName.TOKEN_REVOKE, tokens.TokenRevoke(token_id=request.token_id)
                ),
            )
        )
    if request.announcement_id is not None:
        return ActionAvailabilityView(
            (
                action_availability(
                    ctx,
                    ActionName.ANNOUNCE_END,
                    announcements.AnnouncementEnd(
                        announcement_id=request.announcement_id, reason="Capability inspection"
                    ),
                ),
            )
        )
    return ActionAvailabilityView(
        tuple(
            action_availability(
                ctx,
                action.name,
                access.AccessWrite(deployment=True, reason="")
                if action.name in (ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE)
                else request,
            )
            for action in ACTIONS.values()
            if action.scope == ActionScope.DEPLOYMENT
            and action.method == HttpMethod.POST
            and action.escalate is None
        )
    )


def project_capabilities(
    ctx: OperationContext, request: CapabilitiesInput
) -> CapabilitiesView | ActionAvailabilityView:
    """Inspect a project or pipeline definition, or its selected run controls."""
    if not request.definition:
        return control_capabilities(ctx, request)
    pipeline = request.pipeline_code
    selected: dict[ActionName, object] = {
        ActionName.PIPELINE_REFRESH: RefreshInput(pipeline_code=pipeline),
        ActionName.LINEAGE_REFRESH: LineageRefreshInput(),
        ActionName.DOCS_VERSION: NoInput(),
        ActionName.GENERATE_DOCS: DocsInput(with_warehouse=request.with_warehouse),
        ActionName.RECONCILE: ReconcileInput(pipeline_code=pipeline),
        ActionName.PURGE: PurgeInput(),
        ActionName.REHASH: RehashInput(target=""),
        ActionName.REHASH_PLAN: RehashInput(target=""),
        ActionName.CLONE: NoInput(),
        ActionName.ERASE: NoInput(),
        ActionName.ACCESS_GRANT: access.AccessWrite(
            project=ctx.project, pipeline=pipeline, reason=""
        ),
        ActionName.ACCESS_REVOKE: access.AccessWrite(
            project=ctx.project, pipeline=pipeline, reason=""
        ),
    }
    if pipeline is not None:
        scope = PipelineInput(pipeline_code=pipeline)
        selected[ActionName.UPLOAD] = UploadRequest(pipeline_code=pipeline)
        selected[ActionName.DATA_PROVENANCE] = scope
        selected[ActionName.DATA_EDIT] = scope
        selected[ActionName.DATA_UNLOCK] = scope
        selected[ActionName.MARK] = (
            MarkRequest(
                pipeline_code=pipeline,
                task_code=request.task_code,
                run_id=request.run_id,
                status=RunStatus.SUCCESS if request.reset_position is None else None,
                watermark="0" if request.reset_position == PositionKind.WATERMARK else None,
                offset="0" if request.reset_position == PositionKind.OFFSET else None,
            )
            if request.run_id is not None and request.task_code is not None
            else scope
        )
        selected[ActionName.RUN] = RunRequest(pipeline_code=pipeline)
    if request.preview_table is not None:
        selected[ActionName.TABLE_PREVIEW] = PreviewInput(table=request.preview_table)
    controls = tuple(definition_actions(ctx, request))
    return ActionAvailabilityView(
        (
            *tuple(action_availability(ctx, name, target) for name, target in selected.items()),
            *controls,
        )
    )


def definition_actions(
    ctx: OperationContext, request: CapabilitiesInput
) -> Iterator[ActionAvailability]:
    """List the pause, resume and replace variants for the selected definitions."""
    pipeline = request.pipeline_code
    if pipeline is not None:
        for action, replace in (
            (ControlAction.PAUSE, False),
            (ControlAction.RESUME, False),
            (ControlAction.PAUSE, True),
        ):
            yield action_availability(
                ctx,
                ActionName.CONTROL,
                ControlRequest(
                    pipeline_code=pipeline,
                    task_code=request.task_code,
                    action=action,
                    replace=replace,
                    outcome=RunStatus.SKIPPED
                    if request.task_code and action == ControlAction.PAUSE
                    else None,
                ),
            )
    if request.pipeline_codes:
        for action in (ControlAction.PAUSE, ControlAction.RESUME):
            yield action_availability(
                ctx,
                ActionName.CONTROL_BULK,
                BulkControlRequest(
                    requests=tuple(
                        ControlRequest(pipeline_code=code, action=action)
                        for code in request.pipeline_codes
                    )
                ),
            )


def control_capabilities(ctx: OperationContext, request: CapabilitiesInput) -> CapabilitiesView:
    """Inspect exact-scope controls through the same policy used when accepting them."""
    pipeline_code, task_code = request.pipeline_code, request.task_code
    assert pipeline_code is not None
    with ctx.engine.connect() as conn:
        pipeline_id = resolve_pipeline_id(conn, pipeline_code)
        selected = runlog.select_run(conn, pipeline_id, request.selector)
        with for_run(conn, selected.pipeline_run_id):
            task_id = None if task_code is None else resolve_task_id(conn, pipeline_id, task_code)
            if task_id is not None:
                run_scopes.check_task(conn, selected.pipeline_run_id, task_id)
    actions = []
    for action in ControlAction:
        if action in DEFINITION_CONTROLS:
            continue
        control = ControlRequest(
            pipeline_code=pipeline_code,
            action=action,
            reason="capability inspection",
            run_id=selected.pipeline_run_id,
            task_code=task_code,
        )
        admission = action_availability(ctx, ActionName.CONTROL, control)
        reason = None if admission.available else admission.reason
        if reason is None:
            try:
                with control_scope(ctx, control), ctx.engine.connect() as conn:
                    current = runlog.select_run(conn, pipeline_id, control.selector)
                    check_control(conn, ctx, control, current, task_id)
            except EtlCraftError as error:
                reason = str(error)
        actions.append(
            Capability(
                action,
                reason is None,
                reason or control_effect(action),
                action != ControlAction.RESTART,
            )
        )
    return CapabilitiesView(pipeline_code, selected.pipeline_run_id, task_code, tuple(actions))
