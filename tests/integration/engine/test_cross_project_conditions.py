"""Retiring a definition cannot strand a condition in another project."""

from base64 import b64encode
from dataclasses import replace

import pytest
from sqlalchemy import event, text

from etl_craft.config.object_models import Artifacts
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.core.errors import ConditionError
from etl_craft.engine.condition_edges import derive_edges
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.config_files import ConfigDirectory
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.deploy import DeployInput
from etl_craft.services.operations.identity import authenticated_context
from etl_craft.services.operations.requests import ValidateInput
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task, insert

PREFIX = "upstream default.LOAD.extract: ACTIVE_FLAG=N; expected an active condition target"
VISIBLE = (
    "client0.REPORT0.consume0 RUN_CONDITION depends on default.LOAD.extract; "
    "change the downstream condition or deactivate its owner first"
)
HIDDEN = "a task in another project depends on default.LOAD.extract; ask an administrator"


@pytest.fixture
def scenario(engine_db, tmp_path):
    config = replace(engine_db.config, config_path=tmp_path / "craft-connector.yml")
    (tmp_path / "config").mkdir()
    connector(tmp_path, "default")
    (tmp_path / "python_scripts").mkdir()
    (tmp_path / "python_scripts/task.py").write_text("def run(task):\n    pass\n")
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "LOAD")
        task = add_task(conn, pipeline, "extract", "PYTHON", SCRIPT_FILE="python_scripts/task.py")
    return OperationContext(engine_db.engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN), task


def connector(root, project):
    (root / "craft-connector.yml").write_text(
        "Secrets:\n  Source_type: ENVIRONMENT\n"
        f"Orchestration:\n  dev:\n    Project: {project}\n"
        "Warehouse:\n  dev:\n    Jdbc_url: jdbc:duckdb:warehouse.db\n    Schema: main\n"
    )


def deploy(ctx):
    root = ctx.config.project_dir
    files = {
        path.relative_to(root).as_posix(): b64encode(path.read_bytes()).decode()
        for path in (
            root / "craft-connector.yml",
            *root.glob("config/*.csv"),
            *root.glob("python_scripts/*.py"),
        )
    }
    config = replace(ctx.config, artifacts=Artifacts((root / "store").as_uri()))
    return invoke(replace(ctx, config=config), ActionName.DEPLOY, DeployInput(files=files))


def dependents(ctx, count, *, start=False, offset=0):
    with ctx.engine.begin() as conn:
        for i in range(offset, offset + count):
            project = insert(
                conn,
                "INSERT INTO CFG_PROJECTS (PROJECT_CODE,PROJECT_NAME,DEFAULT_POOL) "
                "VALUES (:code,:code,'default')",
                "PROJECT_ID",
                code=f"client{i}",
            )
            pipeline = add_pipeline(conn, f"REPORT{i}", project_id=project)
            if start:
                conn.execute(
                    text("UPDATE CFG_PIPELINES SET START_CONDITION=:rule WHERE PIPELINE_ID=:id"),
                    {"rule": "default.LOAD.SUCCESS", "id": pipeline},
                )
            else:
                task = add_task(
                    conn, pipeline, f"consume{i}", "PYTHON", SCRIPT_FILE="python_scripts/task.py"
                )
                conn.execute(
                    text("UPDATE CFG_TASKS SET RUN_CONDITION=:rule WHERE TASK_ID=:id"),
                    {"rule": "default.LOAD.extract.SUCCESS", "id": task},
                )
            derive_edges(conn, project)


def retire_task(ctx, *, rename=False):
    rows = "PIPELINE_CODE,TASK_CODE,TASK_TYPE,HANDLER,ACTIVE_FLAG\nLOAD,extract,ETL,PYTHON,N\n"
    if rename:
        rows += "LOAD,new_extract,ETL,PYTHON,Y\n"
    (ctx.config.project_dir / "config/tasks.csv").write_text(rows)


@pytest.mark.parametrize("rename", [False, True])
def test_deploy_refuses_breaking_task_condition_and_rolls_back(scenario, rename):
    ctx, task = scenario
    dependents(ctx, 1)
    retire_task(ctx, rename=rename)
    with pytest.raises(ConditionError) as error:
        deploy(ctx)
    assert str(error.value) == f"{PREFIX}; {VISIBLE}"
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT ACTIVE_FLAG FROM CFG_TASKS WHERE TASK_ID=:id"), {"id": task}
            ).scalar_one()
            == "Y"
        )
        assert (
            conn.execute(
                text("SELECT ACTIVE_FLAG FROM CFG_TASK_DEPENDENCY WHERE DEPENDS_ON_TASK_ID=:id"),
                {"id": task},
            ).scalar_one()
            == "Y"
        )
        assert not conn.execute(
            text("SELECT TASK_ID FROM CFG_TASKS WHERE TASK_CODE='new_extract'")
        ).first()


def test_deploy_refuses_breaking_start_condition(scenario):
    ctx, _ = scenario
    dependents(ctx, 1, start=True)
    retire_task(ctx)
    (ctx.config.project_dir / "config/pipelines.csv").write_text(
        "PIPELINE_CODE,PIPELINE_NAME,REFRESH_TYPE,ACTIVE_FLAG\nLOAD,LOAD,FULL,N\n"
    )
    with pytest.raises(ConditionError, match=r"client0\.REPORT0 START_CONDITION"):
        deploy(ctx)


def test_plan_and_validate_redact_hidden_dependents_and_keep_visible_ones(scenario):
    ctx, task = scenario
    dependents(ctx, 2)
    retire_task(ctx)
    credentials = act(ctx, ActionName.TOKEN_CREATE, name="condition-reader", role=ApiRole.DEVELOPER)
    caller = authenticated_context(ctx, credentials.metadata)
    act(ctx, ActionName.ACCESS_GRANT, project="default", account="condition-reader",
        role="CAN_MANAGE", reason="config owner")  # fmt: skip
    with pytest.raises(ConditionError) as error:
        invoke(caller, ActionName.CONFIG_PLAN, ConfigDirectory())
    assert str(error.value) == (
        f"{PREFIX}; 2 tasks in other projects depend on default.LOAD.extract; ask an administrator"
    )
    act(ctx, ActionName.ACCESS_GRANT, project="client0", account="condition-reader",
        role="CAN_VIEW", reason="visible dependent")  # fmt: skip
    with ctx.engine.begin() as conn:
        client = conn.execute(
            text("SELECT PROJECT_ID FROM CFG_PROJECTS WHERE PROJECT_CODE='client1'")
        ).scalar_one()
        add_pipeline(conn, "VISIBLE", project_id=client)
    act(ctx, ActionName.ACCESS_GRANT, project="client1", account="condition-reader",
        pipeline="VISIBLE", role="CAN_VIEW", reason="visible sibling")  # fmt: skip
    expected = f"{PREFIX}; {VISIBLE}; {HIDDEN}"
    with pytest.raises(ConditionError) as error:
        invoke(caller, ActionName.CONFIG_PLAN, ConfigDirectory())
    assert str(error.value) == expected
    with ctx.engine.begin() as conn:
        conn.execute(text("UPDATE CFG_TASKS SET ACTIVE_FLAG='N' WHERE TASK_ID=:id"), {"id": task})
    report = invoke(caller, ActionName.VALIDATE, ValidateInput())
    assert [
        (f.where, f.status, f.message) for f in report.findings if f.where == "LOAD.extract"
    ] == [("LOAD.extract", "FAIL", expected)]


@pytest.mark.parametrize("retire", [False, True])
def test_deploy_can_retry_after_the_dependent_drops_its_condition(scenario, tmp_path, retire):
    ctx, _ = scenario
    dependents(ctx, 1)
    retire_task(ctx)
    with pytest.raises(ConditionError):
        deploy(ctx)
    client = tmp_path / "client"
    (client / "config").mkdir(parents=True)
    connector(client, "client0")
    (client / "python_scripts").mkdir()
    (client / "python_scripts/task.py").write_text("def run(task):\n    pass\n")
    active = "N" if retire else "Y"
    (client / "config/tasks.csv").write_text(
        "PIPELINE_CODE,TASK_CODE,TASK_TYPE,HANDLER,RUN_CONDITION,ACTIVE_FLAG\n"
        f"REPORT0,consume0,ETL,PYTHON,,{active}\n"
    )
    downstream = replace(
        ctx,
        project="client0",
        config=replace(ctx.config, project="client0", config_path=client / "craft-connector.yml"),
    )
    for scope in (downstream, ctx):
        done = deploy(scope)
        assert not done.failed, done


def test_refusal_statement_count_is_independent_of_the_number_of_dependents(scenario):
    ctx, _ = scenario
    retire_task(ctx)
    dependents(ctx, 2)
    counts = []

    def record(*_args):
        counts[-1] += 1

    for additional in (0, 18):
        dependents(ctx, additional, offset=2)
        counts.append(0)
        event.listen(ctx.engine, "before_cursor_execute", record)
        try:
            with pytest.raises(ConditionError):
                invoke(ctx, ActionName.CONFIG_PLAN, ConfigDirectory())
        finally:
            event.remove(ctx.engine, "before_cursor_execute", record)
    assert counts[0] == counts[1]
