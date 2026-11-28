"""Read-only operation documents for pipeline definitions and execution history."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import Boolean, bindparam
from sqlalchemy.engine import Connection

from etl_craft.core.conditions import edge_kind, is_plain, pipeline_edge_kind
from etl_craft.core.enums import ActionName, ApiRole, EdgeKind, RunStatus
from etl_craft.core.errors import ConfigurationError, ResourceNotFoundError
from etl_craft.core.graph import TaskNode, build_graph
from etl_craft.core.restart import restart_note
from etl_craft.core.time import as_utc
from etl_craft.engine.connection import read_snapshot
from etl_craft.engine.logs import (
    LIVE_ATTEMPTS,
    read_log_attempt,
    shared_log,
)
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.audit_reads import fetch_audit_records
from etl_craft.engine.repository.business_rules import fetch_rule_observations
from etl_craft.engine.repository.dependencies import (
    fetch_cross_pipeline_task_edges,
    fetch_pipeline_dependency_edges,
    fetch_pipeline_graph,
)
from etl_craft.engine.repository.intervention_rows import fetch_interventions
from etl_craft.engine.repository.pauses import fetch_open_pauses
from etl_craft.engine.repository.pipelines import read_tags, resolve_pipeline_id, tagged_pipelines
from etl_craft.engine.repository.tasks import (
    fetch_task_codes,
    fetch_task_parameters,
    resolve_task_id,
)
from etl_craft.engine.run_definitions import for_run
from etl_craft.engine.runlog import select_run
from etl_craft.services.operations.attempt_log_stream import canonical_log
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import (
    ActionView,
    AttemptView,
    AuditView,
    GraphView,
    GridCell,
    HistoryView,
    MetadataChangeView,
    PipelineListView,
    PipelineView,
    RunView,
    StepsView,
    StepsWithSource,
    StepView,
    TaskRunView,
)
from etl_craft.services.operations.permissions import pipeline_access, visible_codes
from etl_craft.services.operations.pipeline_summaries import summarize, workspace_summary
from etl_craft.services.operations.requests import (
    AttemptId,
    AuditInput,
    HistoryInput,
    LogInput,
    PipelineInput,
    RunId,
    StepsInput,
    TagFilter,
)
from etl_craft.services.operations.snapshots import (
    attempt_document,
    pipeline_view,
    run_document,
    run_view,
    task_document,
    timestamp,
)


def list_pipelines(ctx: OperationContext, request: TagFilter) -> PipelineListView:
    """List the active definitions."""
    from etl_craft.engine.standing_pauses import current

    with read_snapshot(ctx.engine) as conn:
        pauses = fetch_open_pauses(conn)
        task_pauses = tuple(p for p in current(conn, None) if p.active(datetime.now(UTC)))
        access = pipeline_access(conn, ctx)
        views = []
        for row in conn.execute(statement(conn, "active_pipelines")):
            tags = read_tags(row.pipeline_parameters, row.pipeline_code)
            if not access.permits(row.pipeline_code) or not set(request.tag) <= set(tags):
                continue
            pause = pauses.get(row.pipeline_code)
            if pause is not None:
                pause = replace(pause, paused_at=as_utc(pause.paused_at))
            views.append(
                PipelineView(
                    row.pipeline_id,
                    row.pipeline_code,
                    row.pipeline_name,
                    row.refresh_type,
                    row.run_schedule,
                    None if row.sla_in_hours is None else float(row.sla_in_hours),
                    pause,
                    tags,
                    tuple(p for p in task_pauses if p.pipeline_id == row.pipeline_id),
                    auto_restart_condition=row.auto_restart_condition,
                    restart_note=restart_note(row.auto_restart_condition),
                    description=row.description,
                    start_condition=row.start_condition,
                )
            )
        return PipelineListView(summarize(conn, views, datetime.now(UTC), _pinned(ctx)))


def pipeline_graph(ctx: OperationContext, request: PipelineInput) -> GraphView:
    """Read the static graph with the pipeline's canonical definition id."""
    pipeline_code = request.pipeline_code
    with read_snapshot(ctx.engine) as conn:
        pipeline_id = resolve_pipeline_id(conn, pipeline_code)
        data = fetch_pipeline_graph(conn, pipeline_id)
        codes = fetch_task_codes(conn, pipeline_id)
        graph = build_graph(data.tasks, data.same_pipeline_edges)
        depends_on: dict[str, list[tuple[str, str]]] = {
            codes[task_id]: [] for task_id in graph.task_ids
        }
        for edge in data.same_pipeline_edges:
            node = graph.node(edge.task_id)
            name = next(n for n, t in node.upstream.items() if t == edge.depends_on_task_id)
            depends_on[codes[edge.task_id]].append(
                (codes[edge.depends_on_task_id], _kind(node, name))
            )
        for task_id in sorted(data.cross_pipeline_task_ids):
            node = graph.node(task_id)
            for cross in fetch_cross_pipeline_task_edges(conn, task_id):
                name = next(n for n, d in node.cross.items() if d == cross.task_dependency_id)
                depends_on[codes[task_id]].append((cross.depends_on_label, _kind(node, name)))
        view = pipeline_view(conn, pipeline_id)
        start_condition = view.start_condition
        return GraphView(
            pipeline_id,
            pipeline_code,
            tuple(tuple(codes[task_id] for task_id in wave) for wave in graph.waves()),
            tuple(
                sorted(
                    codes[task.task_id]
                    for task in data.tasks
                    if task.condition is not None and not is_plain(task.condition)
                )
            ),
            {code: tuple(sorted(edges)) for code, edges in sorted(depends_on.items())},
            tuple(
                (
                    edge.depends_on_pipeline_code,
                    pipeline_edge_kind(
                        start_condition,
                        edge.depends_on_pipeline_code,
                        ".".join(edge.qualified_name),
                    ),
                )
                for edge in fetch_pipeline_dependency_edges(conn, pipeline_id)
            ),
            view.task_pauses,
        )


def _kind(node: TaskNode, name: tuple[str, ...]) -> str:
    return EdgeKind.CONDITION if node.condition is None else edge_kind(node.condition, name)


def pipeline_steps(ctx: OperationContext, request: StepsInput) -> StepsView:
    """Read configured tasks under the exact selected run, including tasks not yet started."""
    if request.source_task is not None:
        from etl_craft.services.operations.actions import ACTIONS, authorize_action

        log = ACTIONS[ActionName.RUN_LOG]
        authorize_action(ctx, log, request, log.required_role(ctx, request))
    with read_snapshot(ctx.engine) as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        selected = select_run(conn, pipeline_id, request.selector)
        with for_run(conn, selected.pipeline_run_id):
            if request.source_task is not None:
                from etl_craft.services.operations.step_source import read_source

                task_id = resolve_task_id(conn, pipeline_id, request.source_task)
                source = read_source(
                    conn, ctx, selected.pipeline_run_id, request.source_task, task_id
                )
                return StepsWithSource(pipeline_id, selected.pipeline_run_id, (), source=source)
            steps = tuple(
                StepView(
                    pipeline_id,
                    selected.pipeline_run_id,
                    row.task_id,
                    row.task_code,
                    row.task_run_id,
                    row.task_type,
                    row.handler,
                    row.run_condition,
                    dict(sorted(fetch_task_parameters(conn, row.task_id).items())),
                    None if row.status is None else RunStatus(row.status),
                )
                for row in conn.execute(
                    statement(conn, "pipeline_steps"),
                    {"pipeline_id": pipeline_id, "run_id": selected.pipeline_run_id},
                )
            )
            return StepsView(pipeline_id, selected.pipeline_run_id, steps)


def run_history(ctx: OperationContext, request: HistoryInput) -> HistoryView:
    """Read one pipeline's history, or a bounded page across matching active pipelines."""
    assert not isinstance(request.run_id, str), "run reference must be resolved"
    if request.run_id is not None and request.pipeline_code is None:
        from etl_craft.services.operations.permissions import run_pipeline_code

        request = replace(request, pipeline_code=run_pipeline_code(ctx, request.run_id))
    if request.pipeline_code is not None and not request.tag:
        return _pipeline_history(ctx, request)
    with read_snapshot(ctx.engine) as conn:
        codes = visible_codes(conn, ctx, tagged_pipelines(conn, request.tag))
        if request.pipeline_code is not None:
            pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
            if request.pipeline_code not in codes:
                return HistoryView(pipeline_id, request.pipeline_code, request.task_code, (), ())
            return _read_history(conn, request, (pipeline_id,))
        return _read_history(conn, replace(request, all=True), tuple(codes.values()))


def _pipeline_history(ctx: OperationContext, request: HistoryInput) -> HistoryView:
    assert request.pipeline_code is not None
    with read_snapshot(ctx.engine) as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        return _read_history(conn, request, (pipeline_id,))


def _read_history(
    conn: Connection, request: HistoryInput, pipeline_ids: tuple[int, ...]
) -> HistoryView:
    pipeline_id = pipeline_ids[0] if request.pipeline_code is not None else None
    task_code, limit = request.task_code, request.limit
    selected = (
        None
        if request.all or pipeline_id is None
        else select_run(conn, pipeline_id, request.selector).pipeline_run_id
    )
    parameters: dict[str, object] = {
        "limit": limit + 1,
        "run_id": selected,
        "before": request.before,
        "pool": request.pool,
        "agent": None if request.agent is None else str(request.agent),
        "failure_class": request.failure_class,
        # An empty status list keeps every run; the placeholder only keeps the IN list valid SQL.
        "status_filter": int(bool(request.run_status)),
        "statuses": [status.value for status in request.run_status] or [""],
    }
    entries: tuple[RunView | TaskRunView, ...]
    if task_code is None:
        entries = _history_runs(conn, pipeline_ids, parameters)
    else:
        assert pipeline_id is not None
        entries = tuple(
            task_document(conn, row._mapping)
            for row in conn.execute(
                statement(conn, "task_run_history"),
                {
                    **parameters,
                    "pipeline_id": pipeline_id,
                    "task_id": resolve_task_id(conn, pipeline_id, task_code),
                },
            )
        )
    more, entries = len(entries) > limit, entries[:limit]
    listed = {entry.pipeline_run_id for entry in entries}
    changes = tuple(
        replace(change, requested_at=as_utc(change.requested_at))
        for change in fetch_interventions(conn, listed)
        if task_code is None or change.task_code in (None, task_code)
    )
    extra: tuple[RunView, ...] = ()
    if request.extra_run_id is not None and request.extra_run_id not in listed:
        extra = _history_runs(
            conn,
            pipeline_ids,
            # A run selected outside the page is shown whatever the status filter.
            dict.fromkeys(parameters)
            | {"run_id": request.extra_run_id, "limit": 1, "status_filter": 0, "statuses": [""]},
        )
        listed.update(run.pipeline_run_id for run in extra)
    return HistoryView(
        pipeline_id,
        request.pipeline_code,
        task_code,
        entries,
        changes,
        entries[-1].pipeline_run_id if more else None,
        rules=tuple(
            r
            for r in fetch_rule_observations(conn, pipeline_id, selected)
            if task_code is None or r.task_code == task_code
        )
        if pipeline_id is not None and not request.cells
        else (),
        cells=_history_cells(conn, listed) if request.cells else (),
        extra_run=extra[0] if extra else None,
        task_order=_grid_task_order(conn, pipeline_id)
        if request.cells and pipeline_id is not None
        else (),
    )


def _grid_task_order(conn: Connection, pipeline_id: int) -> tuple[str, ...]:
    data = fetch_pipeline_graph(conn, pipeline_id)
    graph = build_graph(data.tasks, data.same_pipeline_edges)
    codes = {task.task_id: task.task_code or task.label for task in data.tasks}
    return tuple(
        code
        for wave in graph.waves()
        for code in sorted(codes[task] for task in wave if task not in data.event_alerts)
    ) + tuple(sorted(codes[task] for task in data.event_alerts))


def _history_runs(
    conn: Connection, pipeline_ids: tuple[int, ...], parameters: dict[str, object]
) -> tuple[RunView, ...]:
    if not pipeline_ids:
        return ()
    query = statement(conn, "pipeline_run_history").bindparams(
        bindparam("pipeline_ids", expanding=True), bindparam("statuses", expanding=True)
    )
    return tuple(
        run_document(row._mapping)
        for row in conn.execute(query, parameters | {"pipeline_ids": pipeline_ids})
    )


def _history_cells(conn: Connection, run_ids: set[int]) -> tuple[GridCell, ...]:
    if not run_ids:
        return ()
    query = statement(conn, "history_cells").bindparams(bindparam("run_ids", expanding=True))
    return tuple(
        GridCell(
            row.task_code,
            row.task_run_id,
            row.pipeline_run_id,
            RunStatus(row.status),
            row.attempt_count,
            row.attempt_id,
            timestamp(row.start_date),
            timestamp(row.end_date),
            row.task_run_label,
        )
        for row in conn.execute(query, {"run_ids": sorted(run_ids)})
    )


def audit(ctx: OperationContext, request: AuditInput) -> AuditView:
    """Read completed requests and immutable metadata captures without making an action."""
    from etl_craft.engine.repository.pauses import resumes

    pipeline_code = request.pipeline_code
    since = None if request.since is None else as_utc(request.since)
    with read_snapshot(ctx.engine) as conn:
        pipeline_id = None if pipeline_code is None else resolve_pipeline_id(conn, pipeline_code)
        ids = (
            set(visible_codes(conn, ctx, tagged_pipelines(conn, request.tag)).values())
            if request.tag or ctx.role != ApiRole.ADMIN
            else None
        )
        if ids is not None and pipeline_id is not None:
            ids &= {pipeline_id}
        actions, changes = fetch_audit_records(
            conn,
            pipeline_id if ids is None else None,
            since,
            pipeline_ids=ids,
            project_id=ctx.project_id,
        )
        for row in (*actions, *changes):
            row["at"] = as_utc(row["at"])
        for row in actions:
            selected = row["arguments"].get("run_id")
            row["pipeline_run_id"] = selected if isinstance(selected, int) else None
        if request.mine:
            mine = [row for row in actions if row["actor"] == ctx.actor.name]
            return AuditView(tuple(ActionView(**row) for row in mine), ())
        return AuditView(
            tuple(ActionView(**row) for row in actions),
            tuple(MetadataChangeView(**row) for row in changes),
            tuple(
                r for r in resumes(conn, pipeline_id, since) if ids is None or r.pipeline_id in ids
            ),
        )


def get_pipeline(ctx: OperationContext, request: PipelineInput) -> PipelineView:
    """Read one active definition without duplicating pipeline assembly."""
    with read_snapshot(ctx.engine) as conn:
        view = pipeline_view(conn, resolve_pipeline_id(conn, request.pipeline_code))
        from etl_craft.engine.repository.pipelines import current_project_id
        from etl_craft.services.operations.alert_history import history

        view = replace(
            view, alert_deliveries=history(conn, current_project_id(), (request.pipeline_code,))
        )
        return workspace_summary(conn, summarize(conn, (view,), datetime.now(UTC), _pinned(ctx))[0])


def _pinned(ctx: OperationContext) -> bool:
    """Whether schedules read the re-parsed pipeline definitions, as the controller does."""
    return bool(ctx.engine.get_execution_options().get("reparse_required"))


def get_run(ctx: OperationContext, request: RunId) -> RunView:
    """Read one run by id, never an active or recent replacement."""
    assert isinstance(request.run_id, int), "run reference must be resolved"
    with read_snapshot(ctx.engine) as conn:
        code = conn.execute(
            statement(conn, "api_run_code"), {"run_id": request.run_id}
        ).scalar_one_or_none()
        if code is None:
            raise ResourceNotFoundError(f"pipeline_run_id={request.run_id}: run does not exist")
        from etl_craft.services.operations.timeline import run_timeline

        view = run_view(conn, resolve_pipeline_id(conn, str(code)), request.run_id)
        return replace(view, timeline=run_timeline(conn, request.run_id))


def get_attempt(ctx: OperationContext, request: AttemptId) -> AttemptView:
    """Read one attempt with the same fields and conversions as CLI inspection."""
    with read_snapshot(ctx.engine) as conn:
        row = conn.execute(
            statement(conn, "api_attempt").columns(retryable=Boolean),
            {"attempt_id": request.attempt_id},
        ).one_or_none()
        if row is None:
            raise ResourceNotFoundError(f"attempt_id={request.attempt_id}: attempt does not exist")
        view = attempt_document(row._mapping, ctx=ctx)
        if row.has_items:
            from etl_craft.engine.items import attempt_summaries

            return replace(
                view, item_progress=str(attempt_summaries(conn, row.task_run_id)[row.attempt_id])
            )
        return view


def attempt_log(ctx: OperationContext, request: LogInput) -> Iterator[bytes]:
    """Stream a stored attempt's canonical log in bounded chunks from a byte offset."""
    attempt_id = request.attempt_id
    with ctx.engine.connect() as conn:
        row = read_log_attempt(conn, attempt_id)
        if row is None:
            raise ResourceNotFoundError(f"attempt_id={attempt_id}: attempt does not exist")
        if row.log_removed_at is not None:
            return iter([f"removed by retention on {row.log_removed_at}\n".encode()])
        shared = conn.execute(
            statement(conn, "agent_chunk_last"), {"attempt_id": attempt_id}
        ).first()
    if row.log_path is None:
        if shared is not None and shared.byte_offset + shared.byte_length > 0:
            return shared_log(ctx.engine, attempt_id, request.offset)
        if shared is None and row.status not in LIVE_ATTEMPTS:
            raise ResourceNotFoundError(
                f"attempt_id={attempt_id}: no stored log or uploaded chunks; expected a recorded "
                "log location; inspect preserved TASK_LOG and restore the original log source"
            )
        raise ResourceNotFoundError(
            f"attempt_id={attempt_id}: log pending upload; expected acknowledged log bytes; "
            "wait for the agent or controller to publish the log"
        )
    source = canonical_log(ctx, row, request.offset)
    try:
        first = next(source, None)
    except (ConfigurationError, ResourceNotFoundError):
        with ctx.engine.connect() as conn:
            removed = conn.execute(
                statement(conn, "retention_log_removed"), {"attempt_id": attempt_id}
            ).scalar_one_or_none()
        if removed is not None:
            return iter([f"removed by retention on {removed}\n".encode()])
        raise

    def chunks() -> Iterator[bytes]:
        try:
            if first is not None:
                yield first
            yield from source
        finally:
            source.close()

    return chunks()
