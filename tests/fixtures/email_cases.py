"""Consistent failed, success and SLA inputs for snapshots and delivered-email browser checks."""

from etl_craft.handlers.email_context import appearance
from etl_craft.handlers.email_templates import context_example


def email_case(outcome):
    data = context_example()
    status = "IN-PROGRESS" if outcome == "SLA" else outcome
    style = appearance(status)
    data["version"] = "0.3.0"
    data["recipient_reason"] = "EMAIL_TO on SI_CLIENT_ALPHA.alpha_failure_alert"
    data["subject"] = f"[PRODUCTION] Support Insights: {outcome}"
    data["project"] = {"code": "support_insights"}
    data["pipeline"] = {"code": "SI_CLIENT_ALPHA"}
    data["run"].update(status=status, **style)
    data["run"]["end"] = None if outcome == "SLA" else "2026-01-01T00:00:01+00:00"
    data["body"] = "The customer-support delivery has been checked.\nReview the run facts below."
    data["watched_tasks"][0].update(status=status, **style)
    data["pipelines"][0].update(
        status=status, code="SI_CLIENT_ALPHA", start=data["run"]["start"], end=data["run"]["end"]
    )
    if outcome == "SLA":
        data["recipient_reason"] = "pipeline EMAIL_RECIPIENTS"
        data["run"]["duration"] = "5400.00 seconds"
    if outcome != "FAILED":
        data["errors"] = []
        data["watched_tasks"][0]["error"] = None
    else:
        data["errors"] = [
            "3 records have no customer key.\nInput <customer> remains escaped.\n"
            + "record_key_" * 30
        ]
        data["watched_tasks"][0]["error"] = data["errors"][0]
    data["sla"] = (
        {
            "hours": 1,
            "elapsed_hours": 1.5,
            "message": "SLA of 1 h missed; the run is still running.",
        }
        if outcome == "SLA"
        else None
    )
    return data
