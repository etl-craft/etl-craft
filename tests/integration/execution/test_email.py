"""Alerts on EMAIL channels: an admitted event delivered through a relay and read back from it."""

import html
import json
import socket
import sys
import urllib.parse
import urllib.request
import uuid
from dataclasses import replace

import psycopg
import pytest
from sqlalchemy import text

from etl_craft.config import EmailProfile
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import ApiRole, RunStatus
from etl_craft.core.errors import ConfigurationError, HandlerError
from etl_craft.engine import transitions
from etl_craft.execution.connections import probe_email_relay
from etl_craft.execution.context import build_task_context
from etl_craft.services.operations import alert_delivery
from etl_craft.services.operations.alert_admission import admit_pending
from etl_craft.services.operations.context import OperationContext
from fixtures.metadata import add_pipeline, add_task, start_run, task_run
from fixtures.services import POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, require


def relay_config(config, host, port, **settings):
    profile = EmailProfile(
        "EMAIL", "dev", host, port, "etl@example.com", from_name="ETL Craft", **settings
    )
    return replace(config, email=profile)


@pytest.fixture
def mailpit(engine_db):
    smtp = require("mailpit_smtp")
    api = require("mailpit_api")

    def read(subject):
        query = urllib.parse.urlencode({"query": f'subject:"{subject}"'})
        with urllib.request.urlopen(f"{api.http_url}/api/v1/search?{query}", timeout=10) as reply:
            found = json.load(reply)["messages"]
        assert len(found) == 1, found
        with urllib.request.urlopen(
            f"{api.http_url}/api/v1/message/{found[0]['ID']}", timeout=10
        ) as reply:
            return json.load(reply)

    return relay_config(engine_db.config, smtp.host, smtp.port, tls_mode="NONE"), read


@pytest.fixture
def failed(engine_db, monkeypatch):
    """Pipeline P whose run failed at check, an EMAIL channel, and its admitted alert run."""
    monkeypatch.setattr(alert_delivery, "RETRY_DELAYS", (0, 0, 0))
    engine = engine_db.engine
    ids = {}
    with acting_as(SYSTEM_ACTOR), engine.begin() as conn:
        ids["P"] = add_pipeline(conn, "P")
        load = add_task(conn, ids["P"], "load")
        check = add_task(conn, ids["P"], "check")
        ids["alert"] = add_task(conn, ids["P"], "alert", "ALERT", ALERT_CHANNEL="mail")
        conn.execute(
            text(
                "INSERT INTO CFG_ALERT_CHANNELS(PROJECT_ID,CHANNEL_NAME,KIND,RECIPIENTS,"
                "DEFAULT_ALERT_ON) VALUES(1,'mail','EMAIL','ops@example.com|lead@example.com',"
                "'FAILURE')"
            )
        )
        ids["run"] = start_run(conn, ids["P"])
        task_run(conn, load, ids["run"], "SUCCESS")
        broken = task_run(conn, check, ids["run"], "IN-PROGRESS")
        transitions.finish_task_run(
            conn, broken, status="FAILED", error_message="3 rows had no key"
        )
        transitions.finalize_pipeline_run(conn, ids["run"], RunStatus.FAILED)
    ctx = OperationContext(
        engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN, project_id=1, project="default"
    )
    with acting_as(SYSTEM_ACTOR):
        (ids["alert_run"],) = admit_pending(ctx)
        with engine.begin() as conn:
            ids["task_run"] = transitions.find_or_create_task_run(
                conn, ids["alert"], ids["alert_run"]
            ).task_run_id
    return ctx, ids


def deliver(failed, config, **params):
    ctx, ids = failed
    context = build_task_context(ctx.engine, config, ids["task_run"])
    context = replace(context, config=config, task_params={"ALERT_CHANNEL": "mail", **params})
    with acting_as(SYSTEM_ACTOR):
        return alert_delivery.deliver(replace(ctx, config=config), context)


def recorded(ctx):
    with ctx.engine.connect() as conn:
        return [
            row.status
            for row in conn.execute(
                text("SELECT STATUS AS status FROM AUD_ALERT_DELIVERIES ORDER BY DELIVERY_ID")
            )
        ]


def test_an_alert_emails_the_channel_recipients_with_a_digest(mailpit, failed):
    config, read = mailpit
    ids = failed[1]
    tag = uuid.uuid4().hex[:8]
    result = deliver(
        failed,
        config,
        ALERT_SUBJECT=f"{tag} $$pipeline_code pipeline $$pipeline_id run $$pipeline_run_id "
        "task $$task_run_id: $$trigger $$status",
        ALERT_BODY="Failures: $$error_message",
        EMAIL_PIPELINES="P|NOPE",
    )
    assert result.variables == {"ALERT_SENT": True}
    subject = (
        f"[CUSTOM] {tag} P pipeline {ids['P']} run {ids['run']} task {ids['task_run']}: "
        "FAILURE FAILED"
    )
    message = read(subject)
    assert [to["Address"] for to in message["To"]] == ["ops@example.com", "lead@example.com"]
    assert (message["From"]["Name"], message["From"]["Address"]) == ("ETL Craft", "etl@example.com")
    body = message["HTML"]
    assert "✕ FAILED</h1>" in body and "Failures: 3 rows had no key" in body
    assert "channel mail" in body
    # The digest: P's latest run with its tasks, and a row for the unknown code.
    assert "P — " in body and "3 rows had no key</pre>" in body
    assert "NOPE — UNKNOWN</h2>" in body
    assert recorded(failed[0]) == ["ADMITTED", "STARTED", "SENT"]
    assert deliver(failed, config).variables == {"ALERT_SENT": True}
    assert recorded(failed[0]) == ["ADMITTED", "STARTED", "SENT"]


def test_a_multiline_database_error_is_safe_in_the_subject_and_kept_in_the_body(mailpit, failed):
    config, read = mailpit
    ctx, ids = failed
    pg = require("postgres")
    with (
        psycopg.connect(
            host=pg.host,
            port=pg.port,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        ) as conn,
        pytest.raises(psycopg.errors.InvalidTextRepresentation) as caught,
    ):
        conn.execute("SELECT CAST('bad' AS INTEGER)")
    error = str(caught.value)
    assert "\n" in error
    with ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE AUD_TASK_RUN_LOG SET ERROR_MESSAGE = :error WHERE PIPELINE_RUN_ID = :run"),
            {"error": error, "run": ids["run"]},
        )
    tag = uuid.uuid4().hex[:8]
    deliver(failed, config, ALERT_SUBJECT=f"{tag}: $$error_message", ALERT_BODY="$$error_message")
    message = read(tag)
    assert message["Subject"] == f"[CUSTOM] {tag}: " + " ".join(error.split())
    rendered = message["HTML"].replace("\r\n", "\n")
    assert (
        html.unescape(rendered.split("<pre", 1)[1].split(">", 1)[1].split("</pre>", 1)[0]) == error
    )
    assert "<br>" in rendered


@pytest.mark.parametrize(
    ("recipients", "outcome", "delivered"),
    [("bad@example.com|ops@example.com", "SENT", 1), ("bad@example.com", "FAILED", 0)],
)
def test_recipient_refusal_is_logged_and_a_total_refusal_retries_then_fails(
    failed, tls_relay, caplog, recipients, outcome, delivered
):
    relay = tls_relay(refused={"bad@example.com"})
    ctx, _ = failed
    with ctx.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_ALERT_CHANNELS SET RECIPIENTS=:r"), {"r": recipients})
    config = relay_config(
        ctx.config, relay.host, relay.port, tls_mode="STARTTLS", ca_file=relay.ca_file
    )
    if outcome == "SENT":
        assert deliver(failed, config).variables == {"ALERT_SENT": True}
        assert "bad@example.com (550: no such recipient)" in caplog.text
    else:
        with pytest.raises(HandlerError, match="channel mail: delivery failed; expected a relay"):
            deliver(failed, config)
        assert "SMTPRecipientsRefused" in caplog.text
    assert recorded(ctx)[-1] == outcome
    assert len(relay.messages) == delivered


def test_an_unknown_token_or_a_missing_relay_fails_before_any_attempt(failed):
    ctx, _ = failed
    with pytest.raises(HandlerError, match=r"ALERT_SUBJECT uses unknown token\(s\) \$\$when"):
        deliver(failed, ctx.config, ALERT_SUBJECT="$$when")
    with pytest.raises(ConfigurationError, match=r"kind=EMAIL, but craft-connector\.yml has no"):
        deliver(failed, replace(ctx.config, email=None))
    assert recorded(ctx) == ["ADMITTED"]


def test_a_relay_that_cannot_be_reached_is_named(failed, caplog):
    ctx, _ = failed
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = relay_config(ctx.config, "127.0.0.1", port, tls_mode="NONE")
    with pytest.raises(HandlerError, match="channel mail: delivery failed"):
        deliver(failed, config)
    assert f"the relay 127.0.0.1:{port} failed at connect" in caplog.text
    assert recorded(ctx).count("RETRY") == 3 and recorded(ctx)[-1] == "FAILED"


FAKE_SENDMAIL = """#!{python}
import sys
open({out!r}, "w").write(" ".join(sys.argv[1:]) + "\\n" + sys.stdin.read())
sys.exit({code})
"""


def sendmail_config(config, tmp_path, code=0):
    program = tmp_path / "sendmail"
    out = tmp_path / "sent.eml"
    program.write_text(FAKE_SENDMAIL.format(python=sys.executable, out=str(out), code=code))
    program.chmod(0o755)
    profile = EmailProfile(
        "EMAIL",
        "dev",
        "",
        0,
        "etl@example.com",
        transport="SENDMAIL",
        sendmail_path=str(program),
        from_name="ETL Craft",
    )
    return replace(config, email=profile), out


def test_an_alert_through_sendmail(failed, tmp_path):
    config, out = sendmail_config(failed[0].config, tmp_path)
    deliver(failed, config, ALERT_SUBJECT="$$trigger")
    sent = out.read_text()
    # Recipients come from the headers (-t); the sender is the profile's from_address (-f).
    assert sent.startswith("-t -oi -f etl@example.com -F ETL Craft\n")
    assert "From: ETL Craft <etl@example.com>" in sent
    assert "To: ops@example.com, lead@example.com" in sent
    assert "Subject: [CUSTOM] FAILURE" in sent
    assert probe_email_relay(config) is None


def test_a_failing_or_missing_sendmail_is_named(failed, tmp_path, caplog):
    config, _ = sendmail_config(failed[0].config, tmp_path, code=75)
    with pytest.raises(HandlerError, match="channel mail: delivery failed"):
        deliver(failed, config)
    assert "sendmail exited 75" in caplog.text
    gone = replace(
        config, email=replace(config.email, sendmail_path=str(tmp_path / "no_such_sendmail"))
    )
    assert "does not exist; install one, or set sendmail_path" in probe_email_relay(gone)
