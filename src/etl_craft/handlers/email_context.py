"""Primitive presentation values shared by alert-task and SLA emails."""

from __future__ import annotations

from etl_craft import __version__
from etl_craft.core.enums import EmailFlavour, Handler, RunStatus
from etl_craft.core.errors import HandlerError
from etl_craft.engine.alerts import AlertState
from etl_craft.engine.repository.runs import TaskStatus


def appearance(status: str) -> dict[str, str]:
    """Status is conveyed by both a symbol and a color, never by color alone."""
    if status == RunStatus.SUCCESS:
        return {"symbol": "✓", "color": "#067647"}
    if status == RunStatus.FAILED:
        return {"symbol": "✕", "color": "#b42318"}
    if status == RunStatus.IN_PROGRESS:
        return {"symbol": "●", "color": "#175cd3"}
    if status == EmailFlavour.COMPLETED_WITH_ERRORS:
        return {"symbol": "⚠", "color": "#b54708"}
    return {"symbol": "—", "color": "#475467"}


def task_row(row: TaskStatus) -> dict[str, object]:
    """Keep ORM/dataclass instances out of templates."""
    return {
        "code": row.task_code,
        "status": row.status,
        "error": row.error_message,
        "attempts": row.attempt_count,
        **appearance(row.status),
    }


def email_context(state: AlertState, *, pipeline: str, status: str) -> dict[str, object]:
    """Build the documented common context; each sender supplies subject/body/recipients."""
    if state.environment is None or not state.project:
        raise HandlerError(
            f"email for {pipeline}: missing project environment evidence; restore the "
            f"project registration and retry"
        )
    relevant = [row for row in state.statuses if row.handler != Handler.EMAIL_ALERT]
    return {
        "environment": {
            "type": state.environment.type,
            "name": state.environment.name,
            "label": state.environment.label,
        },
        "project": {"code": state.project},
        "pipeline": {"code": pipeline},
        "run": {**state.run, "status": status, **appearance(status)},
        "task": None,
        "errors": [row.error_message for row in relevant if row.error_message],
        "watched_tasks": [task_row(row) for row in relevant],
        "pipelines": [
            {
                "code": row.pipeline_code,
                "run_id": row.pipeline_run_id,
                "status": row.status,
                "start": row.start_date.isoformat() if row.start_date else None,
                "end": row.end_date.isoformat() if row.end_date else None,
                "tasks": [task_row(task) for task in row.tasks],
            }
            for row in state.digests
        ],
        "sla": None
        if state.sla is None
        else {
            "hours": state.sla.sla_hours,
            "elapsed_hours": state.sla.elapsed_hours,
            "message": state.sla.describe(),
        },
        "version": __version__,
    }
