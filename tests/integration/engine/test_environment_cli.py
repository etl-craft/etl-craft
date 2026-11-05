"""Environment settings and empty-reason governance through the actual CLI parser."""

import csv

import pytest

from etl_craft.cli import main
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import ExitCode
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.metadata import add_pipeline

pytestmark = pytest.mark.usefixtures("cli_logging")


@pytest.mark.parametrize("policy", ("STRICT", "RELAXED"))
def test_cli_environment_governance_and_reason(metadata_project, monkeypatch, capsys, policy):
    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    assert (
        main(
            [
                "project",
                "set",
                "--project",
                "default",
                "--environment-type",
                "DEV",
                "--environment-name",
                "perf",
                "--governance",
                policy,
                "--reason",
                "test",
            ]
        )
        == ExitCode.SUCCESS
    )
    capsys.readouterr()
    with project.engine.begin() as conn:
        add_pipeline(conn, "P")
    result = main(["pause", "--pipeline-code", "P"])
    captured = capsys.readouterr()
    if policy == "RELAXED":
        assert result == ExitCode.SUCCESS, captured.err
    else:
        assert result == ExitCode.USAGE
        assert "default" in captured.err and "DEV" in captured.err and "--reason" in captured.err
    assert main(["project", "list", "--reason", "inspect", "--format", "json"]) == ExitCode.SUCCESS
    output = capsys.readouterr().out
    assert '"environment_type": "DEV"' in output and f'"governance": "{policy}"' in output


def test_config_csv_cannot_change_governance(metadata_project, monkeypatch, capsys):
    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    folder = project.root / "config"
    folder.mkdir(exist_ok=True)
    with (folder / "pipelines.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["PIPELINE_CODE", "GOVERNANCE"])
        writer.writerow(["P", "RELAXED"])
    assert main(["config", "plan"]) != ExitCode.SUCCESS
    error = capsys.readouterr().err
    assert "GOVERNANCE" in error and "unknown column" in error


@pytest.mark.parametrize("policy", ("STRICT", "RELAXED"))
@pytest.mark.parametrize("option", ("--recover", "--restart", "--allow-paused"))
def test_cli_omitted_recovery_reason_obeys_governance(
    metadata_project, monkeypatch, capsys, policy, option
):
    from sqlalchemy import text

    from etl_craft.core.enums import RunStatus
    from fixtures.metadata import add_task, finish_run, start_run, task_run

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(ctx, ActionName.PROJECT_SET, project="default", governance=policy, reason="policy")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    with project.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "T", "PYTHON", SCRIPT_FILE="python_scripts/test.py")
    (project.root / "python_scripts" / "test.py").write_text("def run(task):\n    return None\n")
    checked = act(ctx, ActionName.PIPELINE_REFRESH)
    assert not checked.failed, checked
    with project.engine.begin() as conn:
        run = start_run(conn, pipeline)
        task_run(conn, task, run, RunStatus.FAILED)
        if option != "--allow-paused":
            finish_run(conn, run, RunStatus.FAILED)
    if option == "--allow-paused":
        assert main(["pause", "--pipeline-code", "P", "--reason", "seed"]) == ExitCode.SUCCESS
        capsys.readouterr()
    result = main(["run", "--pipeline-code", "P", "--run-id", str(run), option])
    captured = capsys.readouterr()
    if policy == "RELAXED":
        assert result == ExitCode.SUCCESS, captured.err
        with project.engine.connect() as conn:
            reason = conn.execute(
                text(
                    "SELECT REASON AS reason FROM AUD_CONTROL_REQUESTS ORDER BY "
                    "CONTROL_ID DESC LIMIT 1"
                )
            ).scalar_one()
            assert reason == ""
    else:
        assert result == ExitCode.USAGE, captured.err
        assert "STRICT" in captured.err and "--reason" in captured.err


@pytest.mark.parametrize("policy", ("STRICT", "RELAXED"))
@pytest.mark.parametrize("verb", ("hold", "release", "stop", "abort"))
@pytest.mark.parametrize("interface", ("cli", "api"))
def test_control_reason_policy_has_the_same_cli_and_api_effect(
    metadata_project, monkeypatch, capsys, policy, verb, interface
):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from etl_craft.api.app import create_app
    from etl_craft.core.enums import ControlAction
    from etl_craft.services.operations.actions import ACTIONS, action_path
    from fixtures.metadata import add_task, start_run

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(ctx, ActionName.PROJECT_SET, project="default", governance=policy, reason="policy")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    with project.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(conn, pipeline, "T", "PYTHON")
        run = start_run(conn, pipeline)
    if verb == "release":
        act(
            ctx,
            ActionName.CONTROL,
            pipeline_code="P",
            run_id=run,
            action=ControlAction.HOLD,
            reason="seed",
        )
    with project.engine.connect() as conn:
        before = conn.execute(
            text("SELECT COUNT(*) AS count FROM AUD_CONTROL_REQUESTS")
        ).scalar_one()
    if interface == "cli":
        status = main([verb, "--pipeline-code", "P", "--run-id", str(run)])
        error = capsys.readouterr().err
        accepted = status == ExitCode.SUCCESS
    else:
        client = TestClient(create_app(ctx))
        path = action_path(ACTIONS[ActionName.CONTROL]).format(project="default")
        response = client.post(
            path,
            json={"pipeline_code": "P", "run_id": run, "action": verb.upper()},
            headers={"Authorization": "Bearer " + credential.token},
        )
        accepted = response.status_code == 200
        error = response.text
    if policy == "RELAXED":
        assert accepted, error
    else:
        assert not accepted and "STRICT" in error and "--reason" in error
    with project.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT REASON AS reason FROM AUD_CONTROL_REQUESTS ORDER BY CONTROL_ID")
        ).all()
        assert len(rows) == before + (policy == "RELAXED")
        if policy == "RELAXED":
            assert rows[-1].reason == ""


@pytest.mark.parametrize("policy", ("STRICT", "RELAXED"))
@pytest.mark.parametrize("kind", ("status", "offset"))
@pytest.mark.parametrize("interface", ("cli", "api"))
def test_mark_and_offset_reasons_share_governance(
    metadata_project, monkeypatch, capsys, policy, kind, interface
):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from etl_craft.api.app import create_app
    from etl_craft.engine.repository.offsets import StoredOffset, save_task_offset
    from etl_craft.services.operations.actions import ACTIONS, action_path
    from fixtures.metadata import add_task, start_run

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(ctx, ActionName.PROJECT_SET, project="default", governance=policy, reason="policy")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    with project.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = add_task(conn, pipeline, "T", "PYTHON")
        run = start_run(conn, pipeline)
        save_task_offset(conn, task, StoredOffset("NUMBER", "0"))
    options = (
        ["--status", "SUCCESS"] if kind == "status" else ["--task-code", "T", "--offset", "42"]
    )
    payload = {"status": "SUCCESS"} if kind == "status" else {"task_code": "T", "offset": "42"}
    if interface == "cli":
        accepted = (
            main(["mark", "--pipeline-code", "P", "--run-id", str(run), *options])
            == ExitCode.SUCCESS
        )
        error = capsys.readouterr().err
    else:
        client = TestClient(create_app(ctx))
        response = client.post(
            action_path(ACTIONS[ActionName.MARK]).format(project="default"),
            json={"pipeline_code": "P", "run_id": run, **payload},
            headers={"Authorization": "Bearer " + credential.token},
        )
        accepted, error = response.status_code == 200, response.text
    if policy == "RELAXED":
        assert accepted, error
    else:
        assert not accepted and "STRICT" in error and "--reason" in error
    with project.engine.connect() as conn:
        reasons = (
            conn.execute(text("SELECT REASON AS reason FROM AUD_RUN_INTERVENTIONS")).scalars().all()
        )
        assert reasons == ([""] if policy == "RELAXED" else [])


@pytest.mark.parametrize("policy", ("STRICT", "RELAXED"))
@pytest.mark.parametrize("kind", ("rerun", "ignore", "backfill"))
@pytest.mark.parametrize("interface", ("cli", "api"))
def test_run_override_reasons_share_governance(
    metadata_project, monkeypatch, capsys, policy, kind, interface
):
    from fastapi.testclient import TestClient

    from etl_craft.api.app import create_app
    from etl_craft.core.enums import RunStatus
    from etl_craft.services.operations.actions import ACTIONS, action_path
    from fixtures.metadata import add_task, finish_run, start_run, task_run

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(ctx, ActionName.PROJECT_SET, project="default", governance=policy, reason="policy")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    scripts = project.root / "python_scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "governance.py").write_text(
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n    return ScriptResult(row_count=1)\n"
    )
    with project.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        task = (
            add_task(
                conn,
                pipeline,
                "T",
                "SQL",
                SQL_ACTION="CREATE_TABLE",
                TARGET_OBJECT="main.governance_target",
                SELECT_QUERY="SELECT 1 AS id",
            )
            if kind == "ignore"
            else add_task(conn, pipeline, "T", "PYTHON", SCRIPT_FILE="python_scripts/governance.py")
        )
        run = start_run(conn, pipeline) if kind == "rerun" else None
        if run is not None:
            task_run(conn, task, run, RunStatus.SUCCESS)
            finish_run(conn, run, RunStatus.SUCCESS)
    checked = act(ctx, ActionName.PIPELINE_REFRESH)
    assert not checked.failed, checked
    if kind == "rerun":
        options = ["--task-code", "T", "--run-id", str(run), "--rerun"]
        payload = {"task_code": "T", "run_id": run, "rerun": True}
    elif kind == "ignore":
        options = ["--task-code", "T", "--standalone", "--ignore-dependencies"]
        payload = {"task_code": "T", "standalone": True, "ignore_dependencies": True}
    else:
        options = ["--backfill", "2026-10-20:2026-10-20"]
        payload = {"backfill_from": "2026-10-20", "backfill_to": "2026-10-20"}
    if interface == "cli":
        accepted = main(["run", "--pipeline-code", "P", *options]) == ExitCode.SUCCESS
        error = capsys.readouterr().err
    else:
        client = TestClient(create_app(ctx))
        response = client.post(
            action_path(ACTIONS[ActionName.RUN]).format(project="default"),
            json={"pipeline_code": "P", **payload},
            headers={"Authorization": "Bearer " + credential.token},
        )
        accepted, error = response.status_code == 200, response.text
    if policy == "RELAXED":
        assert accepted, error
    else:
        assert not accepted and "STRICT" in error and "--reason" in error


def test_production_cli_refuses_before_mutating_and_confirms_exact_code(
    metadata_project, monkeypatch, capsys
):
    from etl_craft.engine.repository.pauses import fetch_open_pauses

    monkeypatch.delenv("CI", raising=False)

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(
        ctx, ActionName.PROJECT_SET, project="default", environment_type="PROD", reason="production"
    )
    with project.engine.begin() as conn:
        add_pipeline(conn, "P")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: False)
    assert main(["pause", "--pipeline-code", "P", "--reason", "maintenance"]) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert "PRODUCTION" in captured.err and "--yes" in captured.err
    with project.engine.connect() as conn:
        assert "P" not in fetch_open_pauses(conn)
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "wrong")
    assert main(["pause", "--pipeline-code", "P", "--reason", "maintenance"]) == ExitCode.USAGE
    with project.engine.connect() as conn:
        assert "P" not in fetch_open_pauses(conn)
    monkeypatch.setattr("builtins.input", lambda: "default")
    assert main(["pause", "--pipeline-code", "P", "--reason", "maintenance"]) == ExitCode.SUCCESS
    with project.engine.connect() as conn:
        assert "P" in fetch_open_pauses(conn)


@pytest.mark.parametrize("confirmation", ["right", "wrong", "noninteractive", "yes"])
def test_prod_project_migration_confirms_before_its_first_write(
    metadata_project, monkeypatch, capsys, confirmation
):
    from sqlalchemy import text

    from etl_craft.dialects.engine import for_engine

    monkeypatch.delenv("CI", raising=False)
    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    credential = act(ctx, ActionName.TOKEN_CREATE, name="admin", role=ApiRole.ADMIN)
    act(
        ctx, ActionName.PROJECT_SET, project="default", environment_type="PROD", reason="production"
    )
    directory = project.root / "migrations"
    directory.mkdir(exist_ok=True)
    (directory / "0001_team.sql").write_text("CREATE TABLE CFG_TEAM_CHECK (ID INTEGER);\n")
    monkeypatch.chdir(project.root)
    monkeypatch.setenv("ETL_CRAFT_TOKEN", credential.token)
    monkeypatch.setattr("etl_craft.cli.output.can_prompt", lambda: confirmation != "noninteractive")

    def answer():
        with project.engine.connect() as conn:
            assert not for_engine(conn).has_table(conn, "CFG_TEAM_CHECK")
        return "default" if confirmation == "right" else "wrong"

    monkeypatch.setattr("builtins.input", answer)
    arguments = ["migrate"] + (["--yes"] if confirmation == "yes" else [])
    result = main(arguments)
    accepted = confirmation in {"right", "yes"}
    assert result == (ExitCode.SUCCESS if accepted else ExitCode.USAGE), capsys.readouterr().err
    with project.engine.connect() as conn:
        assert for_engine(conn).has_table(conn, "CFG_TEAM_CHECK") == accepted
        if not accepted:
            assert not conn.execute(
                text(
                    "SELECT VERSION FROM SCHEMA_MIGRATIONS "
                    "WHERE SOURCE='PROJECT' AND VERSION='0001_team'"
                )
            ).first()


def test_login_and_whoami_show_the_selected_environment(metadata_project, monkeypatch, capsys):
    import json
    import sys

    project = metadata_project
    ctx = OperationContext(project.engine, project.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    act(ctx, ActionName.ACCOUNT_ADD, name="owner", role=ApiRole.ADMIN, password="owner password")
    act(
        ctx,
        ActionName.PROJECT_SET,
        project="default",
        environment_type="UAT",
        environment_name="owner checks",
        reason="environment",
    )
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("ETL_CRAFT_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(project.root / "private-session"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "owner")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "owner password")
    assert main(["login"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert "owner (admin)" in captured.out
    assert "default · UAT · owner checks · local" in captured.err
    assert main(["whoami", "--format", "json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    identity = json.loads(captured.out)
    assert identity["name"] == "owner"
    assert identity["environment"] == {"type": "UAT", "name": "owner checks"}
    assert " · " not in captured.err
