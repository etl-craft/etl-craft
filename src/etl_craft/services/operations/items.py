"""Exact-run item inspection and audited operator controls."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy.engine import Connection, Row

from etl_craft.core.actor import current_actor
from etl_craft.core.enums import (
    ActionName,
    Handler,
    InterventionAction,
    ItemAction,
    ItemStatus,
    RunStatus,
)
from etl_craft.core.errors import EtlCraftError, ResourceNotFoundError, RunRefusedError, UsageError
from etl_craft.core.governance import check_reason, reason_text
from etl_craft.core.items import ItemProgress, ItemRecord, progress, valid_item_key
from etl_craft.engine import controls, items
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.intervention_rows import InterventionDetails, record_intervention
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import RunId, require_text


@dataclass(frozen=True, kw_only=True)
class ItemInput(RunId):
    """A task's items are always selected by an explicit run identity."""

    pipeline_code: str
    task_code: str

    def __post_init__(self) -> None:
        """Refuse incomplete scope before any state can change."""
        super().__post_init__()
        require_text("pipeline_code", self.pipeline_code)
        require_text("task_code", self.task_code)


@dataclass(frozen=True, kw_only=True)
class ItemControl(ItemInput):
    """Control one named item, or the failed items, with a recorded reason."""

    action: ItemAction
    reason: str = ""
    item_key: str | None = None
    all_failed: bool = False
    status: ItemStatus | None = None
    rows: int = 0

    def __post_init__(self) -> None:
        """Keep selection exclusive and marks terminal."""
        super().__post_init__()
        try:
            object.__setattr__(self, "action", ItemAction(self.action))
            object.__setattr__(
                self, "status", None if self.status is None else ItemStatus(self.status)
            )
        except ValueError as error:
            raise UsageError(
                f"item action={self.action!r}, status={self.status!r}; expected an item action "
                "and terminal mark status; choose the documented action/status values"
            ) from error
        object.__setattr__(self, "reason", reason_text(self.reason))
        if self.all_failed == (self.item_key is not None):
            raise UsageError(
                "item selection: expected exactly one of item_key and all_failed; select "
                "the work to change"
            )
        if self.item_key is not None and not valid_item_key(self.item_key):
            raise UsageError(
                f"item_key={self.item_key!r}; expected UTF-8 text of 1-512 characters without NUL; "
                "choose a recorded stable item key"
            )
        if self.action == ItemAction.MARK and self.status not in {
            ItemStatus.SUCCESS,
            ItemStatus.FAILED,
            ItemStatus.SKIPPED,
        }:
            raise UsageError(
                f"item mark status={self.status}; expected SUCCESS, FAILED or "
                f"SKIPPED; choose a terminal mark"
            )
        if self.action != ItemAction.MARK and (self.status is not None or self.rows != 0):
            raise UsageError(
                f"item action={self.action}, status={self.status}, rows={self.rows}; "
                "expected status/rows only for MARK; remove those fields"
            )
        if type(self.rows) is not int or self.rows < 0:
            raise UsageError(f"item rows={self.rows}; expected a nonnegative count; correct rows")


@dataclass(frozen=True)
class ItemAvailability:
    """One item action and its shared policy decision."""

    action: ItemAction
    item_key: str | None
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class ItemView:
    """The same persisted item rows and counts behind every user-facing view."""

    SCHEMA: ClassVar[str] = "etl-craft/items/1"
    task_run_id: int
    records: tuple[ItemRecord, ...]
    progress: ItemProgress

    task_run_label: str = ""
    availability: tuple[ItemAvailability, ...] = ()


def inspect(ctx: OperationContext, request: ItemInput) -> ItemView:
    """Read items only from the explicitly selected pipeline run and task."""
    with ctx.engine.connect() as conn:
        task = conn.execute(statement(conn, "item_task"), vars(request)).one_or_none()
        if task is None:
            raise ResourceNotFoundError(
                f"{request.pipeline_code}.{request.task_code} run {request.run_id}: "
                f"task run missing; select a run where this task started"
            )
        records = items.latest(conn, task.task_run_id)
        return ItemView(
            task.task_run_id,
            records,
            progress(records),
            availability=availability(ctx, request, task, records),
        )


def control(ctx: OperationContext, request: ItemControl) -> ItemView:
    """Commit a mark or a truthful pending cancellation; reruns retain other successes."""
    check_reason(request.reason)
    with ctx.engine.begin() as conn:
        assert isinstance(request.run_id, int), "run reference must be resolved"
        controls.lock_run(conn, request.run_id)
        task = conn.execute(statement(conn, "item_task"), vars(request)).one_or_none()
        check_item_task(task, request)
        assert task is not None
        records = items.latest(conn, task.task_run_id)
        selected = select_items(records, request)
        for old in selected:
            change(conn, task, old, request)
    if request.action == ItemAction.RERUN:
        from etl_craft.services.operations.requests import RunRequest
        from etl_craft.services.operations.runs import execute_run

        execute_run(
            ctx,
            RunRequest(
                pipeline_code=request.pipeline_code,
                task_code=request.task_code,
                run_id=request.run_id,
                rerun=True,
                reason=request.reason,
            ),
        )
    return inspect(
        ctx,
        ItemInput(
            pipeline_code=request.pipeline_code, task_code=request.task_code, run_id=request.run_id
        ),
    )


def check_item_task(task: Row[tuple[object, ...]] | None, request: ItemControl) -> None:
    """Require admitted item work and an ended task before rerun."""
    if task is None or task.handler != Handler.PYTHON or task.attempt_id is None:
        raise RunRefusedError(
            f"{request.task_code} run {request.run_id}: no admitted Python "
            f"attempt; expected recorded items; run the Python task first"
        )
    if request.action == ItemAction.RERUN and task.status in {
        RunStatus.QUEUED,
        RunStatus.IN_PROGRESS,
    }:
        raise RunRefusedError(
            f"{request.task_code}: task status={task.status}; expected an ended "
            f"task before rerunning items; wait for the task to finish or cancel "
            f"it"
        )


def select_items(records: tuple[ItemRecord, ...], request: ItemControl) -> list[ItemRecord]:
    """Select the exact item or every failed item under the request."""
    selected = [
        r
        for r in records
        if (r.status == ItemStatus.FAILED if request.all_failed else r.key == request.item_key)
    ]
    if not selected:
        raise ResourceNotFoundError(
            f"{request.task_code}: item "
            f"selection={request.item_key or 'all failed'} found no items; "
            f"inspect the exact task run and choose a recorded key"
        )
    return selected


def availability(
    ctx: OperationContext,
    request: ItemInput,
    task: Row[tuple[object, ...]],
    records: tuple[ItemRecord, ...],
) -> tuple[ItemAvailability, ...]:
    """Use the mutating operation's admission and item checks on a read snapshot."""
    from etl_craft.services.operations.capabilities import action_availability

    authority = action_availability(ctx, ActionName.ITEM_CONTROL, request)
    return (
        inspect_item_action(task, records, request, ItemAction.RERUN, None, authority.reason),
        *(
            inspect_item_action(task, (row,), request, action, row.key, authority.reason)
            for row in records
            for action in ItemAction
        ),
    )


def inspect_item_action(
    task: Row[tuple[object, ...]],
    records: tuple[ItemRecord, ...],
    scope: ItemInput,
    action: ItemAction,
    key: str | None,
    refusal: str,
) -> ItemAvailability:
    """Return the same refusal as control without applying changes."""
    if refusal:
        return ItemAvailability(action, key, False, refusal)
    request = ItemControl(
        pipeline_code=scope.pipeline_code,
        task_code=scope.task_code,
        run_id=scope.run_id,
        action=action,
        item_key=key,
        all_failed=key is None,
        status=ItemStatus.SUCCESS if action == ItemAction.MARK else None,
    )
    try:
        check_item_task(task, request)
        for record in select_items(records, request):
            check_item_change(record, action)
    except EtlCraftError as error:
        return ItemAvailability(action, key, False, str(error))
    return ItemAvailability(action, key, True)


def check_item_change(old: ItemRecord, action: ItemAction) -> None:
    """Require a known ending for overrides other than live cancellation."""
    if old.started is not None and old.ended is None and old.status == ItemStatus.FAILED:
        raise RunRefusedError(
            f"item {old.key}: its task ended without an item ending; expected known completed "
            "work before an override; recover the task to establish this item's outcome"
        )
    live = old.status in {ItemStatus.RUNNING, ItemStatus.CANCEL_REQUESTED}
    if live and action != ItemAction.CANCEL:
        raise RunRefusedError(
            f"item {old.key}: status={old.status}; expected an ended item for "
            f"{action}; cancel and wait for acknowledgement first"
        )


def change(
    conn: Connection, task: Row[tuple[object, ...]], old: ItemRecord, request: ItemControl
) -> None:
    """Serialize the decision with item starts and endings under the same run lock."""
    check_item_change(old, request.action)
    live = old.status in {ItemStatus.RUNNING, ItemStatus.CANCEL_REQUESTED}
    if request.action == ItemAction.CANCEL:
        status = ItemStatus.CANCEL_REQUESTED if live else ItemStatus.CANCELLED
    elif request.action == ItemAction.RERUN:
        status = ItemStatus.QUEUED
    else:
        assert request.status is not None
        status = request.status
    ending = replace(
        old,
        status=status,
        row_count=request.rows if request.action == ItemAction.MARK else old.row_count,
        error=request.reason,
        report_id=str(uuid4()),
        ended=None if live else datetime.now(UTC).isoformat(),
    )
    items.append(conn, task.task_run_id, task.attempt_id, ending)
    record_intervention(
        conn,
        pipeline_id=task.pipeline_id,
        pipeline_run_id=task.run_id,
        task_id=task.task_id,
        action=InterventionAction(request.action),
        reason=request.reason,
        requested_by=current_actor().name,
        from_status=old.status,
        to_status=status,
        target_count=request.rows,
        details=InterventionDetails(item_key=old.key),
    )
