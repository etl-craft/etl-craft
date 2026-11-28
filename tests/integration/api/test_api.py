"""Real token authorization and shared operation documents on both Engine DBs."""

import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy import inspect as sql_inspect

from etl_craft.api.app import create_app
from etl_craft.core.actor import Actor, ActorKind, current_actor
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import UsageError
from etl_craft.core.text import sha256_hex
from etl_craft.engine import transitions
from etl_craft.services.operations import OperationContext, to_json, tokens
from etl_craft.services.operations.actions import ACTIONS, action_path, invoke
from etl_craft.services.operations.requests import (
    AttemptId,
    HistoryInput,
    PipelineInput,
    RunId,
    RunSelection,
    TagFilter,
    TaskSelection,
)
from fixtures.metadata import add_pipeline, add_task, start_run

ROLES = tuple(role for role in ApiRole if role != ApiRole.AGENT)


def create_token(ctx, name, role, expires=None):
    request = tokens.TokenCreate(name=name, role=role, expires=expires or "365d")
    return invoke(ctx, ActionName.TOKEN_CREATE, request)


@pytest.fixture
def api(engine_db, tmp_path, request):
    ctx = OperationContext(
        engine_db.engine,
        replace(engine_db.config, log_dir=tmp_path / "logs"),
        Actor("owner", ActorKind.USER),
        role=ApiRole.ADMIN,
    )
    with ctx.engine.begin() as conn:
        engine_db.dialect.refresh_metadata_triggers(conn)
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "T", **getattr(request, "param", {}))
        run = start_run(conn, pipeline)
        summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
        attempt = transitions.queue_attempt(conn, summary, current_actor())
    creds = {role: create_token(ctx, role, role) for role in ROLES}
    client = TestClient(create_app(ctx))
    return ctx, client, creds, run, attempt


def headers(credential):
    return {"Authorization": "Bearer " + credential.token}


@pytest.mark.parametrize("role", ROLES)
def test_read_routes_require_token_and_share_cli_documents(api, role):
    ctx, client, creds, run, attempt = api
    h = headers(creds[role])
    selected = f"pipeline_code=P&run_id={run}"
    docs = {
        "/api/v1/health": {"schema": "etl-craft/health/1", "status": "ok"},
        "/api/v1/projects/default/pipelines": to_json(
            invoke(ctx, ActionName.PIPELINES, TagFilter())
        ),
        "/api/v1/projects/default/pipelines/P": to_json(
            invoke(ctx, ActionName.PIPELINE, PipelineInput(pipeline_code="P"))
        ),
        "/api/v1/projects/default/history?pipeline_code=P&all=true": to_json(
            invoke(ctx, ActionName.HISTORY, HistoryInput(pipeline_code="P", all=True))
        ),
        f"/api/v1/projects/default/runs/{run}": to_json(
            invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run))
        ),
        f"/api/v1/projects/default/steps?{selected}": to_json(
            invoke(ctx, ActionName.STEPS, RunSelection(pipeline_code="P", run_id=run))
        ),
        f"/api/v1/projects/default/explanations?{selected}&task_code=T": to_json(
            invoke(
                ctx,
                ActionName.EXPLAIN,
                TaskSelection(pipeline_code="P", task_code="T", run_id=run),
            )
        ),
        f"/api/v1/projects/default/attempts/{attempt}": to_json(
            invoke(ctx, ActionName.ATTEMPT, AttemptId(attempt_id=attempt))
        ),
    }
    for path, expected in docs.items():
        assert client.get(path).status_code == 401
        response = client.get(path, headers=h)
        assert response.status_code == 200, response.text
        assert response.json() == expected
    assert (
        client.get("/api/v1/health", headers={"Authorization": "Bearer unknown"}).status_code == 401
    )

    assert client.get("/api/v1/projects/default/runs/999999", headers=h).status_code == 404
    assert client.get("/api/v1/projects/default/attempts/999999", headers=h).status_code == 404
    assert client.get("/api/v1/projects/default/pipelines/missing", headers=h).status_code == 404
    refused = client.get("/api/v1/projects/default/history?pipeline_code=P&limit=101", headers=h)
    assert refused.status_code == 400 and "`limit`" in refused.json()["message"]
    unknown = client.get("/api/v1/projects/default/history?pipeline_code=P&unknown=1", headers=h)
    assert unknown.status_code == 400 and "`unknown`" in unknown.json()["message"]
    assert (
        client.get("/api/v1/openapi.json").json()["components"]["securitySchemes"]["HTTPBearer"][
            "scheme"
        ]
        == "bearer"
    )


def audit_counts(engine):
    with engine.connect() as conn:
        names = [n for n in sql_inspect(conn).get_table_names() if n.upper().startswith("AUD_")]
        return {n: conn.execute(text(f'SELECT COUNT(*) FROM "{n}"')).scalar_one() for n in names}


def test_read_routes_record_only_named_admin_access_or_explicit_refusals(api):
    ctx, client, creds, run, attempt = api
    given = {"pipeline_code": "P", "task_code": "T", "run_id": run, "attempt_id": attempt}
    given |= {
        "control_id": 1,
        "target": "staging.t",
        "project": "default",
        "reason": "Review",
        "upload_id": 1,
        "version": "test",
    }
    audited = {ActionName.PROJECT_LIST, ActionName.POOL_LIST, ActionName.ACCESS_LIST}
    reads = [action for action in ACTIONS.values() if action.method == "GET"]
    # Hourly token-use history is covered separately; these reads start inside that hour.
    with ctx.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_API_TOKENS SET LAST_USED_AT=CURRENT_TIMESTAMP"))
    before = audit_counts(ctx.engine)
    answered = {}
    for action in reads:
        names = {f.name for f in fields(action.request)}
        values = {k: v for k, v in given.items() if k in names}
        path = action_path(action).format(**{"project": "default", **values})
        query = {k: v for k, v in values.items() if "{" + k + "}" not in action_path(action)}
        response = client.get(path, params=query, headers=headers(creds[ApiRole.ADMIN]))
        answered[action.name] = response.status_code
        expected = dict(before)
        if action.name in audited or action.name == ActionName.CONTROL_REQUEST:
            table = next(name for name in before if name.upper() == "AUD_ACTIONS")
            expected[table] += 1 if action.name == ActionName.CONTROL_REQUEST else 2
            with ctx.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT COMMAND AS command,ACTOR AS actor FROM AUD_ACTIONS "
                        "ORDER BY ACTION_ID DESC LIMIT 1"
                    )
                ).one()
                assert row.command == action.name and row.actor == ApiRole.ADMIN
                if action.name == ActionName.CONTROL_REQUEST:
                    assert response.status_code == 404
                    assert response.json()["error"] == "ResourceNotFoundError"
        assert audit_counts(ctx.engine) == expected, action.name
        before = expected
    # Most reads answer; the rest refuse this fixture's data without additional writes.
    assert sum(code == 200 for code in answered.values()) > len(reads) // 2, answered
    assert all(code < 500 for code in answered.values()), answered


@pytest.mark.parametrize("role", ROLES)
def test_catalog_gaps_require_viewer_and_do_not_publish_lineage(api, role):
    ctx, client, creds, _run, _attempt = api
    assert client.get("/api/v1/projects/default/catalog/gaps").status_code == 401
    with ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID AS pipeline_id FROM CFG_PIPELINES WHERE PIPELINE_CODE='P'")
        ).scalar_one()
        add_task(
            conn,
            pipeline,
            "lineage",
            SQL_ACTION="CREATE_TABLE",
            TARGET_OBJECT="api.output",
            SELECT_QUERY="SELECT 1 AS id",
        )
    with ctx.engine.connect() as conn:
        before = conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_LINEAGE_VERSIONS")
        ).scalar_one()
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(ctx.engine, "before_cursor_execute", capture)
    response = client.get("/api/v1/projects/default/catalog/gaps", headers=headers(creds[role]))
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "etl-craft/catalog-gaps/1"
    assert body["compared_at"] is None and body["contract_version"]
    assert any(r["table"] == "api.output" for r in body["records"])
    compared = client.get(
        "/api/v1/projects/default/catalog/gaps?compare=true", headers=headers(creds[role])
    )
    assert compared.status_code == 200 and compared.json()["compared_at"]
    event.remove(ctx.engine, "before_cursor_execute", capture)
    assert not any("AUD_LINEAGE_VERSION" in sql.upper() for sql in statements)
    with ctx.engine.connect() as conn:
        after = conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_LINEAGE_VERSIONS")
        ).scalar_one()
    assert after == before


def test_empty_catalog_does_not_claim_a_warehouse_check(api):
    _ctx, client, creds, _run, _attempt = api
    response = client.get(
        "/api/v1/projects/default/catalog/gaps?compare=true", headers=headers(creds["viewer"])
    )
    assert response.status_code == 200
    assert response.json()["records"] == []
    assert response.json()["compared_at"] is None


@pytest.mark.parametrize("role", ROLES)
def test_every_write_route_enforces_role_and_passes_actor_to_service(api, role, monkeypatch):
    ctx, client, creds, run, _attempt = api
    original_control = ACTIONS[ActionName.CONTROL]
    calls = []

    def done(caller, request):
        calls.append((caller.actor.name, request))
        return invoke(ctx, ActionName.PIPELINES, TagFilter())

    cases = [
        (
            ActionName.RUN,
            {"pipeline_code": "P", "task_code": "T", "run_id": run, "standalone": True},
        ),
        (ActionName.RUN, {"pipeline_code": "P"}),
        (
            ActionName.RUN,
            {
                "pipeline_code": "P",
                "backfill_from": "2026-01-01",
                "backfill_to": "2026-01-02",
                "reason": "test",
            },
        ),
        (ActionName.CONTROL, {"pipeline_code": "P", "action": "PAUSE", "reason": "test"}),
        (ActionName.CONTROL, {"pipeline_code": "P", "action": "RESUME", "reason": "test"}),
        (
            ActionName.MARK,
            {
                "pipeline_code": "P",
                "run_id": run,
                "task_code": "T",
                "status": "SUCCESS",
                "reason": "t",
            },
        ),
        (
            ActionName.MARK,
            {
                "pipeline_code": "P",
                "run_id": run,
                "task_code": "T",
                "watermark": "0",
                "reason": "r",
            },
        ),
        (
            ActionName.RUN,
            {"pipeline_code": "P", "run_id": run, "task_code": "T", "rerun": True, "reason": "t"},
        ),
    ]
    for name, body in cases:
        action = ACTIONS[name]
        monkeypatch.setitem(ACTIONS, name, replace(action, call=done))
        assert (
            client.post(action_path(action).format(project="default"), json=body).status_code == 401
        )
        response = client.post(
            action_path(action).format(project="default"), json=body, headers=headers(creds[role])
        )
        assert response.status_code == (403 if role == "viewer" else 200), response.text
        if role != "viewer":
            caller, request = calls[-1]
            assert caller == role
            assert request.pipeline_code == "P"
            assert request.run_id == body.get("run_id")
    if role == "viewer":
        assert calls == []
    monkeypatch.setitem(ACTIONS, ActionName.CONTROL, original_control)
    response = client.post(
        "/api/v1/projects/default/controls",
        json={"pipeline_code": "P", "action": "PAUSE", "reason": " "},
        headers=headers(creds["operator"]),
    )
    assert response.status_code == 400 and "--reason" in response.json()["message"]


@pytest.mark.parametrize("role", ROLES)
def test_token_admin_routes_and_immediate_revocation(api, role):
    _ctx, client, creds, _run, _attempt = api
    h = headers(creds[role])
    assert client.get("/api/v1/tokens", headers=h).status_code == (200 if role == "admin" else 403)
    response = client.post(
        "/api/v1/tokens", headers=h, json={"name": "new", "role": "viewer", "expires": "90d"}
    )
    assert response.status_code == (200 if role == "admin" else 403)
    response = client.post(
        "/api/v1/tokens/revoke", headers=h, json={"token_id": creds["viewer"].metadata.token_id}
    )
    assert response.status_code == (200 if role == "admin" else 403)
    if role == "admin":
        assert client.get("/api/v1/health", headers=headers(creds["viewer"])).status_code == 401
        assert "token_sha256" not in response.text.lower()
    assert client.get("/api/v1/tokens").status_code == 401
    assert client.post("/api/v1/tokens", json={"name": "x", "role": "viewer"}).status_code == 401
    assert client.post("/api/v1/tokens/revoke", json={"token_id": 1}).status_code == 401


def test_tokens_store_hash_only_expiry_validation_and_audit(api):
    ctx, client, creds, _run, _attempt = api
    value = create_token(ctx, "expires", "operator", "1d")
    with ctx.engine.begin() as conn:
        digest = conn.execute(
            text("SELECT TOKEN_SHA256 AS digest FROM CFG_API_TOKENS WHERE TOKEN_ID=:id"),
            {"id": value.metadata.token_id},
        ).scalar_one()
        assert digest == sha256_hex(value.token.encode())
        conn.execute(
            text("UPDATE CFG_API_TOKENS SET EXPIRES_AT=:now WHERE TOKEN_ID=:id"),
            {"now": datetime.now(UTC) - timedelta(seconds=1), "id": value.metadata.token_id},
        )
        requests = conn.execute(
            text("SELECT COMMAND AS command, ARGUMENTS AS arguments FROM AUD_ACTIONS")
        ).all()
        assert len(requests) == 2 * (len(creds) + 1)
        assert all(row.command == "token create" for row in requests)
        audit = str(requests)
        assert value.token not in audit
    assert client.get("/api/v1/health", headers=headers(value)).status_code == 401
    assert tokens.authenticate(ctx, "") is None
    assert tokens.authenticate(ctx, "x" * 257) is None
    for expires in ["0d", "-1d", "1h", "36501d", "9" * 5000 + "d"]:
        with pytest.raises(UsageError):
            create_token(ctx, "bad", "viewer", expires)
    root = client.post(
        "/api/v1/tokens", headers=headers(creds["admin"]), json={"name": "bad", "role": "root"}
    )
    assert root.status_code == 400 and "`role`" in root.json()["message"]
    with pytest.raises(UsageError):
        invoke(ctx, ActionName.TOKEN_REVOKE, tokens.TokenRevoke(token_id=999999))
    pause = {"pipeline_code": "P", "action": "PAUSE", "reason": "maintenance"}
    response = client.post(
        "/api/v1/projects/default/controls", headers=headers(creds["operator"]), json=pause
    )
    assert response.status_code == 200, response.text
    assert response.json()["pipeline"]["paused"]["paused_by"] == "operator"
    assert (
        client.post(
            "/api/v1/projects/default/controls",
            headers=headers(creds["operator"]),
            json={**pause, "reason": "again"},
        ).status_code
        == 409
    )
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT PAUSED_BY AS actor FROM AUD_PIPELINE_PAUSES")).scalar_one()
            == "operator"
        )


def test_log_streaming_offsets_and_path_boundaries(api, tmp_path):
    ctx, client, creds, run, attempt = api
    with ctx.engine.connect() as conn:
        project_id = conn.execute(
            text("SELECT PROJECT_ID AS project_id FROM CFG_PROJECTS WHERE PROJECT_CODE='default'")
        ).scalar_one()
    path = ctx.config.log_dir / f"project-{project_id}" / "P" / f"run-{run}" / "T.attempt-1.log"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"first\nsecond\n")
    url = f"/api/v1/projects/default/attempts/{attempt}/log"
    for role in ROLES:
        assert client.get(url, headers=headers(creds[role])).status_code == 404
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET LOG_PATH=:path WHERE ATTEMPT_ID=:id"),
            {"path": str(path), "id": attempt},
        )
    for role in ROLES:
        assert client.get(url, headers=headers(creds[role])).content == b"first\nsecond\n"
    assert client.get(url).status_code == 401
    assert client.get(url + "?offset=6", headers=headers(creds["viewer"])).content == b"second\n"
    assert client.get(url + "?offset=-1", headers=headers(creds["viewer"])).status_code == 400
    outside = tmp_path / "secret"
    outside.write_text("secret")
    path.unlink()
    path.symlink_to(outside)
    assert client.get(url, headers=headers(creds["viewer"])).status_code == 404


def test_run_history_cursor_is_bounded_and_exact(api):
    ctx, client, creds, run, _attempt = api
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE AUD_PIPELINES_RUN_LOG SET STATUS='SUCCESS' WHERE PIPELINE_RUN_ID=:id"),
            {"id": run},
        )
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES WHERE PIPELINE_CODE='P'")
        ).scalar_one()
        second = start_run(conn, pipeline)
    h = headers(creds["viewer"])
    first = client.get(
        "/api/v1/projects/default/history?pipeline_code=P&all=true&limit=1", headers=h
    ).json()
    assert first["entries"][0]["pipeline_run_id"] == second
    assert first["before"] == second
    last = client.get(
        f"/api/v1/projects/default/history?pipeline_code=P&all=true&limit=1&before={second}",
        headers=h,
    ).json()
    assert last["entries"][0]["pipeline_run_id"] == run
    assert last["before"] is None


def test_grid_reads_extra_run_and_cells_without_moving_cursor(api):
    ctx, client, creds, first, attempt = api
    from fixtures.metadata import finish_run

    with ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES WHERE PIPELINE_CODE='P'")
        ).scalar_one()
        finish_run(conn, first)
        second = start_run(conn, pipeline)
    response = client.get(
        "/api/v1/projects/default/history",
        headers=headers(creds["viewer"]),
        params={
            "pipeline_code": "P",
            "all": True,
            "cells": True,
            "limit": 1,
            "extra_run_id": first,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["before"] == second
    assert [r["pipeline_run_id"] for r in body["entries"]] == [second]
    assert body["extra_run"]["pipeline_run_id"] == first
    (cell,) = body["cells"]
    assert (cell["task_code"], cell["pipeline_run_id"], cell["attempt_id"]) == ("T", first, attempt)
    assert cell["task_run_label"]


def test_run_status_filter_pages_through_matching_runs_only(api):
    ctx, client, creds, first, _attempt = api
    from fixtures.metadata import finish_run

    with ctx.engine.begin() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES WHERE PIPELINE_CODE='P'")
        ).scalar_one()
        finish_run(conn, first, "FAILED")
        middle = start_run(conn, pipeline)
        finish_run(conn, middle)
        newest = start_run(conn, pipeline)
    url, viewer = "/api/v1/projects/default/history", headers(creds["viewer"])
    page = {"pipeline_code": "P", "all": True, "cells": True, "limit": 1}
    failed = client.get(url, headers=viewer, params=page | {"run_status": ["FAILED"]})
    assert failed.status_code == 200, failed.text
    body = failed.json()
    # The newer SUCCESS and IN-PROGRESS runs are skipped by the query, not trimmed from a page.
    assert [r["pipeline_run_id"] for r in body["entries"]] == [first]
    assert {cell["pipeline_run_id"] for cell in body["cells"]} <= {first}
    both = client.get(
        url, headers=viewer, params=page | {"limit": 5, "run_status": ["FAILED", "IN-PROGRESS"]}
    ).json()
    assert [r["pipeline_run_id"] for r in both["entries"]] == [newest, first]
    assert middle not in {r["pipeline_run_id"] for r in both["entries"]}
    refused = client.get(url, headers=viewer, params={"pipeline_code": "P", "run_status": "FAILED"})
    assert refused.status_code == 400
    assert "`run_status` filter a list of pipeline runs" in refused.text


def test_token_changes_are_not_captured_and_accept_no_project_scope(api):
    ctx, client, creds, _run, _attempt = api
    with ctx.engine.begin() as conn:
        assert not conn.execute(
            text("SELECT 1 AS found FROM AUD_METADATA_CHANGES WHERE TABLE_NAME='CFG_API_TOKENS'")
        ).first()
        conn.execute(
            text("UPDATE CFG_API_TOKENS SET PROJECT_ID=1 WHERE TOKEN_ID=:id"),
            {"id": creds["viewer"].metadata.token_id},
        )
    assert client.get("/api/v1/health", headers=headers(creds["viewer"])).status_code == 401


def test_engine_unavailable_response_does_not_echo_storage_parameters(api, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    _ctx, client, _creds, _run, _attempt = api

    def broken(*args, **kwargs):
        raise SQLAlchemyError("secret credential")

    monkeypatch.setattr("etl_craft.api.routes.authenticate", broken)
    response = client.get("/api/v1/health", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 503
    assert "secret" not in response.text


def test_live_http_trigger_is_executed_by_controller_and_shutdown_is_clean(cli_project):
    import signal
    import socket
    import time
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    import yaml

    p = cli_project
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        port = bound.getsockname()[1]
    path = p.config.config_path
    config = yaml.safe_load(path.read_text())
    config["Orchestration"]["Api_address"] = f"127.0.0.1:{port}"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    code, output = p.run(
        "token", "create", "--name", "web", "--role", "operator", "--format", "json"
    )
    assert code == 0, output
    credential = json.loads(output)["token"]
    server = p.start("controller")
    p.wait_for("SELECT COUNT(*) FROM AUD_CONTROLLERS", expected=1)
    base = f"http://127.0.0.1:{port}/api/v1"
    deadline = time.monotonic() + 10
    while True:
        try:
            with urlopen(
                Request(base + "/health", headers={"Authorization": "Bearer " + credential}),
                timeout=2,
            ) as response:
                assert response.status == 200
            break
        except URLError:
            assert time.monotonic() < deadline, server.output
            time.sleep(0.02)
    with urlopen(
        Request(
            base + "/projects/default/runs",
            data=b'{"pipeline_code":"P","reason":"HTTP refresh"}',
            headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"},
        ),
        timeout=5,
    ) as response:
        result = json.loads(response.read())
    run = result["run"]["pipeline_run_id"]
    assert result["run"]["started_by"] == "web"
    p.wait_for(
        f"SELECT STATUS FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID={run}", expected="SUCCESS"
    )
    server.signal(signal.SIGTERM)
    assert server.wait() == 0, server.output
    p.wait_for("SELECT COUNT(*) FROM AUD_CONTROLLERS WHERE STOPPED_AT IS NOT NULL", expected=1)
    with p.engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT ACTOR AS actor FROM AUD_ACTIONS WHERE COMMAND='run' "
                    "ORDER BY ACTION_ID DESC LIMIT 1"
                )
            ).scalar_one()
            == "web"
        )
        arguments = conn.execute(
            text(
                "SELECT ARGUMENTS AS args FROM AUD_ACTIONS WHERE COMMAND='run' "
                "ORDER BY ACTION_ID DESC LIMIT 1"
            )
        ).scalar_one()
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        assert arguments["reason"] == "HTTP refresh"


@pytest.mark.parametrize(
    "api",
    [
        {
            "TARGET_OBJECT": "s.events",
            "SQL_ACTION": "APPEND_TABLE",
            "SELECT_QUERY": "SELECT id FROM raw.events WHERE id > $$watermark",
            "WATERMARK_COLUMN": "id",
            "WATERMARK_TYPE": "NUMBER",
            "WATERMARK_START": "0",
        }
    ],
    indirect=True,
)
def test_watermark_reset_validates_and_audits_the_api_actor(api):
    from etl_craft.config import ConnectionProfile
    from etl_craft.engine.repository.offsets import fetch_task_offset

    ctx, client, creds, run, attempt = api
    config = replace(
        ctx.config,
        warehouse=ConnectionProfile(
            "WAREHOUSE", "local", "jdbc:duckdb:warehouse.duckdb", "", "NONE"
        ),
    )
    client = TestClient(create_app(replace(ctx, config=config)))
    with ctx.engine.begin() as conn:
        task = conn.execute(text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE='T'")).scalar_one()
    path = "/api/v1/projects/default/marks"
    h = headers(creds["operator"])
    selected = {"pipeline_code": "P", "task_code": "T", "run_id": run}
    for body in (
        {"reason": "reset"},
        {"status": "SUCCESS", "watermark": "1", "reason": "reset"},
        {"watermark": "1", "rows": 1, "reason": "reset"},
    ):
        assert client.post(path, json={**selected, **body}, headers=h).status_code == 400
    reset = {**selected, "watermark": "1", "reason": "reset"}
    assert client.post(path, json=reset, headers=h).status_code == 409
    with ctx.engine.begin() as conn:
        transitions.cancel_attempt(conn, attempt, current_actor(), error_message="cancelled")
    response = client.post(path, json=reset, headers=h)
    assert response.status_code == 200, response.text
    with ctx.engine.connect() as conn:
        assert fetch_task_offset(conn, task).offset_value == "1"
        intervention = conn.execute(
            text("SELECT REQUESTED_BY, REASON FROM AUD_RUN_INTERVENTIONS WHERE TASK_ID=:task"),
            {"task": task},
        ).one()
        assert tuple(intervention) == ("operator", "reset")


def test_server_refuses_an_api_address_in_use_before_taking_leadership(cli_project):
    import socket

    import yaml

    p = cli_project
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        path = p.config.config_path
        config = yaml.safe_load(path.read_text())
        config["Orchestration"]["Api_address"] = f"127.0.0.1:{port}"
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        code, output = p.run("controller")
    assert code == 10, output
    assert f"Orchestration.Api_address 127.0.0.1:{port} cannot be used" in output
    assert "set Api_address to a free port" in output
    with p.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_CONTROLLERS")).scalar_one() == 0


def test_run_refuses_unknown_fields_and_host_only_options(api):
    _ctx, client, creds, _run, _attempt = api
    h = headers(creds["operator"])
    task = {"pipeline_code": "P", "task_code": "T", "standalone": True}
    unknown = client.post(
        "/api/v1/projects/default/runs", json={**task, "unexpected": True}, headers=h
    )
    assert unknown.status_code == 400 and "`unexpected`" in unknown.json()["message"]
    forced = client.post(
        "/api/v1/projects/default/runs", json={"pipeline_code": "P", "force": True}, headers=h
    )
    assert forced.status_code == 400
    assert "`force` works only on the controller's host" in forced.json()["message"]


def test_scoped_control_routes_share_durable_identity_and_role_policy(api):
    _, client, creds, run, attempt = api
    path = "/api/v1/projects/default/controls"
    body = {
        "pipeline_code": "P",
        "action": "STOP",
        "task_code": "T",
        "run_id": run,
        "reason": "maintenance",
        "request_key": "stop:first:T",
    }
    assert client.post(path, json=body, headers=headers(creds["viewer"])).status_code == 403
    first = client.post(path, json=body, headers=headers(creds["operator"]))
    assert first.status_code == 200
    document = first.json()
    assert document["schema"] == "etl-craft/control/1"
    assert document["action"] == "STOP" and document["status"] == "COMPLETED"
    assert document["requested_by"] == "operator" and document["task_code"] == "T"
    assert document["run_status"] == "IN-PROGRESS" and document["attempt_ids"] == [attempt]
    repeated = client.post(path, json=body, headers=headers(creds["operator"]))
    assert repeated.json()["control_id"] == document["control_id"]
    read = client.get(
        f"/api/v1/projects/default/control-requests/{document['control_id']}",
        headers=headers(creds["viewer"]),
    )
    assert read.status_code == 200 and read.json() == document
    assert (
        client.post(
            path, json={**body, "unexpected": True}, headers=headers(creds["operator"])
        ).status_code
        == 400
    )
    stop = client.post(
        path,
        json={**body, "action": "STOP", "request_key": "stop:T"},
        headers=headers(creds["operator"]),
    )
    assert stop.status_code == 200 and stop.json()["status"] == "COMPLETED"
    assert stop.json()["run_status"] == "IN-PROGRESS"
    assert stop.json()["attempt_ids"] == [attempt]


def test_recovery_capabilities_and_bulk_routes_share_exact_requests(api):
    _, client, creds, run, _ = api
    viewer, operator = headers(creds["viewer"]), headers(creds["operator"])
    caps = client.get(
        f"/api/v1/projects/default/capabilities?pipeline_code=P&run_id={run}", headers=viewer
    )
    assert caps.status_code == 200 and caps.json()["schema"] == "etl-craft/capabilities/1"
    assert all(not a["available"] for a in caps.json()["actions"])
    body = {
        "requests": [
            {
                "pipeline_code": "P",
                "run_id": run,
                "task_code": "T",
                "action": "STOP",
                "reason": "selected task",
                "request_key": "bulk:T",
            },
            {
                "pipeline_code": "P",
                "run_id": run,
                "action": "RESTART",
                "reason": "restart",
                "request_key": "bulk:restart",
            },
        ]
    }
    assert (
        client.post("/api/v1/projects/default/controls/bulk", json=body, headers=viewer).status_code
        == 403
    )
    result = client.post("/api/v1/projects/default/controls/bulk", json=body, headers=operator)
    assert result.status_code == 200, result.text
    outcomes = result.json()["outcomes"]
    assert outcomes[0]["control"]["task_code"] == "T"
    assert outcomes[1]["control"] is None and outcomes[1]["error"]
    repeated = client.post("/api/v1/projects/default/controls/bulk", json=body, headers=operator)
    assert (
        repeated.json()["outcomes"][0]["control"]["control_id"]
        == outcomes[0]["control"]["control_id"]
    )
    rejected = client.post(
        "/api/v1/projects/default/controls/bulk",
        json={"requests": [{**body["requests"][0], "unexpected": True}]},
        headers=operator,
    )
    assert rejected.status_code == 400


def test_attempt_endpoint_retains_failure_evidence_and_retry_policy(api):
    from etl_craft.core.enums import FailureClass
    from etl_craft.core.failures import Failure

    ctx, client, creds, _run, attempt = api
    with ctx.engine.begin() as conn:
        transitions.claim_attempt(
            conn,
            attempt,
            current_actor(),
            owner="test",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        transitions.record_attempt_failure(
            conn, attempt, Failure(FailureClass.PERMANENT, "ProgrammingError", "42P01")
        )
        transitions.finish_attempt(conn, attempt, "FAILED", current_actor(), owner="test")
    response = client.get(
        f"/api/v1/projects/default/attempts/{attempt}", headers=headers(creds[ApiRole.VIEWER])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failure_class"] == "PERMANENT"
    assert body["failure_source"] == "ProgrammingError"
    assert body["failure_code"] == "42P01"
    assert body["retry_on"] == "TRANSIENT"
    assert not body["retryable"]
    assert "RETRY_ON=TRANSIENT" in body["retry_reason"]


def test_an_exact_run_id_cannot_cross_the_route_project_even_for_admin(api):
    ctx, client, creds, _run, _attempt = api
    with ctx.engine.begin() as conn:
        other = conn.execute(
            text(
                "INSERT INTO CFG_PROJECTS (PROJECT_CODE,PROJECT_NAME,DEFAULT_POOL) "
                "VALUES ('other','Other','default') RETURNING PROJECT_ID AS project_id"
            )
        ).scalar_one()
        pipeline = conn.execute(
            text(
                "INSERT INTO CFG_PIPELINES (PROJECT_ID,PIPELINE_CODE,PIPELINE_NAME,REFRESH_TYPE) "
                "VALUES (:id,'P','Other P','FULL') RETURNING PIPELINE_ID AS pipeline_id"
            ),
            {"id": other},
        ).scalar_one()
        foreign_run = start_run(conn, pipeline)
    credential = headers(creds[ApiRole.ADMIN])
    assert (
        client.get(f"/api/v1/projects/default/runs/{foreign_run}", headers=credential).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/projects/other/runs/{foreign_run}", headers=credential).status_code
        == 200
    )
    response = client.get("/api/v1/projects/other/pipelines", headers=credential)
    assert [row["pipeline_id"] for row in response.json()["pipelines"]] == [pipeline]
    from etl_craft.services.operations.requests import NoInput

    invoke(ctx, ActionName.DOCS_VERSION, NoInput())
    invoke(replace(ctx, project="other"), ActionName.DOCS_VERSION, NoInput())
    audit = client.get("/api/v1/projects/other/audit", headers=credential).json()
    with ctx.engine.connect() as conn:
        foreign_actions = set(
            conn.execute(
                text("SELECT ACTION_ID AS action_id FROM AUD_ACTIONS WHERE PROJECT_ID=1")
            ).scalars()
        )
    assert foreign_actions and not foreign_actions.intersection(
        row["action_id"] for row in audit["actions"]
    )
    owned_pipeline_changes = [
        row for row in audit["changes"] if row["table_name"] == "CFG_PIPELINES"
    ]
    assert owned_pipeline_changes
    assert all(row["after_json"]["project_id"] == other for row in owned_pipeline_changes)


def test_foreign_project_prefix_cannot_masquerade_as_a_local_pipeline_grant(api):
    from etl_craft.services.operations.status import DependencyView
    from etl_craft.services.operations.visibility import visible_result

    ctx, _client, _creds, _run, _attempt = api
    with ctx.engine.begin() as conn:
        add_pipeline(conn, "foreign")
    value = DependencyView(
        "foreign.secret",
        "SUCCESS",
        "SUCCESS",
        True,
        "private status",
        selected_pipeline_run_id=777,
        pipeline_dependency_id=1,
    )
    redacted = visible_result(replace(ctx, role=ApiRole.VIEWER, project_id=1), value)
    assert redacted.selected_pipeline_run_id is None
    assert redacted.status is None and "private" not in redacted.reason


def test_a_refused_enum_value_keeps_the_case_of_the_values_it_lists(api):
    _ctx, client, creds, _run, _attempt = api
    response = client.get(
        "/api/v1/projects/default/lineage?table=a.b&direction=sideways",
        headers=headers(creds["viewer"]),
    )
    assert response.status_code == 400
    message = response.json()["message"]
    assert "'BOTH', 'UPSTREAM' or 'DOWNSTREAM'" in message


def test_api_run_labels_match_exactly_for_paths_queries_and_json(api):
    ctx, client, creds, run, _ = api
    auth = headers(creds[ApiRole.ADMIN])
    label = invoke(ctx, ActionName.RUN_DETAIL, RunId(run_id=run)).run_label
    assert (
        client.get(f"/api/v1/projects/default/runs/{label}", headers=auth).json()["pipeline_run_id"]
        == run
    )
    for value in (run, str(run), label):
        response = client.get(
            "/api/v1/projects/default/status", params={"run_id": value}, headers=auth
        )
        assert response.status_code == 200, response.text
        assert response.json()["run"]["pipeline_run_id"] == run
    response = client.post(
        "/api/v1/projects/default/controls",
        headers=auth,
        json={"pipeline_code": "P", "run_id": label, "action": "STOP", "reason": "exact label"},
    )
    assert response.status_code == 200, response.text
    for wrong in ("WRONG-" + label, label.lower()):
        response = client.get(
            "/api/v1/projects/default/status", params={"run_id": wrong}, headers=auth
        )
        assert response.status_code == 409, response.text
        assert label in response.text


def test_run_display_labels_are_carried_by_nested_and_attempt_responses(api):
    ctx, client, creds, run, attempt = api
    auth = headers(creds[ApiRole.ADMIN])
    with ctx.engine.connect() as conn:
        stored = conn.execute(
            text("SELECT RUN_LABEL AS label FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:id"),
            {"id": run},
        ).scalar_one()
        task = conn.execute(
            text(
                "SELECT TASK_RUN_ID AS id, TASK_RUN_LABEL AS label FROM AUD_TASK_RUN_LOG "
                "WHERE PIPELINE_RUN_ID=:id"
            ),
            {"id": run},
        ).one()
    paths = [
        f"/api/v1/projects/default/attempts/{attempt}",
        "/api/v1/projects/default/history?pipeline_code=P&task_code=T&all=true",
        "/api/v1/projects/default/pipelines",
        f"/api/v1/projects/default/steps?pipeline_code=P&run_id={run}",
    ]
    for path in paths:
        response = client.get(path, headers=auth)
        assert response.status_code == 200, response.text
        document = response.json()
        assert stored in json.dumps(document), path
        if "attempts/" in path:
            assert document["pipeline_run_id"] == run
            assert document["task_run_id"] == task.id
            assert document["task_run_label"] == task.label


def test_run_api_requires_reasons_by_governance_not_environment(api):
    from fixtures.actions import act

    ctx, client, creds, _, _ = api
    for environment, policy in (("DEV", "STRICT"), ("DEV", "RELAXED"), ("PROD", "STRICT")):
        act(
            ctx,
            ActionName.PROJECT_SET,
            project="default",
            environment_type=environment,
            governance=policy,
            reason="set test policy",
        )
        code = f"REASON_{environment}_{policy}"
        with ctx.engine.begin() as conn:
            pipeline = add_pipeline(conn, code)
            add_task(conn, pipeline, "T", "PYTHON")
        response = client.post(
            "/api/v1/projects/default/runs",
            json={"pipeline_code": code},
            headers=headers(creds[ApiRole.ADMIN]),
        )
        if policy == "STRICT":
            assert response.status_code == 400, response.text
            assert "non-empty reason" in response.json()["message"]
            assert "STRICT" in response.json()["message"]
            refused = client.post(
                "/api/v1/projects/default/reconciliations",
                json={"pipeline_code": code},
                headers=headers(creds[ApiRole.ADMIN]),
            )
            assert refused.status_code == 400
            assert "STRICT" in refused.json()["message"]
        else:
            assert response.status_code == 200, response.text
            assert response.json()["run"]["pipeline_run_id"] is not None


def test_run_overrides_share_admission_replay_and_authorization(api):
    ctx, client, creds, _, _ = api
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "OVERRIDE_INPUTS")
        add_task(conn, pipeline, "load", "PYTHON", INPUT_PARAMS='{"day":1}')
    payload = {
        "pipeline_code": "OVERRIDE_INPUTS",
        "params": ['load.INPUT_PARAMS={"day":2}'],
        "request_key": "api-inputs",
        "reason": "one-off input",
    }
    path = "/api/v1/projects/default/runs"
    denied = client.post(path, headers=headers(creds[ApiRole.VIEWER]), json=payload)
    assert denied.status_code == 403
    first = client.post(path, headers=headers(creds[ApiRole.OPERATOR]), json=payload)
    assert first.status_code == 200, first.text
    replay = client.post(path, headers=headers(creds[ApiRole.OPERATOR]), json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["run"]["pipeline_run_id"] == first.json()["run"]["pipeline_run_id"]
    assert replay.json()["run"]["parameter_overrides"] == {"load": {"INPUT_PARAMS": '{"day":2}'}}
    conflict = client.post(
        path,
        headers=headers(creds[ApiRole.OPERATOR]),
        json={**payload, "params": ['load.INPUT_PARAMS={"day":3}']},
    )
    assert conflict.status_code >= 400 and "payload differs" in conflict.text


def test_full_refresh_asks_for_confirmation_over_http_then_records_the_confirmed_plan(api):
    ctx, client, creds, _, _ = api
    sql = {
        "SQL_ACTION": "APPEND_TABLE",
        "WATERMARK_COLUMN": "id",
        "WATERMARK_TYPE": "NUMBER",
        "WATERMARK_START": "0",
        "SELECT_QUERY": "SELECT 1 AS id",
    }
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "REFRESHED")
        add_task(conn, pipeline, "load", "SQL", TARGET_OBJECT="mart.orders", **sql)
        python = add_pipeline(conn, "INGESTED")
        add_task(conn, python, "pull", "PYTHON", SCRIPT_FILE="pull.py")
    path = "/api/v1/projects/default/runs"
    ask = {"pipeline_code": "REFRESHED", "full_refresh": True, "reason": "profile corrected"}
    refused = client.post(path, headers=headers(creds[ApiRole.OPERATOR]), json=ask)
    assert refused.status_code == 428, refused.text
    assert refused.json()["targets"] == ["mart.orders"] and refused.json()["exit_code"] == 31
    assert "load: mart.orders" in refused.json()["message"]
    wrong = client.post(
        path, headers=headers(creds[ApiRole.OPERATOR]), json={**ask, "empty_targets": ["mart.x"]}
    )
    assert wrong.status_code == 428 and wrong.json()["targets"] == ["mart.orders"]
    with ctx.engine.connect() as conn:  # nothing was created by either refusal
        runs = conn.execute(
            text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_ID=:p"),
            {"p": pipeline},
        ).scalar_one()
    assert runs == 0
    viewer = client.post(path, headers=headers(creds[ApiRole.VIEWER]), json=ask)
    assert viewer.status_code == 403
    # A refresh with nothing to confirm is admitted for the controller, with its plan recorded.
    plain = {"pipeline_code": "INGESTED", "full_refresh": True, "reason": "source corrected"}
    started = client.post(path, headers=headers(creds[ApiRole.OPERATOR]), json=plain)
    assert started.status_code == 200, started.text
    run_id = started.json()["run"]["pipeline_run_id"]
    assert started.json()["run"]["full_refresh"] is True
    with ctx.engine.connect() as conn:
        plan = conn.execute(
            text(
                "SELECT FULL_REFRESH_PLAN AS plan FROM AUD_PIPELINES_RUN_LOG "
                "WHERE PIPELINE_RUN_ID=:r"
            ),
            {"r": run_id},
        ).scalar_one()
    assert json.loads(plan) == {"empty_targets": [], "tasks": None}
    again = client.post(path, headers=headers(creds[ApiRole.OPERATOR]), json=plain)
    assert again.status_code == 409 and "own run" in again.text


def test_alert_delivery_history_is_visible_without_secret_values(api, monkeypatch):
    from fixtures.alerts import failed_delivery

    ctx, client, creds, run, _attempt = api
    monkeypatch.setenv("ALERT_URL", "https://receiver.invalid/private-url-token")
    monkeypatch.setenv("ALERT_KEY", "private-signing-key-" + "x" * 32)
    with ctx.engine.connect() as conn:
        pipeline = conn.execute(
            text("SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE='P'")
        ).scalar_one()
    failed_delivery(ctx, pipeline, run)
    response = client.get(
        "/api/v1/projects/default/pipelines/P", headers=headers(creds[ApiRole.ADMIN])
    )
    assert response.status_code == 200, response.text
    records = response.json()["alert_deliveries"]
    assert records[-1]["status"] == "ADMITTED" and records[0]["status_code"] == 503
    assert "private-url-token" not in response.text and "private-signing-key" not in response.text
    projects = client.get("/api/v1/projects?reason=inspect", headers=headers(creds[ApiRole.ADMIN]))
    assert projects.status_code == 200, projects.text
    assert projects.json()["projects"][0]["alert_deliveries"]
    assert "private-url-token" not in projects.text and "private-signing-key" not in projects.text


@pytest.mark.parametrize("action", ["HOLD", "RELEASE"])
def test_removed_hold_controls_are_refused_and_holds_route_is_absent(api, action):
    ctx, client, creds, run, _ = api
    auth = headers(creds["operator"])
    response = client.post(
        "/api/v1/projects/default/controls",
        headers=auth,
        json={"pipeline_code": "P", "run_id": run, "action": action, "reason": "maintenance"},
    )
    assert response.status_code == 400, response.text
    message = response.json()["message"]
    assert "control" in message and "`action`" in message
    assert action in message and "STOP" in message
    assert "choose one of the expected values" in message
    assert response.json()["exit_code"] == 2
    assert client.get("/api/v1/projects/default/holds", headers=auth).status_code == 404
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_CONTROL_REQUESTS")).scalar_one()
            == 0
        )


@pytest.mark.parametrize("with_mode", [False, True])
def test_task_pause_api_requires_outcome_and_refuses_pipeline_mode_before_writes(api, with_mode):
    ctx, client, creds, _, _ = api
    body = {"pipeline_code": "P", "task_code": "T", "action": "PAUSE", "reason": "maintenance"}
    if with_mode:
        body.update(active_runs="DRAIN", outcome="SKIPPED")
    response = client.post(
        "/api/v1/projects/default/controls", headers=headers(creds["operator"]), json=body
    )
    assert response.status_code == 400, response.text
    message = response.json()["message"]
    assert "pipeline P task T" in message
    assert (
        "task pauses take an outcome, not --active-runs"
        if with_mode
        else "a task pause needs --outcome SUCCESS, SKIPPED or FAILED"
    ) in message
    assert ("active_runs=DRAIN" if with_mode else "outcome=None") in message
    assert ("omit --active-runs" if with_mode else "supply --outcome") in message
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) AS count FROM AUD_PIPELINE_PAUSES")).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "api", [{"SELECT_QUERY": "select 'pinned-secret-value', '$$rule_flags'"}], indirect=True
)
def test_steps_source_reads_pinned_inline_sql_with_masking(api):
    from etl_craft.core.redaction import remember

    ctx, client, creds, run, _ = api
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE CFG_TASK_PARAMETERS SET PARAMETER_VALUE='select 42' "
                "WHERE PARAMETER_NAME='SELECT_QUERY'"
            )
        )
    remember("pinned-secret-value")
    path = "/api/v1/projects/default/steps"
    params = {"pipeline_code": "P", "run_id": run}
    viewer = headers(creds[ApiRole.VIEWER])
    ordinary = client.get(path, headers=viewer, params=params)
    assert ordinary.status_code == 200, ordinary.text
    assert "source" not in ordinary.json()
    source = client.get(path, headers=viewer, params={**params, "source_task": "T"})
    assert source.status_code == 200, source.text
    assert source.json()["source"]["text"] == "select '[REDACTED]', '$$rule_flags'"
    assert source.json()["source"]["version"]
    assert (
        client.get(
            path, headers=viewer, params={**params, "source_task": "T", "path": "other.sql"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize("api", [{"SCRIPT_FILE": "sql_scripts/pinned.sql"}], indirect=True)
def test_steps_source_refuses_missing_pinned_file(api):
    _, client, creds, run, _ = api
    answer = client.get(
        "/api/v1/projects/default/steps",
        headers=headers(creds[ApiRole.VIEWER]),
        params={"pipeline_code": "P", "run_id": run, "source_task": "T"},
    )
    assert answer.status_code == 404, answer.text
    for detail in (f"run {run}", "task 'T'", "version", "sql_scripts/pinned.sql", "restore"):
        assert detail in answer.text


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (b"SELECT 17 AS old_value\n", 200),
        (b"x" * (256 * 1024 - 1) + "é".encode(), 200),
        (b"SELECT \xff", 409),
        (b"SELECT \x00", 409),
    ],
)
def test_steps_source_reads_exact_bundle_bytes(api, tmp_path, contents, expected):
    from base64 import b64encode

    from etl_craft.config.object_models import Artifacts
    from etl_craft.services.operations.bundles import PublishBundle, publish

    ctx, _, creds, _, _ = api
    ctx = replace(
        ctx, config=replace(ctx.config, artifacts=Artifacts((tmp_path / "store").as_uri()))
    )
    ctx = replace(ctx, project="default", project_id=1)
    config = (
        b"Secrets:\n  Source_type: ENVIRONMENT\nEngine:\n"
        b"  dev:\n    Jdbc_url: jdbc:sqlite:engine.db\n    Schema: main\n"
    )
    path = "sql_scripts/load.sql"

    def encode(value):
        return b64encode(value).decode("ascii")

    publish(
        ctx,
        PublishBundle(
            files={
                "craft-connector.yml": encode(config),
                path: encode(contents),
            }
        ),
    )
    ctx.engine.update_execution_options(bundles_enabled=True)
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "PINNED")
        add_task(conn, pipeline, "LOAD", SCRIPT_FILE=path)
        run = start_run(conn, pipeline)
    publish(
        ctx,
        PublishBundle(
            files={
                "craft-connector.yml": encode(config),
                path: encode(b"SELECT 42 AS new_value"),
            }
        ),
    )
    with TestClient(create_app(ctx)) as client:
        response = client.get(
            "/api/v1/projects/default/steps",
            headers=headers(creds[ApiRole.VIEWER]),
            params={"pipeline_code": "PINNED", "run_id": run, "source_task": "LOAD"},
        )
    assert response.status_code == expected, response.text
    if expected != 200:
        assert "UTF-8" in response.text and path in response.text
        return
    source = response.json()["source"]
    assert source["file"] == path
    assert source["text"] == contents[: 256 * 1024].decode(errors="ignore")
    assert source["truncated_at_bytes"] == (256 * 1024 - 1 if len(contents) > 256 * 1024 else None)


@pytest.mark.parametrize("action", ["RECOVER", "RESTART"])
def test_recovery_preview_has_the_same_http_refusal_as_submission(api, action):
    _ctx, client, creds, run, _ = api
    path = "/api/v1/projects/default/controls"
    auth = headers(creds[ApiRole.OPERATOR])
    scope = {
        "pipeline_code": "P",
        "run_id": run,
        "action": action,
        "reason": "verify that the live attempt has ended",
    }
    audit = "/api/v1/projects/default/audit"
    before = client.get(audit, headers=auth).json()["actions"]
    preview = client.post(path, headers=auth, json={**scope, "dry_run": True})
    after = client.get(audit, headers=auth).json()["actions"]
    assert after == before
    actual = client.post(path, headers=auth, json=scope)
    assert preview.status_code == actual.status_code == 409
    assert preview.json()["message"] == actual.json()["message"]
    assert "requires ended ownership" in preview.json()["message"]


def test_statistics_read_is_scoped_and_preserves_absent_attempt_values(api):
    ctx, client, creds, run, attempt = api
    token = headers(creds[ApiRole.VIEWER])
    path = f"/api/v1/projects/default/runs/{run}/statistics"
    result = client.get(path, headers=token)
    assert result.status_code == 200, result.text
    [task] = result.json()["tasks"]
    assert task["task_code"] == "T"
    assert task["duration"] == {"median": None, "sample_size": 0}
    [row] = task["attempts"]
    assert row["attempt_id"] == attempt
    assert row["source_count"] is None
    assert row["peak_rss_bytes"] is None

    from fixtures.actions import act

    act(
        ctx,
        ActionName.ACCESS_REVOKE,
        project="default",
        audience="viewer",
        role="CAN_VIEW",
        reason="restrict pipeline",
    )
    act(
        ctx,
        ActionName.ACCESS_REVOKE,
        project="default",
        audience="operator",
        role="CAN_RUN",
        reason="restrict pipeline",
    )
    for denied in (
        client.get(path, headers=token),
        client.get(
            "/api/v1/projects/default/reject-breakdown",
            params={"pipeline_code": "P", "run_id": run, "task_code": "T"},
            headers=token,
        ),
    ):
        assert denied.status_code in (403, 404), denied.text
        assert "attempts" not in denied.json() and "rows" not in denied.json()
