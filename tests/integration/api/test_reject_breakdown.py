"""The reject drilldown shows final-try aggregate evidence and confirmed target removals."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api.app import create_app
from etl_craft.config import ConnectionProfile
from etl_craft.config.targets import active_catalog
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.counts import Counts
from etl_craft.core.enums import ActionName, ActionOutcome, ApiRole, AuthMode
from etl_craft.engine import transitions
from etl_craft.engine.audit import ActionRequest
from etl_craft.services.operations import OperationContext
from etl_craft.warehouse.connection import open_warehouse
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run


@pytest.mark.parametrize(
    "case",
    ["present", "gone", "removal_after", "removal_before", "zero", "retried"],
)
def test_reject_breakdown(engine_db, tmp_path, case):
    config = replace(
        engine_db.config,
        warehouse=ConnectionProfile(
            "WAREHOUSE",
            "local",
            f"jdbc:duckdb:{tmp_path / 'warehouse.duckdb'}",
            "",
            AuthMode.NONE,
            schema="main",
        ),
    )
    ctx = OperationContext(engine_db.engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    target = f"{active_catalog(config)}.main.sales"
    table = target + "__rejects"
    count = 0 if case == "zero" else 3
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "load", TARGET_OBJECT="main.sales")
        run = start_run(conn, pipeline)
        task_run = transitions.find_or_create_task_run(conn, task, run).task_run_id
        if case == "retried":
            _attempt(conn, task_run, "FAILED", 8)
        _attempt(conn, task_run, "SUCCESS", count)
        finish_run(conn, run)

    with open_warehouse(config) as warehouse, warehouse.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {table} (PIPELINE_ID BIGINT, PIPELINE_RUN_ID BIGINT, "
                "TASK_RUN_ID BIGINT, REJECT_REASON VARCHAR)"
            )
        )
        if case in {"present", "retried"}:
            conn.execute(
                text(f"INSERT INTO {table} VALUES (:pipeline,:run,:task,:reason)"),
                [
                    {"pipeline": pipeline, "run": run, "task": task_run, "reason": reason}
                    for reason in ["invalid integer", "invalid integer", "overflow"]
                ]
                + [
                    {
                        "pipeline": pipeline,
                        "run": run + 1,
                        "task": task_run,
                        "reason": "another run",
                    }
                ],
            )
    if case.startswith("removal"):
        date = datetime.now(UTC) + timedelta(days=1 if case == "removal_after" else -1)
        ActionRequest(
            ActionName.PURGE,
            {"warehouse_retention": target, "counts": {table: 5}},
            date,
            engine=ctx.engine,
            project_id=1,
            outcome=ActionOutcome.SUCCESS,
        ).record()
    credential = act(ctx, ActionName.TOKEN_CREATE, name="reader", role=ApiRole.VIEWER)
    with TestClient(create_app(ctx)) as client:
        result = client.get(
            "/api/v1/projects/default/reject-breakdown",
            params={"pipeline_code": "P", "run_id": run, "task_code": "load"},
            headers={"Authorization": f"Bearer {credential.token}"},
        )
    assert result.status_code == 200, result.text
    document = result.json()
    assert document["recorded_count"] == count
    assert document["reject_table"] == (table if count else None)
    assert document["rows"] == (
        [{"reason": "invalid integer", "count": 2}, {"reason": "overflow", "count": 1}]
        if case in {"present", "retried"}
        else []
    )
    assert bool(document["retention_removed_at"]) == (case == "removal_after")


def _attempt(conn, task_run, status, count):
    attempt = transitions.queue_attempt(conn, task_run, SYSTEM_ACTOR)
    transitions.claim_attempt(
        conn,
        attempt,
        SYSTEM_ACTOR,
        owner="test",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    transitions.start_attempt(conn, attempt, SYSTEM_ACTOR, owner="test")
    transitions.finish_attempt(
        conn, attempt, status, SYSTEM_ACTOR, owner="test", counts=Counts(reject_count=count)
    )
