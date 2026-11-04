"""A missing required upload is a permanent audited failure with normal failure edges."""

from email import message_from_bytes, policy
from pathlib import Path

import yaml
from sqlalchemy import text

from fixtures.metadata import add_dependency, add_task


def test_missing_required_upload_is_recorded_once_and_sends_failure_alert(cli_project, tls_relay):
    p = cli_project
    relay = tls_relay()
    raw = yaml.safe_load(p.config.config_path.read_text())
    raw["Orchestration"]["Email"] = {
        "Host": relay.host,
        "Port": relay.port,
        "From_address": "etl@example.test",
        "Tls_mode": "STARTTLS",
        "Ca_file": str(relay.ca_file),
    }
    p.config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    folder = p.config.project_dir / "validation_scripts"
    folder.mkdir()
    (folder / "check.py").write_text(
        'def validate(task):\n    raise AssertionError("no file to validate")\n'
    )
    with p.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y' WHERE PIPELINE_ID=:id"),
            {"id": p.pipeline_id},
        )
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='FILE_VALIDATION' WHERE TASK_ID=:id"),
            {"id": p.task_id},
        )
        conn.execute(text("DELETE FROM CFG_TASK_PARAMETERS WHERE TASK_ID=:id"), {"id": p.task_id})
        for name, value in {
            "SCRIPT_FILE": "validation_scripts/check.py",
            "FILE_FORMAT": "CSV",
            "REQUIRE_UPLOADS": "Y",
            "RETRIES": "3",
            "RETRY_ON": "TRANSIENT",
        }.items():
            conn.execute(
                text(
                    "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                    "VALUES (:id,:name,:value)"
                ),
                {"id": p.task_id, "name": name, "value": value},
            )
        alert = add_task(
            conn,
            p.pipeline_id,
            "failure_alert",
            "EMAIL_ALERT",
            EMAIL_TO="ops@example.test",
            EMAIL_SUBJECT="Upload refused",
            EMAIL_BODY="$$error_message",
        )
        add_dependency(conn, p.pipeline_id, alert, p.task_id, "FAILURE")
    code, output = p.run("pipelines", "refresh")
    assert code == 0, output
    code, output = p.run("run", "--pipeline-code", "P", timeout=60)
    assert code != 0, output
    with p.engine.connect() as conn:
        attempts = (
            conn.execute(
                text(
                    "SELECT a.STATUS AS status,a.FAILURE_CLASS AS failure_class,"
                    "a.ERROR_MESSAGE AS error_message,a.LOG_PATH AS log_path "
                    "FROM AUD_TASK_ATTEMPTS a "
                    "JOIN AUD_TASK_RUN_LOG t ON t.TASK_RUN_ID=a.TASK_RUN_ID WHERE t.TASK_ID=:id"
                ),
                {"id": p.task_id},
            )
            .mappings()
            .all()
        )
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["failure_class"] == "PERMANENT"
    assert attempt["status"] == "FAILED"
    for part in [
        "P.load",
        "no uploaded files in this run",
        "REQUIRE_UPLOADS=Y",
        "start the run from an upload in the UI",
        "etl-craft upload",
    ]:
        assert part in attempt["error_message"]
        assert part in Path(attempt["log_path"]).read_text(encoding="utf-8")
    assert len(relay.messages) == 1
    message = message_from_bytes(relay.messages[0], policy=policy.default)
    body = message.get_body(preferencelist=("html", "plain")).get_content()
    assert "no uploaded files in this run" in body
