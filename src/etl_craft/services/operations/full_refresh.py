"""Plan a one-time full refresh: what it re-reads, and which append targets need confirming."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from uuid import uuid4

from sqlalchemy.engine import Connection

from etl_craft.core.enums import Handler, RunStatus, ScriptKind, SqlAction
from etl_craft.core.errors import (
    ConfirmationRequiredError,
    RunStateError,
    SqlGuardError,
    UsageError,
)
from etl_craft.core.full_refresh import FullRefresh
from etl_craft.core.graph import build_graph
from etl_craft.core.script_kinds import script_kind
from etl_craft.engine import runlog, standing_pauses
from etl_craft.engine.repository.dependencies import fetch_pipeline_graph
from etl_craft.engine.repository.pipelines import resolve_pipeline_id
from etl_craft.engine.repository.tasks import (
    TaskExecutionDetail,
    fetch_task_execution_detail,
    fetch_task_parameters,
    resolve_task_id,
)
from etl_craft.engine.run_creation import RunCreation, create
from etl_craft.handlers.sql.spec import parse_flag, read_action
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import RunRequest
from etl_craft.services.operations.run_parameters import base_definition


@dataclass(frozen=True)
class _Task:
    """What a full refresh needs to know about one task."""

    code: str
    handler: str
    params: Mapping[str, str]
    action: SqlAction | None = None

    @property
    def target(self) -> str:
        """The written ``TARGET_OBJECT``, which is also what an operator confirms."""
        return (self.params.get("TARGET_OBJECT") or "").strip()

    @property
    def refreshable(self) -> bool:
        """Whether it keeps a position, or reads only the latest run, that a refresh resets."""
        if self.handler == Handler.SQL:
            return "WATERMARK_COLUMN" in self.params or parse_flag(
                self.params, "PIPELINE_RUN_ID_FILTER"
            )
        if self.handler == Handler.PYTHON:
            return script_kind(self.params, self.code) == ScriptKind.INGESTION
        return False

    @property
    def appends(self) -> bool:
        """Whether the task appends, so reading everything again would write every row twice."""
        return self.action == SqlAction.APPEND_TABLE


def plan(ctx: OperationContext, request: RunRequest) -> FullRefresh:
    """Resolve a full refresh request, refusing what cannot work or lacks confirmation.

    The refresh covers every task of the pipeline, or ``task_code`` (and, with
    ``with_downstream``, everything that reads it). The run is always a whole pipeline run: tasks
    outside the scope run as usual. Raises ``ConfirmationRequiredError`` listing the append
    targets the operator must confirm emptying, until ``empty_targets`` names exactly those.
    """
    with ctx.engine.connect() as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        with base_definition(conn, pipeline_id):
            scope = _scope(conn, pipeline_id, request)
            everyone = _tasks(conn, _active_ids(conn, pipeline_id))
    refreshable = [task for task in scope if task.refreshable]
    if not refreshable:
        raise UsageError(
            f"{request.pipeline_code}: a full refresh of {_names(scope)} has nothing to refresh; "
            "expected a SQL task with WATERMARK_COLUMN or PIPELINE_RUN_ID_FILTER, or a Python "
            "INGESTION task; choose a task that reads incrementally"
        )
    appends = [task for task in refreshable if task.appends]
    _refuse_shared_targets(request, appends, everyone)
    needed = tuple(sorted({task.target for task in appends}))
    _require_confirmation(request, appends, needed)
    covered = None if request.task_code is None else tuple(sorted(t.code for t in scope))
    return FullRefresh(covered, needed)


def admit(ctx: OperationContext, request: RunRequest) -> RunRequest:
    """Record the run a full refresh is, and return the request that executes exactly that run.

    The run is created before it executes, like a run with recorded inputs, so a controller or an
    agent that picks it up later reads the same plan. It refuses while another run of the pipeline
    is active or queued: a full refresh starts its own run and never joins another.
    """
    refresh = plan(ctx, request)
    with ctx.engine.begin() as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        standing_pauses.lock(conn, pipeline_id)  # so two requests cannot both find it idle
        busy = [
            run
            for run in runlog.run_candidates(conn, pipeline_id)
            if run.task_selection is None
            and run.status in {RunStatus.QUEUED, RunStatus.IN_PROGRESS}
        ]
        if busy:
            raise RunStateError(
                f"{request.pipeline_code}: pipeline_run_id={busy[0].pipeline_run_id} is "
                f"{busy[0].status}, and a full refresh starts its own run instead of joining "
                "it; finish, cancel or recover that run first, then repeat "
                "`etl-craft run --full-refresh`"
            )
        run_id = create(
            conn,
            pipeline_id,
            ctx.actor,
            RunCreation(
                run_date=request.run_date or runlog.today(ctx.config.timezone),
                run_key=f"full-refresh:{uuid4()}",
                status=RunStatus.QUEUED,
                full_refresh=refresh,
            ),
        )
    return replace(
        request,
        task_code=None,
        with_downstream=False,
        full_refresh=False,
        empty_targets=(),
        run_id=run_id,
    )


def _active_ids(conn: Connection, pipeline_id: int) -> tuple[int, ...]:
    data = fetch_pipeline_graph(conn, pipeline_id)
    return tuple(sorted(task.task_id for task in data.tasks))


def _tasks(conn: Connection, ids: tuple[int, ...]) -> list[_Task]:
    found = []
    for task_id in ids:
        detail = fetch_task_execution_detail(conn, task_id)
        params = fetch_task_parameters(conn, task_id)
        found.append(_Task(detail.task_code, detail.handler, params, _action(detail, params)))
    return found


def _action(detail: TaskExecutionDetail, params: Mapping[str, str]) -> SqlAction | None:
    """Read a SQL task's action, naming the task when its metadata cannot say."""
    if detail.handler != Handler.SQL:
        return None
    try:
        return read_action(params)
    except SqlGuardError as error:
        raise SqlGuardError(
            f"{detail.pipeline_code}.{detail.task_code}: {error}; correct the task, then repeat "
            "the full refresh"
        ) from error


def _scope(conn: Connection, pipeline_id: int, request: RunRequest) -> list[_Task]:
    """Return the tasks the refresh re-reads: all, or one and optionally what reads it."""
    if request.task_code is None:
        return _tasks(conn, _active_ids(conn, pipeline_id))
    task_id = resolve_task_id(conn, pipeline_id, request.task_code)
    ids = {task_id}
    if request.with_downstream:
        data = fetch_pipeline_graph(conn, pipeline_id)
        ids |= build_graph(data.tasks, data.same_pipeline_edges).downstream_of(task_id)
    return _tasks(conn, tuple(sorted(ids)))


def _refuse_shared_targets(
    request: RunRequest, appends: list[_Task], everyone: list[_Task]
) -> None:
    """Refuse emptying a table that another task of the pipeline also writes."""
    for task in appends:
        others = sorted(
            other.code
            for other in everyone
            if other.code != task.code and other.target == task.target
        )
        if others:
            raise UsageError(
                f"{request.pipeline_code}.{task.code}: target {task.target!r} is also written by "
                f"{', '.join(others)}; a full refresh would empty their rows too. Give each "
                "appended target one writer, or empty and reload it deliberately"
            )


def _require_confirmation(
    request: RunRequest, appends: list[_Task], needed: tuple[str, ...]
) -> None:
    """Demand the operator's confirmation that exactly these targets may be emptied."""
    if not needed:
        return
    if tuple(sorted(request.empty_targets)) == needed:
        return
    lines = "\n".join(
        f"  {task.code}: {task.target}" for task in sorted(appends, key=lambda t: t.code)
    )
    raise ConfirmationRequiredError(
        f"{request.pipeline_code}: a full refresh reads every source row again, and these "
        f"APPEND_TABLE tasks would write them a second time, so the engine empties their targets "
        f"(DELETE of all rows) just before each load. etl-craft cannot restore them:\n{lines}\n"
        "Confirm to continue: repeat the request with empty_targets naming exactly these targets "
        "(--yes unattended, or answer the prompt)",
        needed,
    )


def _names(tasks: list[_Task]) -> str:
    return ", ".join(task.code for task in tasks) or "no tasks"
