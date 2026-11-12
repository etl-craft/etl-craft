"""Alert observations admit isolated work and retain sanitized delivery evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import ApiRole, RunStatus
from etl_craft.engine import transitions
from etl_craft.engine.run_scopes import fetch_selection
from etl_craft.services.operations.context import OperationContext
from fixtures.metadata import add_dependency, add_pipeline, add_task, start_run
from fixtures.webhook import webhook as webhook


@pytest.fixture
def alerts(engine_db, monkeypatch):
    monkeypatch.setenv("ALERT_URL", "https://receiver.invalid/private-url-token")
    monkeypatch.setenv("ALERT_KEY", "private-signing-key-" + "x" * 32)
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ALERT_SOURCE")
        data = add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="load.py")
        task = add_task(
            conn,
            pipeline,
            "notify",
            "EMAIL_ALERT",
            ALERT_CHANNEL="ops",
        )
        add_dependency(conn, pipeline, task, data, "ALWAYS")
        channel = conn.execute(
            text(
                "INSERT INTO CFG_ALERT_CHANNELS(PROJECT_ID,CHANNEL_NAME,KIND,URL_SECRET,"
                "SIGNING_SECRET,BODY_FORMAT,DEFAULT_ALERT_ON) VALUES(1,'ops','WEBHOOK',"
                "'ALERT_URL','ALERT_KEY','JSON','FAILURE|SLA_BREACH|LOST|GATE_WAIT_OVER_5') "
                "RETURNING CHANNEL_ID"
            )
        ).scalar_one()
        source = start_run(conn, pipeline)
    ctx = OperationContext(
        engine_db.engine,
        engine_db.config,
        SYSTEM_ACTOR,
        role=ApiRole.ADMIN,
        project_id=1,
        project="default",
    )
    return ctx, pipeline, source, task, channel, data


def failed_source(alerts):
    ctx, _pipeline, source, task, _channel, _data = alerts
    with ctx.engine.begin() as conn:
        transitions.finalize_pipeline_run(conn, source, RunStatus.FAILED)
    return ctx, source, task


def test_failure_admits_only_alert_task_once_without_changing_paused_source(alerts):
    from etl_craft.controller.supervisor import WorkingSet
    from etl_craft.engine.repository.pauses import record_pause
    from etl_craft.engine.runlog import RunSelector
    from etl_craft.execution.interventions import open_pause
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, source, task = failed_source(alerts)
    with ctx.engine.begin() as conn:
        record_pause(conn, alerts[1], "operator", "investigate")
    with acting_as(SYSTEM_ACTOR):
        admitted = admit_pending(ctx)
        assert len(admitted) == 1
        assert admit_pending(ctx) == ()
        run = admitted[0]
        assert open_pause(ctx.engine, "ALERT_SOURCE", selector=RunSelector(run_id=run)) is None
        assert (
            open_pause(ctx.engine, "ALERT_SOURCE", selector=RunSelector(run_id=source)) is not None
        )
        with ctx.engine.connect() as conn:
            assert fetch_selection(conn, run).task_ids == (task,)
            assert fetch_selection(conn, run).ignore_dependencies
            assert (
                conn.execute(
                    text("SELECT STATUS FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:id"),
                    {"id": source},
                ).scalar_one()
                == RunStatus.FAILED
            )
        assert run in [r.pipeline_run_id for r in WorkingSet().refresh(ctx)]


def test_alert_failures_never_admit_recursive_alerts(alerts):
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, _task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        with ctx.engine.begin() as conn:
            transitions.finalize_pipeline_run(conn, run, RunStatus.FAILED)
        assert admit_pending(ctx) == ()


def test_sla_lost_and_gate_events_each_admit_once_while_source_is_running(alerts, monkeypatch):
    from etl_craft.services.operations import alert_admission
    from etl_craft.services.operations.alert_admission import admit_pending

    monkeypatch.setattr(alert_admission, "ADMISSION_BATCH", 1, raising=False)
    ctx, _pipeline, source, _task, _channel, data = alerts
    now = datetime(2026, 11, 12, tzinfo=UTC)
    with ctx.engine.begin() as conn:
        transitions.mark_sla_breached(conn, source)
        binding = transitions.find_or_create_task_run(conn, data, source)
        attempt = transitions.queue_attempt(conn, binding.task_run_id, SYSTEM_ACTOR)
        transitions.claim_attempt(
            conn, attempt, SYSTEM_ACTOR, owner="gone", lease_expires_at=now - timedelta(seconds=1)
        )
        transitions.lose_attempt(conn, attempt, SYSTEM_ACTOR, owner="gone")
        conn.execute(
            text(
                "INSERT INTO AUD_GATE_WAITS(PIPELINE_RUN_ID,FIRST_CHECK_AT,NEXT_CHECK_AT,"
                "LOOKS,WAIT_UNTIL,WAIT_KIND) VALUES(:run,:start,:now,1,:end,'DEPENDENCY')"
            ),
            {
                "run": source,
                "start": now - timedelta(minutes=6),
                "now": now,
                "end": now + timedelta(minutes=5),
            },
        )
    with acting_as(SYSTEM_ACTOR):
        batches = [admit_pending(ctx, now) for _ in range(3)]
        assert [len(batch) for batch in batches] == [1, 1, 1]
        assert len({run for batch in batches for run in batch}) == 3
        assert admit_pending(ctx, now + timedelta(minutes=1)) == ()


def task_for(ctx, run, task):
    from etl_craft.execution.context import build_task_context

    with ctx.engine.begin() as conn:
        binding = transitions.find_or_create_task_run(conn, task, run)
    return build_task_context(ctx.engine, ctx.config, binding.task_run_id)


def test_delivery_signs_exact_bytes_and_never_records_secrets(alerts, monkeypatch, caplog):
    import hashlib
    import hmac
    import json

    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, source, task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    received = []

    def post(url, body, headers):
        received.append((url, body, headers))
        return 204, None

    monkeypatch.setattr(alert_delivery, "post", post)
    result = alert_delivery.deliver(ctx, context)
    assert result.variables["ALERT_SENT"] is True
    url, body, headers = received[0]
    signed = headers["X-ETL-Craft-Timestamp"].encode() + b"." + body
    expected = hmac.new(
        ("private-signing-key-" + "x" * 32).encode(), signed, hashlib.sha256
    ).hexdigest()
    assert headers["X-ETL-Craft-Signature"] == "v1=" + expected
    assert json.loads(body)["run"]["id"] == source
    with ctx.engine.connect() as conn:
        facts = str(conn.execute(text("SELECT * FROM AUD_ALERT_DELIVERIES")).all())
    for value in (url, "private-signing-key-" + "x" * 32):
        assert value not in facts and value not in caplog.text


def test_failed_delivery_uses_fixed_backoff_and_records_terminal_failure(alerts, monkeypatch):
    from etl_craft.core.errors import HandlerError
    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    delays = []

    class Clock:
        def wait(self, delay):
            delays.append(delay)
            return False

    monkeypatch.setattr(alert_delivery.threading, "Event", Clock)
    monkeypatch.setattr(alert_delivery, "post", lambda *args: (503, "HTTPError"))
    with pytest.raises(HandlerError, match=r"channel ops.*delivery failed"):
        alert_delivery.deliver(ctx, context)
    assert delays == [5, 30, 120]
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT STATUS AS status,ATTEMPT_NUMBER AS number "
                "FROM AUD_ALERT_DELIVERIES ORDER BY DELIVERY_ID"
            )
        ).all()
    assert [r.number for r in rows if r.status == "STARTED"] == [1, 2, 3, 4]
    assert rows[-1].status == "FAILED"


def test_missing_admin_secret_reference_refuses_channel_without_echo(alerts, monkeypatch):
    from etl_craft.core.errors import ConfigurationError
    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    monkeypatch.delenv("ALERT_URL")
    with pytest.raises(ConfigurationError, match="channel ops, variable ALERT_URL: missing"):
        alert_delivery.deliver(ctx, context)


def test_slack_delivery_uses_plain_text_shape(alerts, monkeypatch):
    import json

    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, task = failed_source(alerts)
    with ctx.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_ALERT_CHANNELS SET KIND='SLACK',BODY_FORMAT='SLACK'"))
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    sent = []
    monkeypatch.setattr(
        alert_delivery,
        "post",
        lambda url, body, headers: sent.append(json.loads(body)) or (200, None),
    )
    alert_delivery.deliver(ctx, context)
    assert "ALERT_SOURCE" in sent[0]["text"] and sent[0]["link_names"] is False


def test_concurrent_observers_admit_one_alert_run(alerts):
    from etl_craft.services.operations.alert_admission import admit_pending
    from fixtures.races import two_at_once

    ctx, _source, _task = failed_source(alerts)
    first, second = two_at_once(
        lambda: admit_pending(ctx), lambda: admit_pending(ctx), at=(ctx.engine, "begin")
    )
    assert len(first + second) == 1


def test_crash_after_receiver_acceptance_replays_the_same_event_id(alerts, monkeypatch):
    import json

    from etl_craft.core.errors import InjectedFaultError
    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    events = []

    def interrupted(url, body, headers):
        events.append(json.loads(body)["event_id"])
        raise InjectedFaultError("crash after remote acceptance")

    monkeypatch.setattr(alert_delivery, "post", interrupted)
    with pytest.raises(InjectedFaultError):
        alert_delivery.deliver(ctx, context)

    def accepted(url, body, headers):
        events.append(json.loads(body)["event_id"])
        return 200, None

    monkeypatch.setattr(alert_delivery, "post", accepted)
    alert_delivery.deliver(ctx, context)
    assert len(events) == 2 and events[0] == events[1]


def test_alert_history_and_actor_guards_are_immutable_and_project_scoped(alerts):
    from sqlalchemy.exc import DBAPIError

    from etl_craft.services.operations.alert_admission import admit_pending
    from etl_craft.services.operations.alert_history import history

    ctx, _source, _task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (_run,) = admit_pending(ctx)
    with ctx.engine.connect() as conn:
        assert len(history(conn, 1, ("ALERT_SOURCE",))) == 1
        assert history(conn, 2, ("ALERT_SOURCE",)) == ()
        assert history(conn, 1, ("OTHER",)) == ()
    for sql in (
        "UPDATE AUD_ALERT_DELIVERIES SET EVENT_ID='changed'",
        "DELETE FROM AUD_ALERT_DELIVERIES",
    ):
        with (
            pytest.raises(DBAPIError, match=r"append-only|written only"),
            ctx.engine.begin() as conn,
        ):
            conn.execute(text(sql))


def test_selected_alert_run_executes_over_tls_while_source_is_paused(
    alerts, webhook, monkeypatch, tmp_path
):
    import hashlib
    import hmac
    import json

    import yaml

    from etl_craft.config import load_config
    from etl_craft.engine.repository.pauses import record_pause
    from etl_craft.engine.runlog import RunSelector
    from etl_craft.execution.pipeline import run_pipeline
    from etl_craft.services.operations.alert_admission import admit_pending
    from fixtures.engine_db import profile_block

    ctx, source, task = failed_source(alerts)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "craft-connector.yml"
    block = profile_block(ctx.config.engine, ctx.config.engine.schema or "main")
    if ctx.config.engine.jdbc_url.startswith("jdbc:sqlite:"):
        block["Jdbc_url"] = "jdbc:sqlite:" + str(ctx.engine.url.database)
    path.write_text(
        yaml.safe_dump(
            {
                "Secrets": {"Source_type": "ENVIRONMENT"},
                "Orchestration": {"Project": "default"},
                "Engine": {"dev": block},
            },
            sort_keys=False,
        )
    )
    ctx = replace(ctx, config=load_config(path))
    address, received, _ = webhook
    monkeypatch.setenv("ALERT_URL", address + "/secret-endpoint")
    with acting_as(SYSTEM_ACTOR):
        with ctx.engine.begin() as conn:
            record_pause(conn, alerts[1], "operator", "investigate failure")
        (run,) = admit_pending(ctx)
        assert received == []
        outcome = run_pipeline(
            ctx.engine, ctx.config, "ALERT_SOURCE", selector=RunSelector(run_id=run)
        )
        assert outcome.status == RunStatus.SUCCESS, outcome.message
        assert len(received) == 1
        path, body, headers = received[0]
        assert path == "/secret-endpoint"
        expected = hmac.new(
            ("private-signing-key-" + "x" * 32).encode(),
            headers["X-Etl-Craft-Timestamp"].encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        assert headers["X-Etl-Craft-Signature"] == "v1=" + expected
        assert json.loads(body)["run"]["id"] == source
        with ctx.engine.connect() as conn:
            tasks = (
                conn.execute(
                    text("SELECT TASK_ID AS task FROM AUD_TASK_RUN_LOG WHERE PIPELINE_RUN_ID=:run"),
                    {"run": run},
                )
                .scalars()
                .all()
            )
            assert tasks == [task]
            assert (
                conn.execute(
                    text("SELECT STATUS FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID=:source"),
                    {"source": source},
                ).scalar_one()
                == RunStatus.FAILED
            )
        assert admit_pending(ctx) == ()


@pytest.mark.parametrize(
    "name,value",
    [
        ("ALERT_URL", "http://receiver.invalid/private-value"),
        ("ALERT_URL", "https://receiver.invalid:not-a-port/private-value"),
        ("ALERT_KEY", "tiny-private-value"),
        ("ALERT_KEY", "\udcff" * 32),
    ],
)
def test_bad_channel_secret_values_refuse_without_echoing_them(alerts, monkeypatch, name, value):
    from etl_craft.core.errors import ConfigurationError
    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _, task = failed_source(alerts)
    monkeypatch.setenv(name, value)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    with pytest.raises(ConfigurationError) as caught:
        alert_delivery.deliver(ctx, context)
    message = str(caught.value)
    assert "channel ops" in message and name in message and "expected" in message
    assert value not in message


def test_retention_keeps_admission_receipt_until_source_history_is_removed(alerts):
    from etl_craft.core.actor import purpose
    from etl_craft.core.alerts import AlertStatus
    from etl_craft.engine.alert_deliveries import DeliveryAttempt, append, event
    from etl_craft.engine.queries import statement
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, source, _ = failed_source(alerts)
    cutoff = datetime.now(UTC) + timedelta(days=1)
    token = purpose.set("retention")
    try:
        with acting_as(SYSTEM_ACTOR):
            (run,) = admit_pending(ctx)
            params = {"project_id": 1, "cutoff": cutoff}
            with ctx.engine.begin() as conn:
                conn.execute(statement(conn, "retention_aud_pipelines_run_log"), params)
                assert (
                    conn.execute(
                        text(
                            "SELECT PIPELINE_RUN_ID AS run_id FROM AUD_PIPELINES_RUN_LOG "
                            "WHERE PIPELINE_RUN_ID=:run"
                        ),
                        {"run": source},
                    ).scalar_one()
                    == source
                )
                transitions.finalize_pipeline_run(conn, run, RunStatus.FAILED)
                append(
                    conn,
                    run,
                    event(conn, run),
                    AlertStatus.FAILED,
                    DeliveryAttempt(status_code=503),
                )
            with ctx.engine.begin() as conn:
                conn.execute(statement(conn, "retention_aud_alert_deliveries"), params)
            assert admit_pending(ctx) == ()
            with ctx.engine.begin() as conn:
                remaining = (
                    conn.execute(text("SELECT STATUS AS status FROM AUD_ALERT_DELIVERIES"))
                    .scalars()
                    .all()
                )
                assert remaining == [AlertStatus.ADMITTED]
                conn.execute(statement(conn, "retention_aud_pipelines_run_log"), params)
                assert (
                    conn.execute(
                        text(
                            "SELECT COUNT(*) AS count FROM AUD_PIPELINES_RUN_LOG "
                            "WHERE PIPELINE_RUN_ID=:id"
                        ),
                        {"id": source},
                    ).scalar_one()
                    == 0
                )
                conn.execute(statement(conn, "retention_aud_alert_deliveries"), params)
                assert (
                    conn.execute(
                        text("SELECT COUNT(*) AS count FROM AUD_ALERT_DELIVERIES")
                    ).scalar_one()
                    == 0
                )
    finally:
        purpose.reset(token)


def test_local_channel_delivery_never_reads_task_secret_declaration(alerts, monkeypatch, caplog):
    from etl_craft.execution.secret_pipe import task_values
    from etl_craft.handlers import task_secrets
    from etl_craft.services.operations import alert_delivery
    from etl_craft.services.operations.alert_admission import admit_pending

    ctx, _source, task = failed_source(alerts)
    with acting_as(SYSTEM_ACTOR):
        (run,) = admit_pending(ctx)
        context = task_for(ctx, run, task)
    assert "SECRETS" not in context.task_params

    def refuse_declaration(*args):
        pytest.fail("a channel alert must not read a task SECRETS declaration")

    monkeypatch.setattr(task_secrets, "declared", refuse_declaration)
    values = task_values(ctx.engine, ctx.config, context.task_run_id)
    assert set(values) == {"ALERT_URL", "ALERT_KEY"}
    monkeypatch.setattr(alert_delivery, "post", lambda *args: (204, None))
    result = alert_delivery.deliver(ctx, replace(context, _secret_values=values))
    assert result.variables["ALERT_SENT"] is True
    with ctx.engine.connect() as conn:
        facts = str(conn.execute(text("SELECT * FROM AUD_ALERT_DELIVERIES")).all())
    for value in values.values():
        assert value not in facts and value not in caplog.text and value not in str(result)
