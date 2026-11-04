"""Real agents execute project files through HTTP without Engine DB credentials."""

import json
import signal
import threading
import time

import pytest
from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from fixtures.cluster import publish_project

pytestmark = pytest.mark.parametrize(
    "empty_engine_db",
    [pytest.param("postgresql", marks=pytest.mark.engine_postgres)],
    indirect=True,
)


@pytest.mark.parametrize("fan_out", [False, True], ids=["plain", "fan-out"])
def test_agent_runs_its_pinned_bundle_without_engine_or_store_credentials(
    cluster, monkeypatch, fan_out
):
    p, url, token, agent_dir = cluster
    if fan_out:
        (agent_dir / "python_scripts" / "load.py").write_text(
            "from etl_craft.scripting import ScriptResult\n"
            "def run(task):\n"
            "    print('project copy ran')\n"
            "    return task.fan_out(['first','second'], "
            "lambda key: ScriptResult(4 if key == 'first' else 3), max_items=2)\n"
        )
    publish_project(p, agent_dir)
    controller = p.start("controller", "--no-ui")
    code, output = p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", "agent-test")
    assert code == 0, output
    p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="QUEUED")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    try:
        p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="SUCCESS", timeout=20)
        with p.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT OWNER_ID AS owner_id, TARGET_COUNT AS target_count "
                    "FROM AUD_TASK_ATTEMPTS"
                )
            ).one()
            logs = conn.execute(text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS")).all()
        if fan_out:
            with p.engine.connect() as conn:
                items = conn.execute(
                    text(
                        "SELECT ITEM_KEY AS key, ROW_COUNT AS rows FROM AUD_TASK_ITEMS "
                        "WHERE STATUS='SUCCESS' ORDER BY ITEM_KEY"
                    )
                ).all()
                assert [(r.key, r.rows) for r in items] == [("first", 4), ("second", 3)]
        assert row.owner_id == str(token.metadata.token_id)
        assert row.target_count == 7
        code, output = p.run("agent", "health", "--project-dir", str(agent_dir))
        assert code == 0, output
        assert "project copy ran" in "".join(r.content for r in logs)
        agent.signal(signal.SIGTERM)
        assert agent.wait(timeout=40) == 0, agent.output
        p.wait_for("SELECT STATUS FROM AUD_AGENTS", expected="GONE")
    except AssertionError as error:
        raise AssertionError(
            f"{error}\nagent:\n{agent.output}\ncontroller:\n{controller.output}"
        ) from error


@pytest.mark.chaos
@pytest.mark.parametrize("failure", ["agent-killed", "api-cut-off"])
def test_a_lost_agent_stops_its_writer_before_a_second_holder(cluster, monkeypatch, failure):
    from datetime import UTC, datetime, timedelta

    from etl_craft.core.actor import acting_as
    from etl_craft.execution.leases import process_start
    from etl_craft.execution.reconcile import reconcile
    from etl_craft.handlers.resources import LocalLocker
    from etl_craft.warehouse.connection import open_warehouse

    p, url, token, agent_dir = cluster
    (agent_dir / "python_scripts" / "load.py").write_text(
        "import threading\n"
        "from sqlalchemy import text\n"
        "def run(task):\n"
        "    with task.warehouse() as engine:\n"
        "        with engine.begin() as conn:\n"
        '            conn.execute(text("CREATE TABLE evidence (id INTEGER)"))\n'
        f'        __import__("pathlib").Path({str(agent_dir / "writing")!r}).touch()\n'
        "        counter = 0\n"
        "        while True:\n"
        "            with engine.begin() as conn:\n"
        '                conn.execute(text("INSERT INTO evidence VALUES (:id)"), {"id": counter})\n'
        "            counter += 1\n"
        "            threading.Event().wait(.02)\n"
    )
    publish_project(p, agent_dir)
    p.start("controller", "--no-ui")
    code, output = p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", failure)
    assert code == 0, output
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    deadline = time.monotonic() + 20
    while not (agent_dir / "writing").exists():
        assert time.monotonic() < deadline, agent.output
        assert agent.process.poll() is None, agent.output
        threading.Event().wait(0.02)
    with p.engine.connect() as conn:
        attempt = conn.execute(
            text(
                "SELECT ATTEMPT_ID AS attempt_id, PID AS pid, PROCESS_START AS birth, "
                "LEASE_EXPIRES_AT AS lease FROM AUD_TASK_ATTEMPTS"
            )
        ).one()
    if failure == "agent-killed":
        agent.signal(signal.SIGKILL)
        agent.wait()
    else:
        ui = next(command for command in p.processes if "ui" in command.process.args)
        ui.signal(signal.SIGKILL)
        ui.wait()
    deadline = time.monotonic() + (5 if failure == "agent-killed" else 55)
    while process_start(attempt.pid) == attempt.birth:
        assert time.monotonic() < deadline, agent.output
        threading.Event().wait(0.02)
    # The old writer must end while its reservation still excludes a successor.
    assert datetime.now(UTC) < attempt.lease
    with p.engine.begin() as conn:
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET LEASE_EXPIRES_AT=:past WHERE ATTEMPT_ID=:id"),
            {"past": datetime.now(UTC) - timedelta(seconds=1), "id": attempt.attempt_id},
        )
    with acting_as(SYSTEM_ACTOR):
        reconcile(p.engine)
        config = load_config(agent_dir / "craft-connector.yml", agent=True)
        with (
            open_warehouse(config, LocalLocker(p.engine, p.config)) as warehouse,
            warehouse.begin() as conn,
        ):
            before = conn.execute(text("SELECT COUNT(*) AS n FROM evidence")).scalar_one()
            conn.execute(text("INSERT INTO evidence VALUES (-1)"))
            assert (
                conn.execute(text("SELECT COUNT(*) AS n FROM evidence")).scalar_one() == before + 1
            )
    with p.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT STATUS AS status FROM AUD_TASK_ATTEMPTS WHERE ATTEMPT_ID=:id"),
                {"id": attempt.attempt_id},
            ).scalar_one()
            == "LOST"
        )


@pytest.mark.parametrize("lost_notification", [False, True])
def test_agent_cancel_is_acknowledged_by_notification_or_renewal(
    cluster, monkeypatch, lost_notification
):
    from etl_craft.core.enums import ControlAction
    from etl_craft.engine import resource_locks
    from etl_craft.services.operations.requests import ControlRequest
    from fixtures.cancellation import wait_for

    p, url, token, agent_dir = cluster
    (agent_dir / "python_scripts" / "load.py").write_text(
        "import threading\n"
        "def run(task):\n"
        f"    __import__('pathlib').Path({str(agent_dir / 'ready')!r}).touch()\n"
        "    threading.Event().wait(120)\n",
        encoding="utf-8",
    )
    publish_project(p, agent_dir)
    controller = p.start("controller", "--no-ui")
    code, output = p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", "cancel")
    assert code == 0, output
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    wait_for(lambda: (agent_dir / "ready").exists())
    if lost_notification:
        monkeypatch.setattr(resource_locks, "notify", lambda *args: None)
    ctx = OperationContext(p.engine, p.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    started = time.monotonic()
    pending = invoke(
        ctx,
        ActionName.CONTROL,
        ControlRequest(
            pipeline_code="P", action=ControlAction.ABORT, reason="cancel an agent attempt"
        ),
    )
    try:
        p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="CANCELLED", timeout=15)
        p.wait_for(
            "SELECT STATUS FROM AUD_CONTROL_REQUESTS WHERE CONTROL_ID=" + str(pending.control_id),
            expected="COMPLETED",
            timeout=5,
        )
        assert time.monotonic() - started < (14 if lost_notification else 6)
        with p.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT CANCEL_REQUESTED_AT AS requested, "
                    "CANCEL_ACKNOWLEDGED_AT AS acknowledged "
                    "FROM AUD_TASK_ATTEMPTS"
                )
            ).one()
        assert row.requested is not None and row.acknowledged is not None
    except AssertionError as error:
        raise AssertionError(
            f"{error}\nagent:\n{agent.output}\ncontroller:\n{controller.output}"
        ) from error


def test_api_publication_needs_only_project_files_and_a_person_token(cluster, monkeypatch):
    from fixtures.engine_db import SECRET_VAR

    project, url, _, _ = cluster
    with monkeypatch.context() as isolated:
        isolated.delenv(SECRET_VAR)
        code, output = project.run("bundle", "publish", "--api", url, "--format", "json")
    assert code == 0, output
    with project.engine.connect() as conn:
        bundle = conn.execute(
            text("SELECT BUNDLE_ID AS bundle_id FROM AUD_PROJECT_BUNDLES WHERE BUNDLE_ID=:id"),
            {"id": json.loads(output)["bundle_id"]},
        ).scalar_one()
    assert bundle in output


@pytest.mark.chaos
def test_agent_killed_after_upload_leaves_chunks_for_a_restarted_controller(cluster, monkeypatch):
    import os
    from datetime import UTC, datetime, timedelta

    from etl_craft.core.actor import acting_as
    from etl_craft.execution.reconcile import reconcile
    from etl_craft.services.operations.requests import LogInput

    p, url, token, agent_dir = cluster
    controller_token = os.environ["ETL_CRAFT_TOKEN"]
    publish_project(p, agent_dir)
    controller = p.start("controller", "--no-ui")
    code, output = p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", "log-loss")
    assert code == 0, output
    p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="QUEUED")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start(
        "agent", "--api", url, "--project-dir", str(agent_dir), fault="agent.after_log_upload:kill"
    )
    assert agent.wait(timeout=20) == 137, agent.output
    controller.signal(signal.SIGKILL)
    assert controller.wait(timeout=20) == -signal.SIGKILL, controller.output
    with acting_as(SYSTEM_ACTOR), p.engine.begin() as conn:
        before = conn.execute(
            text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS ORDER BY SEQUENCE_NUMBER")
        ).all()
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET LEASE_EXPIRES_AT=:past"),
            {"past": datetime.now(UTC) - timedelta(seconds=1)},
        )
    assert before
    reconcile(p.engine)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", controller_token)
    restarted = p.start("controller", "--no-ui")
    p.wait_for(
        "SELECT COUNT(*) FROM AUD_TASK_ATTEMPTS WHERE LOG_PATH IS NOT NULL", expected=1, timeout=20
    )
    with p.engine.connect() as conn:
        row = conn.execute(
            text("SELECT ATTEMPT_ID AS attempt_id, STATUS AS status FROM AUD_TASK_ATTEMPTS")
        ).one()
    assert row.status == "LOST"
    ctx = OperationContext(p.engine, p.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    assert (
        b"".join(invoke(ctx, ActionName.LOGS, LogInput(attempt_id=row.attempt_id)))
        == "".join(r.content for r in before).encode()
    )
    restarted.signal(signal.SIGTERM)
    assert restarted.wait(timeout=20) == 0, restarted.output


def test_children_never_receive_agent_token(cluster, monkeypatch):
    import yaml

    from fixtures.cluster import start_ui

    p, url, token, agent_dir = cluster
    bootstrap = agent_dir / "craft-connector.yml"
    raw = yaml.safe_load(bootstrap.read_text())
    raw["Orchestration"]["Email"] = {
        "Host": "localhost",
        "Port": 1025,
        "From_address": "demo@example.test",
        "Auth_mode": "PASSWORD",
        "User": "demo",
        "Secret": "PINNED_EMAIL_PASSWORD",
    }
    raw["Privacy"] = {"Hmac_secret": "PINNED_PRIVACY_SECRET"}
    bootstrap.write_text(yaml.safe_dump(raw, sort_keys=False))
    monkeypatch.setenv("PINNED_PRIVACY_SECRET", "pinned-host-only")
    monkeypatch.setenv("CURRENT_PRIVACY_SECRET", "current-host-only")
    monkeypatch.setenv("PINNED_EMAIL_PASSWORD", "pinned-example-only")
    monkeypatch.setenv("CURRENT_EMAIL_PASSWORD", "current-example-only")
    _, url = start_ui(p)
    (agent_dir / "python_scripts" / "load.py").write_text(
        "import os, sys, json\n"
        "from pathlib import Path\n"
        "from urllib.request import Request, urlopen\n"
        "from urllib.error import HTTPError\n"
        "from etl_craft import __version__\n"
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    assert 'ETL_CRAFT_TOKEN' not in os.environ\n"
        "    assert 'PINNED_PRIVACY_SECRET' not in os.environ\n"
        "    assert 'CURRENT_PRIVACY_SECRET' not in os.environ\n"
        "    assert 'ETL_CRAFT_REFRESH_TOKEN' not in os.environ\n"
        "    assert os.environ['PINNED_EMAIL_PASSWORD'] == 'pinned-example-only'\n"
        "    work = json.loads(Path(sys.argv[sys.argv.index('--work-file')+1]).read_text())\n"
        "    attempt = work['task']['attempt_id']\n"
        "    api = sys.argv[sys.argv.index('--api')+1]\n"
        "    request = Request(api+'/api/v1/agent/log', method='POST',\n"
        "        headers={'Authorization':'Bearer '+work['credential'], 'C"
        "ontent-Type':'application/json'},\n"
        "        data=json.dumps({'version':__version__,'attempt_id':attem"
        "pt+1,'sequence':0,'content':'foreign'}).encode())\n"
        "    try:\n"
        "        urlopen(request, timeout=5)\n"
        "    except HTTPError as error:\n"
        "        assert error.code == 403\n"
        "    else:\n"
        "        raise AssertionError('foreign attempt accepted')\n"
        "    print('attempt boundary checked')\n"
        "    return ScriptResult(7)\n"
    )
    publish_project(p, agent_dir)
    raw["Orchestration"]["Email"]["Secret"] = "CURRENT_EMAIL_PASSWORD"
    raw["Privacy"]["Hmac_secret"] = "CURRENT_PRIVACY_SECRET"
    bootstrap.write_text(yaml.safe_dump(raw, sort_keys=False))
    controller = p.start("controller", "--no-ui")
    code, output = p.run(
        "run", "--pipeline-code", "P", "--init-only", "--run-key", "credential-test"
    )
    assert code == 0, output
    p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="QUEUED")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    monkeypatch.setenv("ETL_CRAFT_REFRESH_TOKEN", "must-not-reach-the-task")
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    try:
        p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected="SUCCESS", timeout=25)
    except AssertionError as error:
        with p.engine.connect() as conn:
            messages = conn.execute(
                text("SELECT ERROR_MESSAGE AS message FROM AUD_TASK_RUN_LOG")
            ).all()
            chunks = conn.execute(
                text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS")
            ).all()
        raise AssertionError(
            f"{error}\n{messages}\n{chunks}\n{agent.output}\n{controller.output}"
        ) from error
    finally:
        agent.signal(signal.SIGTERM)
        agent.wait(timeout=40)


def test_api_only_agent_runs_upload_validation_and_load(cluster, monkeypatch):
    from etl_craft.core.actor import Actor, acting_as
    from etl_craft.core.enums import ActorKind
    from etl_craft.services.operations.uploads import UploadRequest, receive
    from fixtures.metadata import add_dependency, add_task

    p, url, token, agent_dir = cluster
    (agent_dir / "validation_scripts").mkdir()
    (agent_dir / "validation_scripts/check.py").write_text(
        "def validate(task):\n"
        "    rows = list(task.reader.rows())\n"
        "    assert rows == [('id', 'name'), ('1', 'accepted')]\n"
    )
    (agent_dir / "python_scripts/load.py").write_text(
        "from sqlalchemy import text\n"
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    with task.warehouse() as engine, engine.begin() as conn:\n"
        "        conn.execute(text('CREATE TABLE uploaded "
        "(id INTEGER,UPLOAD_ID BIGINT,CREATED_BY VARCHAR,UPDATED_BY VARCHAR)'))\n"
        "        for upload in task.uploads:\n"
        "            assert upload.path.read_bytes() == b'id|name\\n1|accepted\\n'\n"
        "            conn.execute(text('INSERT INTO uploaded VALUES "
        "(1,:id,:account,:account)'), {'id': upload.upload_id,'account': upload.account})\n"
        "    return ScriptResult(1)\n"
    )
    ctx = OperationContext(p.engine, p.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    from fixtures.actions import act

    act(ctx, ActionName.ACCOUNT_ADD, name="steward", role=ApiRole.ADMIN, oidc_subject="steward")
    with p.engine.begin() as conn:
        pipeline = conn.execute(text("SELECT PIPELINE_ID AS id FROM CFG_PIPELINES")).scalar_one()
        load = conn.execute(text("SELECT TASK_ID AS id FROM CFG_TASKS")).scalar_one()
        validation = add_task(
            conn,
            pipeline,
            "check",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
        )
        add_dependency(conn, pipeline, load, validation, "HAS_DATA")
        conn.execute(text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y'"))
    publish_project(p, agent_dir)
    ctx = OperationContext(
        p.engine,
        p.config,
        Actor("steward", ActorKind.USER),
        role=ApiRole.ADMIN,
        project="default",
        project_id=1,
    )
    with receive(ctx, UploadRequest(pipeline_code="P")) as receipt:
        receipt.begin_file("data.csv", "text/csv")
        receipt.write(b"id|name\n1|accepted\n")
    controller = p.start("controller", "--no-ui")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    try:
        p.wait_for("SELECT STATUS FROM AUD_PIPELINES_RUN_LOG", expected="SUCCESS", timeout=40)
        with acting_as(SYSTEM_ACTOR), p.engine.connect() as conn:
            row = conn.execute(
                text("SELECT STATUS AS status,ACCOUNT AS account FROM AUD_UPLOADS")
            ).one()
        assert row.status == "LOADED" and row.account == "steward"
        from etl_craft.warehouse.connection import open_warehouse

        with open_warehouse(p.config) as warehouse, warehouse.connect() as conn:
            row = conn.execute(
                text("SELECT CREATED_BY AS creator,UPDATED_BY AS writer FROM uploaded")
            ).one()
        assert row.creator == row.writer == "steward"
    except AssertionError as error:
        with p.engine.connect() as conn:
            failures = (
                conn.execute(text("SELECT ERROR_MESSAGE AS error FROM AUD_TASK_ATTEMPTS"))
                .scalars()
                .all()
            )
            logs = (
                conn.execute(text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS"))
                .scalars()
                .all()
            )
        raise AssertionError(
            f"{error}\nfailures:{failures}\nlogs:{logs}\nagent:\n{agent.output}"
            f"\ncontroller:\n{controller.output}"
        ) from error
    finally:
        agent.signal(signal.SIGTERM)
        agent.wait(timeout=40)


@pytest.mark.parametrize("killed", [False, True], ids=["empty", "sigkill"])
def test_explicit_small_python_agent_records_success_or_memory_failure(
    cluster, monkeypatch, killed
):
    from etl_craft.core.enums import AttemptStatus, FailureClass
    from etl_craft.core.resources import MIB, discover

    p, url, token, folder = cluster
    memory_mb = 1024 if killed else 256
    physical_mb = (discover().memory.value or 0) / MIB
    body = (
        "    import os, signal\n    os.kill(os.getpid(), signal.SIGKILL)\n"
        if killed
        else "    return ScriptResult(0)\n"
    )
    (folder / "python_scripts" / "load.py").write_text(
        "from etl_craft.scripting import ScriptResult\ndef run(task):\n" + body
    )
    with p.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "VALUES (:task,'MEMORY_REQUEST_MB',:memory)"
            ),
            {"task": p.task_id, "memory": "128"},
        )
    publish_project(p, folder)
    p.start("controller", "--no-ui")
    assert p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", "small-agent")[0] == 0
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start(
        "agent",
        "--api",
        url,
        "--project-dir",
        str(folder),
        "--cpu",
        "2",
        "--memory-mb",
        str(memory_mb),
        "--python-slots",
        "1",
        "--warehouse-slots",
        "0",
        "--drain-seconds",
        "0",
    )
    try:
        status = AttemptStatus.FAILED if killed else AttemptStatus.SUCCESS
        p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected=status, timeout=30)
        assert "set explicitly to 1" in agent.output
        assert f"estimate allowed {int(killed)}" in agent.output
        if killed:
            with p.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT ERROR_MESSAGE AS message, FAILURE_CLASS AS failure "
                        "FROM AUD_TASK_ATTEMPTS"
                    )
                ).one()
                logs = conn.execute(
                    text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS")
                ).all()
                host = conn.execute(text("SELECT HOST AS host FROM AUD_AGENTS")).scalar_one()
            assert row.failure == FailureClass.PERMANENT
            for part in (
                host,
                "SIGKILL",
                f"container memory limit {physical_mb:.0f} MB",
                "--python-slots=1",
                "lower",
                "explicitly recovering",
            ):
                assert part in row.message
                assert part in "".join(chunk.content for chunk in logs)
        agent.signal(signal.SIGTERM)
        assert agent.wait(timeout=30) == 0, agent.output
    except AssertionError as error:
        raise AssertionError(f"{error}\nagent:\n{agent.output}") from error


@pytest.fixture(params=["ENVIRONMENT", "FILE"])
def secret_cluster(empty_engine_db, cli_project, monkeypatch, request):
    import os

    import yaml

    monkeypatch.setenv("SOURCE_TOKEN", "task-private-test-value")
    p = cli_project
    if request.param == "FILE":
        path = p.config.project_dir / "provider.env"
        path.write_text(
            "SOURCE_TOKEN=task-private-test-value\n"
            + p.config.engine.secret_var
            + "="
            + os.environ[p.config.engine.secret_var]
            + "\n"
        )
        raw = yaml.safe_load(p.config.config_path.read_text())
        raw["Secrets"] = {"Source_type": "FILE", "Path": str(path)}
        p.config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
        p.config = load_config(p.config.config_path)
    cluster = request.getfixturevalue("cluster")
    agent_dir = cluster[3]
    path = agent_dir / "craft-connector.yml"
    raw = yaml.safe_load(path.read_text())
    raw["Secrets"] = {"Source_type": "ENVIRONMENT"}
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return cluster


@pytest.mark.parametrize("fails", [False, True])
def test_agent_receives_secrets_by_pipe_and_masks_all_output(secret_cluster, monkeypatch, fails):
    p, url, token, agent_dir = secret_cluster
    path = agent_dir / "python_scripts/load.py"
    path.write_text(
        "import os\nfrom etl_craft.scripting import ScriptResult, PermanentError\n"
        "def run(task):\n"
        "    assert 'SOURCE_TOKEN' not in os.environ\n"
        "    value = task.secret('SOURCE_TOKEN')\n"
        "    print(value)\n"
        "    task.logger.warning('echo %s', value)\n"
        + (
            "    raise PermanentError(value)\n"
            if fails
            else "    return ScriptResult(1, variables={'echo': value, value: 'opaque'})\n"
        )
    )
    with p.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                "VALUES (:id,'SECRETS','SOURCE_TOKEN')"
            ),
            {"id": p.task_id},
        )
    publish_project(p, agent_dir)
    controller = p.start("controller", "--no-ui")
    code, output = p.run("run", "--pipeline-code", "P", "--init-only", "--run-key", "secret-test")
    assert code == 0, output
    monkeypatch.delenv("SOURCE_TOKEN")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    try:
        p.wait_for(
            "SELECT STATUS FROM AUD_TASK_ATTEMPTS",
            expected="FAILED" if fails else "SUCCESS",
            timeout=40,
        )
        with p.engine.connect() as conn:
            attempt = conn.execute(
                text("SELECT ERROR_MESSAGE AS error,TASK_LOG AS log FROM AUD_TASK_ATTEMPTS")
            ).one()
            chunks = conn.execute(
                text("SELECT CONTENT AS content FROM AUD_ATTEMPT_LOG_CHUNKS")
            ).all()
        assert "task-private-test-value" not in str(attempt)
        assert "task-private-test-value" not in "".join(row.content for row in chunks)
        assert "[REDACTED]" in "".join(row.content for row in chunks)
        assert "task-private-test-value" not in agent.output
        for path in agent_dir.rglob("*"):
            if path.is_file():
                assert b"task-private-test-value" not in path.read_bytes()
    finally:
        agent.close()
        controller.close()


@pytest.mark.chaos
@pytest.mark.parametrize("outcome", ["FAILED", "TIMED_OUT"])
def test_agent_terminal_exit_records_real_evidence(cluster, monkeypatch, outcome):
    p, url, token, agent_dir = cluster
    script = (
        "from etl_craft.scripting import PermanentError\n"
        "def run(task):\n    raise PermanentError('deliberate failed writer')\n"
        if outcome == "FAILED"
        else "import threading\ndef run(task):\n    threading.Event().wait(120)\n"
    )
    (agent_dir / "python_scripts/load.py").write_text(script)
    with p.engine.begin() as conn:
        for name, value in (
            ("RETRY_ON", "NONE"),
            ("TASK_TIMEOUT_SECONDS", "3" if outcome == "TIMED_OUT" else "30"),
        ):
            conn.execute(
                text(
                    "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID,PARAMETER_NAME,PARAMETER_VALUE) "
                    "VALUES (:task,:name,:value)"
                ),
                {"task": p.task_id, "name": name, "value": value},
            )
    publish_project(p, agent_dir)
    controller = p.start("controller", "--no-ui")
    code, output = p.run(
        "run", "--pipeline-code", "P", "--init-only", "--run-key", "ending-evidence"
    )
    assert code == 0, output
    monkeypatch.setenv("ETL_CRAFT_TOKEN", token.token)
    agent = p.start("agent", "--api", url, "--project-dir", str(agent_dir), "--drain-seconds", "0")
    p.wait_for("SELECT STATUS FROM AUD_TASK_ATTEMPTS", expected=outcome, timeout=30)
    p.wait_for("SELECT count(*) FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS", expected=2, timeout=10)
    with p.engine.connect() as conn:
        evidence = (
            conn.execute(
                text(
                    "SELECT KIND AS kind,EVIDENCE_KIND AS evidence_kind "
                    "FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS"
                )
            )
            .mappings()
            .all()
        )
        attempt = conn.execute(
            text(
                "SELECT PID AS pid, PROCESS_START AS birth, AGENT_INSTANCE_ID AS instance "
                "FROM AUD_TASK_ATTEMPTS"
            )
        ).one()
        registered = conn.execute(
            text("SELECT INSTANCE_ID AS instance FROM AUD_AGENTS")
        ).scalar_one()
    assert {r["kind"] for r in evidence} == {"PROCESS", "QUERIES"}
    assert all(r["evidence_kind"] == "VERIFIED" for r in evidence)
    assert attempt.pid and attempt.birth and attempt.instance == registered
    agent.signal(signal.SIGTERM)
    assert agent.wait(timeout=40) == 0, agent.output + controller.output
