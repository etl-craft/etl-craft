"""Expose the control policy and its data effects without executing a control."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import cached_property
from typing import ClassVar

from sqlalchemy.engine import Row

from etl_craft.core.enums import (
    DEFINITION_CONTROLS,
    ActionName,
    ActionScope,
    AgentCommand,
    ApiRole,
    ControlAction,
    HttpMethod,
    PositionKind,
    RunStatus,
)
from etl_craft.core.errors import EtlCraftError, RunStateError, UsageError
from etl_craft.engine import run_scopes, runlog
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.accounts import find_account
from etl_craft.engine.repository.pauses import Pause, fetch_open_pauses
from etl_craft.engine.repository.pipelines import resolve_pipeline_id
from etl_craft.engine.repository.tasks import resolve_task_id
from etl_craft.engine.run_definitions import for_run
from etl_craft.execution.interventions import (
    open_pause,
    require_markable_task,
    require_pause_state,
    require_resettable_offset,
)
from etl_craft.handlers.erasure import secret
from etl_craft.services.operations import access, announcements, erasure, groups, inspect, tokens
from etl_craft.services.operations.access_inputs import Resolved
from etl_craft.services.operations.accounts import AccountName, AccountRole, inspect_account_action
from etl_craft.services.operations.admin_metadata import (
    PoolIdentity,
    ProjectIdentity,
    require_existing_project,
    require_unused_pool,
)
from etl_craft.services.operations.agent_models import AgentControl
from etl_craft.services.operations.agents import require_live_agent
from etl_craft.services.operations.alert_channels import ChannelIdentity, require_channel
from etl_craft.services.operations.authorization import AdmissionSnapshot
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
    LogInput,
    MarkRequest,
    NoInput,
    PipelineInput,
    ReconcileInput,
    Request,
    RunRequest,
    RunSelection,
    TaskSelection,
    ValidateInput,
)
from etl_craft.services.operations.retention import PurgeInput
from etl_craft.services.operations.roles import (
    RoleAction,
    RoleName,
    bindable,
    custom_role_id,
    require_role_action,
)
from etl_craft.services.operations.task_pauses import inspect_task_pause
from etl_craft.services.operations.uploads import (
    UploadRequest,
    check_upload_pipeline,
    require_upload_pipeline,
    upload_principal,
)
from etl_craft.services.operations.values import require_human_unlock, value_task
from etl_craft.services.rehash import rehash_columns

ROLE_MUTATIONS = (
    ActionName.ROLE_DISABLE,
    ActionName.ROLE_ADD_ACTION,
    ActionName.ROLE_REMOVE_ACTION,
)


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
    pipelines: dict[str, tuple[ActionAvailability, ...]] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class DeploymentCapabilitiesInput(Request):
    """Optionally inspect an exact deployment object or a form's selected target."""

    account_name: str | None = None
    account_role: ApiRole | None = None
    agent_id: int | None = None
    role_name: str | None = None
    role_action: str | None = None
    pool_name: str | None = None
    token_id: int | None = None
    announcement_id: int | None = None
    group_name: str | None = None
    member_name: str | None = None
    project_code: str | None = None
    channel_name: str | None = None

    def __post_init__(self) -> None:
        """Keep each optional form value tied to its explicit target identity."""
        for value, parent in (
            ("account_role", "account_name"),
            ("role_action", "role_name"),
            ("member_name", "group_name"),
            ("channel_name", "project_code"),
        ):
            if getattr(self, value) is not None and getattr(self, parent) is None:
                raise UsageError(f"{value} requires {parent}; supply the selected target identity")


class DefinitionSnapshot(AdmissionSnapshot):
    """Read shared admission, pause and upload state once for a definition response."""

    @cached_property
    def pauses(self) -> dict[str, Pause]:
        """Read current standing pipeline pauses."""
        return fetch_open_pauses(self.conn)

    @cached_property
    def upload_flags(self) -> dict[str, tuple[int, str, str]]:
        """Read the stewardship flags for every active definition."""
        return {
            row.pipeline_code: (row.pipeline_id, row.stewardable_flag, row.active_flag)
            for row in self.conn.execute(statement(self.conn, "active_pipelines"))
        }

    @cached_property
    def upload_account(self) -> Row[tuple[object, ...]] | None:
        """Use one stored account row to check every upload capability."""
        return find_account(self.conn, self.ctx.actor.name)

    def check_upload(self, code: str) -> None:
        """Evaluate the same upload preconditions as the receipt action."""
        ctx = upload_principal(self.ctx, self.upload_account, code)
        scope = self if ctx == self.ctx else self.upload_scope(ctx)
        check_upload_pipeline(scope, code, flags=self.upload_flags[code])

    @cached_property
    def upload_snapshot(self) -> dict[ApiRole | None, AdmissionSnapshot]:
        """Reuse admission facts even when the stored role has changed."""
        return {}

    def upload_scope(self, ctx: OperationContext) -> AdmissionSnapshot:
        """Get the snapshot scoped to the effective upload role."""
        return self.upload_snapshot.setdefault(ctx.role, AdmissionSnapshot(self.conn, ctx))


def action_availability(
    ctx: OperationContext,
    name: ActionName,
    request: object,
    *,
    snapshot: DefinitionSnapshot | None = None,
    bulk_admission_only: bool = False,
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
        authorize_action(
            ctx, action, request, action.required_role(ctx, request), snapshot=snapshot
        )
        inspect_action_state(ctx, name, request, snapshot=snapshot)
        if isinstance(request, BulkControlRequest) and not bulk_admission_only:
            choices = tuple(
                action_availability(ctx, ActionName.CONTROL, control, snapshot=snapshot)
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


def inspect_action_state(
    ctx: OperationContext,
    name: ActionName,
    request: object,
    *,
    snapshot: DefinitionSnapshot | None = None,
) -> None:
    """Evaluate action-specific read-only preconditions after authorization."""
    if isinstance(request, DocsInput):
        require_warehouse_check(ctx, request)
    if isinstance(request, PreviewInput):
        preview_parts(ctx, request)
    inspect_maintenance_state(ctx, name, request)
    inspect_value_state(ctx, name, request)
    if isinstance(request, access.AccessWrite):
        project_id = None if request.reaches_beyond_project else ctx.project_id
        resolved = Resolved(request, project_id, None, None)
        if snapshot is None:
            with ctx.engine.connect() as conn:
                access.authorize(conn, ctx, resolved)
        else:
            access.authorize(snapshot.conn, ctx, resolved, snapshot=snapshot)
    if isinstance(request, RunRequest):
        pause = (
            open_pause(ctx.engine, request.pipeline_code, selector=request.selector)
            if snapshot is None
            else snapshot.pauses.get(request.pipeline_code)
        )
        if pause is not None:
            raise RunStateError(
                f"pipeline {request.pipeline_code!r}: {pause.describe()}; "
                "resume it before starting a run"
            )
    if isinstance(request, ControlRequest) and request.action in DEFINITION_CONTROLS:
        inspect_definition_control(ctx, request, None if snapshot is None else snapshot.pauses)
    if isinstance(request, MarkRequest):
        inspect_mark(ctx, request)
    if isinstance(request, UploadRequest):
        if snapshot is None:
            require_upload_pipeline(ctx, request)
        else:
            snapshot.check_upload(request.pipeline_code)
    inspect_log_state(ctx, name, request)
    inspect_deployment_state(ctx, name, request)


def inspect_maintenance_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Inspect configured maintenance targets without taking their writer locks."""
    from etl_craft.services.operations.actions import project_settings

    if name == ActionName.CLONE:
        require_cloning(project_settings(ctx, name, request))
    if name == ActionName.ERASE:
        secret(erasure.deployment(ctx).config)
    if isinstance(request, RehashInput) and request.target:
        selected = project_settings(ctx, name, request)
        rehash_columns(ctx.engine, selected.config, request.target)


def inspect_value_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Preserve identity-before-definition admission for value actions."""
    from etl_craft.services.operations.actions import project_settings

    if name == ActionName.DATA_UNLOCK:
        require_human_unlock(ctx)
    if isinstance(request, TaskSelection) and name in (
        ActionName.DATA_EDIT,
        ActionName.DATA_UNLOCK,
        ActionName.DATA_PROVENANCE,
    ):
        value_task(project_settings(ctx, name, request), request.pipeline_code, request.task_code)


def inspect_log_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Inspect the exact read source before offering a log action."""
    if isinstance(request, LogInput):
        source = inspect.attempt_log(ctx, request)
        close = getattr(source, "close", None)
        if close is not None:
            close()
    if isinstance(request, RunSelection) and name in (ActionName.RUN_LOG, ActionName.RUN_ZIP):
        with ctx.engine.connect() as conn:
            pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
            runlog.select_run(conn, pipeline_id, request.selector)


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
    if isinstance(request, groups.GroupMember):
        with ctx.engine.connect() as conn:
            groups.require_membership_identities(conn, request, name == ActionName.GROUP_ADD_MEMBER)
    elif isinstance(request, groups.GroupName):
        with ctx.engine.connect() as conn:
            groups.require_group(conn, request.name)
    if name == ActionName.PROJECT_DISABLE and isinstance(request, ProjectIdentity):
        with ctx.engine.connect() as conn:
            require_existing_project(conn, request.project)
    if name == ActionName.ALERT_CHANNEL_DISABLE and isinstance(request, ChannelIdentity):
        with ctx.engine.connect() as conn:
            require_channel(conn, request)
    if isinstance(request, AgentControl):
        with ctx.engine.connect() as conn:
            require_live_agent(conn, request.agent_id)
    inspect_role_state(ctx, name, request)
    if name == ActionName.POOL_DISABLE and isinstance(request, PoolIdentity):
        with ctx.engine.connect() as conn:
            require_unused_pool(conn, request.name)
    if isinstance(request, tokens.TokenRevoke):
        tokens.require_revocable_token(ctx, request.token_id)
    if isinstance(request, announcements.AnnouncementEnd):
        announcements.require_open_announcement(ctx, request.announcement_id)


def inspect_role_state(ctx: OperationContext, name: ActionName, request: object) -> None:
    """Inspect mutable role commands in the same validation order as execution."""
    if isinstance(request, RoleName) and name in ROLE_MUTATIONS:
        if name == ActionName.ROLE_ADD_ACTION and isinstance(request, RoleAction):
            bindable(request.action)
        with ctx.engine.connect() as conn:
            custom_role_id(conn, request.name)
            if isinstance(request, RoleAction):
                require_role_action(conn, request, adding=name == ActionName.ROLE_ADD_ACTION)


def inspect_definition_control(
    ctx: OperationContext,
    request: ControlRequest,
    pauses: dict[str, Pause] | None,
) -> None:
    """Apply the same standing pause state rules without taking a writer lock."""
    if request.task_code is not None:
        with ctx.engine.connect() as conn:
            pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
            inspect_task_pause(conn, pipeline_id, request, datetime.now(UTC))
        return
    active = (
        open_pause(ctx.engine, request.pipeline_code)
        if pauses is None
        else pauses.get(request.pipeline_code)
    )
    if request.action == ControlAction.RESUME:
        require_open_pause(request.pipeline_code, active)
    else:
        require_pause_state(request.pipeline_code, active, replace_pause=request.replace)


def deployment_capabilities(
    ctx: OperationContext, request: DeploymentCapabilitiesInput
) -> ActionAvailabilityView:
    """Inspect deployment action permissions without selecting a project."""
    from etl_craft.services.operations.actions import ACTIONS

    if any(
        value is not None
        for value in (request.account_name, request.group_name, request.project_code)
    ):
        return metadata_capabilities(ctx, request)
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
            tuple(
                action_availability(
                    ctx,
                    name,
                    RoleAction(name=request.role_name, action=request.role_action)
                    if name != ActionName.ROLE_DISABLE and request.role_action is not None
                    else RoleName(name=request.role_name),
                )
                for name in ROLE_MUTATIONS
            )
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
            and action.method is not None
            and action.escalate is None
        )
    )


def metadata_capabilities(
    ctx: OperationContext, request: DeploymentCapabilitiesInput
) -> ActionAvailabilityView:
    """Inspect group membership and project identities without writing them."""
    if request.account_name is not None:
        account = AccountName(name=request.account_name)
        return ActionAvailabilityView(
            tuple(
                action_availability(
                    ctx,
                    name,
                    AccountRole(name=request.account_name, role=request.account_role)
                    if name == ActionName.ACCOUNT_SET_ROLE and request.account_role is not None
                    else account,
                )
                for name in (
                    ActionName.ACCOUNT_DISABLE,
                    ActionName.ACCOUNT_UNLOCK,
                    ActionName.ACCOUNT_RESET_PASSWORD,
                    ActionName.ACCOUNT_SET_ROLE,
                )
            )
        )
    if request.group_name is not None:
        target = (
            groups.GroupMember(name=request.group_name, account=request.member_name)
            if request.member_name is not None
            else groups.GroupName(name=request.group_name)
        )
        names = (
            (ActionName.GROUP_ADD_MEMBER, ActionName.GROUP_REMOVE_MEMBER)
            if request.member_name is not None
            else (ActionName.GROUP_DISABLE,)
        )
        return ActionAvailabilityView(
            tuple(action_availability(ctx, name, target) for name in names)
        )
    assert request.project_code is not None
    if request.channel_name is not None:
        return ActionAvailabilityView(
            (
                action_availability(
                    ctx,
                    ActionName.ALERT_CHANNEL_DISABLE,
                    ChannelIdentity(project=request.project_code, name=request.channel_name),
                ),
            )
        )
    return ActionAvailabilityView(
        (
            action_availability(
                ctx,
                ActionName.PROJECT_DISABLE,
                ProjectIdentity(project=request.project_code, reason=""),
            ),
        )
    )


def project_capabilities(
    ctx: OperationContext, request: CapabilitiesInput
) -> CapabilitiesView | ActionAvailabilityView:
    """Inspect a project or pipeline definition, or its selected run controls."""
    if not request.definition:
        return control_capabilities(ctx, request)
    with read_snapshot(ctx.engine) as conn:
        snapshot = DefinitionSnapshot(conn, ctx)
        access = snapshot.pipelines
        if request.pipeline_code is not None:
            access.require(ctx, request.pipeline_code, ApiRole.VIEWER)
        visible = tuple(code for code in request.pipeline_codes if access.permits(code))
        return _definition_capabilities(ctx, request, snapshot, visible)


def _definition_capabilities(
    ctx: OperationContext,
    request: CapabilitiesInput,
    snapshot: DefinitionSnapshot,
    visible: tuple[str, ...],
) -> ActionAvailabilityView:
    pipeline = request.pipeline_code
    selected: dict[ActionName, object] = {
        ActionName.VALIDATE: ValidateInput(),
        ActionName.PIPELINE_REFRESH: RefreshInput(pipeline_code=pipeline),
        ActionName.LINEAGE_REFRESH: LineageRefreshInput(),
        ActionName.DOCS_VERSION: NoInput(),
        ActionName.GENERATE_DOCS: DocsInput(with_warehouse=request.with_warehouse),
        ActionName.RECONCILE: ReconcileInput(pipeline_code=pipeline),
        ActionName.PURGE: PurgeInput(),
        ActionName.REHASH: RehashInput(target=request.rehash_target or ""),
        ActionName.REHASH_PLAN: RehashInput(target=request.rehash_target or ""),
        ActionName.CLONE: NoInput(),
        ActionName.ERASE: NoInput(),
        ActionName.ACCESS_GRANT: access.AccessWrite(
            project=ctx.project, pipeline=pipeline, tag=request.binding_tag, reason=""
        ),
        ActionName.ACCESS_REVOKE: access.AccessWrite(
            project=ctx.project, pipeline=pipeline, tag=request.binding_tag, reason=""
        ),
    }
    if pipeline is not None:
        selected.update(pipeline_requests(request))
    if pipeline is not None and request.run_id is not None:
        selected[ActionName.RUN_LOG] = RunSelection(pipeline_code=pipeline, run_id=request.run_id)
        selected[ActionName.RUN_ZIP] = selected[ActionName.RUN_LOG]
    if request.attempt_id is not None:
        selected[ActionName.LOGS] = LogInput(attempt_id=request.attempt_id)
    if request.preview_table is not None:
        selected[ActionName.TABLE_PREVIEW] = PreviewInput(table=request.preview_table)
    common = {
        name: action_availability(ctx, name, target, snapshot=snapshot)
        for name, target in selected.items()
    }
    controls = tuple(
        definition_actions(
            ctx,
            replace(request, pipeline_codes=visible) if request.pipeline_codes else request,
            snapshot,
        )
    )
    return ActionAvailabilityView(
        (*common.values(), *controls),
        {code: _pipeline_availability(ctx, request, snapshot, common, code) for code in visible},
    )


def _pipeline_availability(
    ctx: OperationContext,
    request: CapabilitiesInput,
    snapshot: DefinitionSnapshot,
    common: dict[ActionName, ActionAvailability],
    code: str,
) -> tuple[ActionAvailability, ...]:
    target = replace(request, pipeline_code=code, pipeline_codes=())
    scoped = {
        **pipeline_requests(target),
        ActionName.RECONCILE: ReconcileInput(pipeline_code=code),
        ActionName.ACCESS_GRANT: access.AccessWrite(project=ctx.project, pipeline=code, reason=""),
        ActionName.ACCESS_REVOKE: access.AccessWrite(project=ctx.project, pipeline=code, reason=""),
    }
    answers = common | {
        name: action_availability(ctx, name, value, snapshot=snapshot)
        for name, value in scoped.items()
    }
    return (
        *answers.values(),
        *definition_actions(ctx, target, snapshot),
        *_bulk_definition_actions(ctx, (code,), snapshot, admission_only=True),
    )


def pipeline_requests(request: CapabilitiesInput) -> dict[ActionName, object]:
    """Build the exact pipeline and task requests whose admission the page renders."""
    pipeline = request.pipeline_code
    assert pipeline is not None
    scope = PipelineInput(pipeline_code=pipeline)
    selected: dict[ActionName, object] = {}
    selected[ActionName.UPLOAD] = UploadRequest(pipeline_code=pipeline)
    value_scope = (
        TaskSelection(pipeline_code=pipeline, task_code=request.task_code)
        if request.task_code is not None
        else scope
    )
    selected[ActionName.DATA_PROVENANCE] = value_scope
    selected[ActionName.DATA_EDIT] = value_scope
    selected[ActionName.DATA_UNLOCK] = value_scope
    selected[ActionName.MARK] = (
        MarkRequest(
            pipeline_code=pipeline,
            task_code=request.task_code,
            run_id=request.run_id,
            status=RunStatus.SUCCESS if request.reset_position is None else None,
            watermark="0" if request.reset_position == PositionKind.WATERMARK else None,
            offset="0" if request.reset_position == PositionKind.OFFSET else None,
        )
        if request.task_code is not None
        else scope
    )
    selected[ActionName.RUN] = RunRequest(pipeline_code=pipeline)
    return selected


def definition_actions(
    ctx: OperationContext,
    request: CapabilitiesInput,
    snapshot: DefinitionSnapshot,
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
                snapshot=snapshot,
            )
    if 1 <= len(request.pipeline_codes) <= BulkControlRequest.MAX_REQUESTS:
        yield from _bulk_definition_actions(ctx, request.pipeline_codes, snapshot)


def _bulk_definition_actions(
    ctx: OperationContext,
    codes: tuple[str, ...],
    snapshot: DefinitionSnapshot,
    *,
    admission_only: bool = False,
) -> Iterator[ActionAvailability]:
    for action in (ControlAction.PAUSE, ControlAction.RESUME):
        yield action_availability(
            ctx,
            ActionName.CONTROL_BULK,
            BulkControlRequest(
                requests=tuple(ControlRequest(pipeline_code=code, action=action) for code in codes)
            ),
            snapshot=snapshot,
            bulk_admission_only=admission_only,
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
