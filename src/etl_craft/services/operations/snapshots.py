"""Read canonical execution views without selecting runs by recency."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from statistics import median

from sqlalchemy import Boolean
from sqlalchemy.engine import Connection, RowMapping

from etl_craft.core.enums import (
    AttemptStatus,
    EndingEvidenceKind,
    FailureClass,
    RunStatus,
    SlaStatus,
    TriggerKind,
    YesNo,
)
from etl_craft.core.error_anchors import ErrorEvent
from etl_craft.core.errors import RunStateError, UsageError
from etl_craft.core.failures import retry_reason
from etl_craft.core.restart import restart_note
from etl_craft.core.time import as_utc
from etl_craft.engine.logs import LIVE_ATTEMPTS, LogAttempt
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.business_rules import fetch_rule_observations
from etl_craft.engine.repository.pauses import fetch_open_pause
from etl_craft.engine.repository.pipelines import fetch_pipeline_detail
from etl_craft.engine.repository.triggers import fetch_trigger_links
from etl_craft.engine.run_scopes import TaskSelection
from etl_craft.engine.runlog import as_date
from etl_craft.services.operations.attempt_log_stream import resolve_error
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.models import (
    AttemptError,
    AttemptView,
    MetricMedian,
    PipelineView,
    RunView,
    TaskRunView,
    TaskSuccessCohort,
)


def timestamp(value: object) -> datetime | None:
    """Normalize nullable Engine DB timestamps to aware UTC instants."""
    return None if value is None else as_utc(value)


def pipeline_view(conn: Connection, pipeline_id: int) -> PipelineView:
    """Read one definition and its pause within the caller's snapshot."""
    from etl_craft.engine.repository.pauses import resumes
    from etl_craft.engine.standing_pauses import current

    detail = fetch_pipeline_detail(conn, pipeline_id)
    pause = fetch_open_pause(conn, pipeline_id)
    if pause is not None:
        pause = replace(
            pause, paused_at=as_utc(pause.paused_at), pipeline_code=detail.pipeline_code
        )
    return PipelineView(
        pipeline_id,
        detail.pipeline_code,
        detail.pipeline_name,
        detail.refresh_type,
        detail.run_schedule,
        detail.sla_in_hours,
        pause,
        tuple(detail.tags or ()),
        tuple(p for p in current(conn, pipeline_id) if p.active(datetime.now(UTC))),
        resumes(conn, pipeline_id)[:1],
        auto_restart_condition=detail.auto_restart_condition,
        restart_note=restart_note(detail.auto_restart_condition),
        description=detail.description,
        start_condition=detail.start_condition,
    )


def run_view(conn: Connection, pipeline_id: int, pipeline_run_id: int) -> RunView:
    """Read the exact run; a foreign pipeline's identity never matches."""
    row = conn.execute(
        statement(conn, "operation_run"),
        {"pipeline_id": pipeline_id, "pipeline_run_id": pipeline_run_id},
    ).one_or_none()
    if row is None:
        raise RunStateError(
            f"pipeline_id={pipeline_id}: no pipeline_run_id={pipeline_run_id}; "
            "select a run belonging to this pipeline"
        )
    from etl_craft.engine.run_overrides import recorded

    links = fetch_trigger_links(conn, [pipeline_run_id])
    parent = next((link for link in links if link.child_run_id == pipeline_run_id), None)
    return replace(
        run_document(row._mapping),
        parameter_overrides=recorded(conn, pipeline_run_id),
        rules=fetch_rule_observations(conn, pipeline_id, pipeline_run_id),
        triggered_by_task_run_id=None if parent is None else parent.task_run_id,
        parent_run_id=None if parent is None else parent.parent_run_id,
        child_run_ids=tuple(
            link.child_run_id for link in links if link.parent_run_id == pipeline_run_id
        ),
    )


def run_document(row: RowMapping) -> RunView:
    """Convert a stored run row into its public document."""
    values = dict(row)
    values["run_date"] = None if values["run_date"] is None else as_date(values["run_date"])
    values["start_date"] = timestamp(values["start_date"])
    values["end_date"] = timestamp(values["end_date"])
    values["backfill"] = values["backfill"] == YesNo.YES
    values["full_refresh"] = values.get("full_refresh", YesNo.NO) == YesNo.YES
    values["trigger_kind"] = TriggerKind(values["trigger_kind"])
    values["status"] = RunStatus(values["status"])
    sla = values["sla_status"]
    values["sla_status"] = None if sla is None else SlaStatus(sla)
    selection = values.pop("task_selection", None)
    if selection is not None:
        scope = TaskSelection.deserialize(selection)
        values["selected_task_ids"] = scope.task_ids
        values["ignore_dependencies"] = scope.ignore_dependencies
    values["exclusive_run"] = values.get("exclusive_run", YesNo.YES) == YesNo.YES
    values["newer_metadata_available"] = bool(values.get("newer_metadata_available", False))
    return RunView(**values)


def task_run_view(
    conn: Connection,
    pipeline_id: int,
    *,
    task_run_id: int | None = None,
    pipeline_run_id: int | None = None,
    task_id: int | None = None,
    ctx: OperationContext | None = None,
) -> TaskRunView | None:
    """Read a task run by its id or by an exact task and pipeline-run pair."""
    if task_run_id is None and (pipeline_run_id is None or task_id is None):
        raise UsageError(
            "task run inspection needs task_run_id or both pipeline_run_id and task_id; "
            "supply an exact execution identity"
        )
    row = conn.execute(
        statement(conn, "operation_task_run"),
        {
            "pipeline_id": pipeline_id,
            "task_run_id": task_run_id,
            "pipeline_run_id": pipeline_run_id,
            "task_id": task_id,
        },
    ).one_or_none()
    if row is None:
        return None
    return replace(
        task_document(conn, row._mapping, ctx=ctx), success_cohort=success_cohort(conn, row.task_id)
    )


def success_cohort(conn: Connection, task_id: int) -> TaskSuccessCohort:
    """Calculate medians from one bounded read, excluding absent metric values."""
    rows = (
        conn.execute(
            statement(conn, "operation_task_success_cohort"),
            {"task_id": task_id, "status": RunStatus.SUCCESS},
        )
        .mappings()
        .all()
    )
    samples: dict[str, list[int | float]] = {
        name: []
        for name in (
            "source_count",
            "target_count",
            "insert_count",
            "update_count",
            "delete_count",
            "rows_written",
            "reject_count",
            "duplicate_count",
            "duration_seconds",
        )
    }
    for row in rows:
        for name, value in row.items():
            if name in samples and value is not None:
                samples[name].append(value)
        start, end = timestamp(row["start_date"]), timestamp(row["end_date"])
        if start is not None and end is not None:
            samples["duration_seconds"].append((end - start).total_seconds())
    return TaskSuccessCohort(
        len(rows),
        {
            key: MetricMedian(median(values) if values else None, len(values))
            for key, values in samples.items()
        },
    )


def task_document(
    conn: Connection, row: RowMapping, *, ctx: OperationContext | None = None
) -> TaskRunView:
    """Convert a task summary and its attempts into one public document."""
    from etl_craft.engine.standing_pauses import applied

    values = dict(row)
    has_items = values.pop("has_items", False)
    has_table_rules = values.pop("has_table_rules", False)
    item_progress = None
    by_attempt = {}
    if has_items:
        from etl_craft.engine.items import attempt_summaries, summaries

        item_progress = str(summaries(conn, [values["task_run_id"]])[values["task_run_id"]])
        by_attempt = attempt_summaries(conn, values["task_run_id"])
    values["start_date"] = timestamp(values["start_date"])
    values["end_date"] = timestamp(values["end_date"])
    values["status"] = RunStatus(values["status"])
    attempts = []
    for attempt in conn.execute(
        statement(conn, "operation_attempts").columns(retryable=Boolean),
        {"task_run_id": values["task_run_id"]},
    ):
        attempts.append(attempt_document(attempt._mapping, ctx=ctx))
    attempts = [
        replace(a, item_progress=str(by_attempt[a.attempt_id])) if a.attempt_id in by_attempt else a
        for a in attempts
    ]
    return TaskRunView(
        **values,
        standing_pause=applied(conn, row.pipeline_run_id, row.task_id),
        rules=(
            tuple(
                r
                for r in fetch_rule_observations(conn, row.pipeline_id, row.pipeline_run_id)
                if r.task_run_id == row.task_run_id
            )
            if has_table_rules
            else ()
        ),
        attempts=tuple(attempts),
        item_progress=item_progress,
        child_run_ids=tuple(
            link.child_run_id
            for link in fetch_trigger_links(conn, [row.pipeline_run_id])
            if link.task_run_id == row.task_run_id
        ),
    )


def attempt_document(row: RowMapping, *, ctx: OperationContext | None = None) -> AttemptView:
    """Normalize the same attempt document for task inspection and direct API reads."""
    captured = dict(row)
    captured.pop("has_items", None)
    for key in (
        "lease_expires_at",
        "heartbeat_at",
        "queued_at",
        "claimed_at",
        "started_at",
        "ended_at",
        "not_before",
    ):
        captured[key] = timestamp(captured[key])
    for prefix in ("process", "query"):
        key = f"{prefix}_evidence_kind"
        if captured.get(key) is not None:
            captured[key] = EndingEvidenceKind(captured[key])
    captured["status"] = AttemptStatus(captured["status"])
    captured["failure_class"] = FailureClass(captured["failure_class"])
    captured["retry_reason"] = retry_reason(
        captured["failure_class"],
        captured["failure_source"],
        captured["failure_code"],
        captured["retry_on"],
    )
    lookup = LogAttempt(
        row.attempt_id,
        captured.pop("log_engine_id"),
        captured.pop("log_project_id"),
        row.pipeline_run_id,
        row.task_run_id,
        row.attempt_number,
        captured.pop("log_pipeline_code"),
        captured.pop("log_task_code"),
        captured["status"],
        row.owner_id,
        row.log_path,
        captured.pop("log_removed_at"),
    )
    initial = captured.pop("log_initial_chunk")
    first = _anchor(captured, "first")
    last = _anchor(captured, "last")
    if ctx is not None:
        first = None if first is None else resolve_error(ctx, lookup, first, initial)
        if last is not None:
            last = (
                first
                if first is not None and first.event.sequence == last.event.sequence
                else resolve_error(ctx, lookup, last, initial)
            )
    message = (
        f"First error was not recorded for attempt {row.attempt_number}. Open the raw log."
        if first is None and lookup.status not in LIVE_ATTEMPTS | {AttemptStatus.SUCCESS}
        else None
    )
    return AttemptView(**captured, first_error=first, last_error=last, first_error_message=message)


def _anchor(values: dict[str, object], prefix: str) -> AttemptError | None:
    key = f"{prefix}_"
    sequence = values.pop(key + "sequence")
    step = values.pop(key + "step")
    error_class = values.pop(key + "error_class")
    exit_name = values.pop(key + "exit_name")
    kind = values.pop(key + "class")
    offset = values.pop(key + "offset")
    line = values.pop(key + "line")
    if sequence is None:
        return None
    assert isinstance(sequence, int)
    assert step is None or isinstance(step, str)
    assert isinstance(error_class, str) and isinstance(exit_name, str) and isinstance(kind, str)
    assert offset is None or isinstance(offset, int)
    assert line is None or isinstance(line, int)
    return AttemptError(
        ErrorEvent(sequence, step, error_class, exit_name, FailureClass(kind)), offset, line
    )
