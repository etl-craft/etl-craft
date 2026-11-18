"""`deploy` publishes, applies config, loads seeds and refreshes, and stops at a failure."""

import csv
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.config.object_models import Artifacts
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole, Transport
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
from etl_craft.engine.project_files import collect
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.config_files import ConfigDirectory
from fixtures.actions import act


def python_task(folder: Path, code: str) -> None:
    add_row(
        folder, "tasks.csv", PIPELINE_CODE="P", TASK_CODE=code, TASK_TYPE="ETL",
        HANDLER="PYTHON", ACTIVE_FLAG="Y",
    )  # fmt: skip
    for name, value in (("SCRIPT_FILE", "python_scripts/load.py"), ("SCRIPT_KIND", "INGESTION")):
        add_row(
            folder, "task_parameters.csv", PIPELINE_CODE="P", TASK_CODE=code,
            PARAMETER_NAME=name, PARAMETER_VALUE=value, ACTIVE_FLAG="Y",
        )  # fmt: skip


def add_row(folder: Path, name: str, **values: str) -> None:
    """Append one row to a config CSV, keeping the exported header."""
    path = folder / name
    with path.open() as stream:
        header = next(csv.reader(stream))
    with path.open("a", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerow([values.get(c, "") for c in header])


def count_bundles(project) -> int:
    with project.engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) AS n FROM AUD_PROJECT_BUNDLES")).scalar_one()


def codes(project) -> set[str]:
    with project.engine.connect() as conn:
        return {r.code for r in conn.execute(text("SELECT TASK_CODE AS code FROM CFG_TASKS"))}


@pytest.fixture
def scene(cli_project):
    p = cli_project
    raw = yaml.safe_load(p.config.config_path.read_text())
    raw["Artifacts"] = {"Store": (p.config.project_dir / "artifacts").as_uri()}
    p.config.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    p.config = load_config(p.config.config_path)
    code, output = p.run("config", "export")
    assert code == 0, output
    return p, p.config.project_dir / "config"


def deployed(p, *args):
    code, output = p.run("deploy", *args, "--format", "json")
    return code, json.loads(
        output[output.index("\n{") + 1 :] if not output.startswith("{") else output
    )


def test_deploy_applies_and_pins_what_it_publishes_and_a_plan_writes_nothing(scene):
    p, folder = scene
    python_task(folder, "planned")
    bundles = count_bundles(p)
    code, done = deployed(p, "--plan")
    assert code == 0 and done["plan"] and done["bundle_id"] is None, done
    assert "planned" not in codes(p) and count_bundles(p) == bundles
    assert any(change["row"] == "P.planned" for change in done["config"]["changes"])
    code, done = deployed(p)
    assert code == 0, done
    assert count_bundles(p) == bundles + 1 and "planned" in codes(p)
    assert done["refreshes"] and {r["bundle_id"] for r in done["refreshes"]} == {done["bundle_id"]}
    assert done["config"]["directory"] == f"bundle {done['bundle_id']}"


def test_a_failed_config_step_stops_seeds_and_refresh(scene):
    p, folder = scene
    add_row(
        folder, "tasks.csv", PIPELINE_CODE="P", TASK_CODE="broken", TASK_TYPE="ETL",
        HANDLER="PYTHON", ACTIVE_FLAG="Y",
    )  # fmt: skip
    code, done = deployed(p)
    assert code == 1 and done["config"]["failed"], done
    assert done["seed_loads"] == [] and done["refreshes"] == []
    code, output = p.run("deploy")
    assert code == 1 and "validate failed the result" in output, output


def over_http(p, role):
    return OperationContext(
        p.engine, p.config, SYSTEM_ACTOR, role=role, project="default", transport=Transport.HTTP
    )


def test_the_server_validates_the_uploaded_files_not_its_own(scene):
    p, folder = scene
    python_task(folder, "published")
    files = collect(p.config.project_dir)
    shutil.rmtree(p.config.project_dir / "python_scripts")  # a server holds no project scripts
    done = act(over_http(p, ApiRole.ADMIN), ActionName.DEPLOY, files=files)
    assert not done.failed and "published" in codes(p), done.config.findings


def test_deploy_refuses_files_it_would_not_read_and_a_folder_the_caller_cannot_see(scene):
    p, _ = scene
    admin = over_http(p, ApiRole.ADMIN)
    with pytest.raises(UsageError, match=r"deploy without files, but Artifacts\.Store is set"):
        act(admin, ActionName.DEPLOY)
    no_store = replace(admin, config=replace(p.config, artifacts=Artifacts()))
    with pytest.raises(UsageError, match=r"deploy over the API needs Artifacts\.Store"):
        act(no_store, ActionName.DEPLOY)
    with pytest.raises(UsageError, match=r"this deployment has no Artifacts\.Store"):
        act(no_store, ActionName.DEPLOY, files=collect(p.config.project_dir))
    with pytest.raises(PermissionDeniedError):
        act(replace(admin, role=ApiRole.VIEWER), ActionName.DEPLOY, files={})


def test_config_plan_reads_a_published_bundle_over_the_api(scene):
    p, _ = scene
    developer = over_http(p, ApiRole.ADMIN)  # CAN_MANAGE on the project, which plan needs
    with pytest.raises(UsageError, match="reads a published bundle"):
        act(developer, ActionName.CONFIG_PLAN)
    code, output = p.run("deploy")
    assert code == 0, output
    with pytest.raises(ResourceNotFoundError, match="no such published bundle"):
        act(developer, ActionName.CONFIG_PLAN, bundle="0" * 64)
    with pytest.raises(PermissionDeniedError):
        act(replace(developer, role=ApiRole.VIEWER), ActionName.CONFIG_PLAN, bundle="latest")
    assert not act(developer, ActionName.CONFIG_PLAN, bundle="latest").failed
    with pytest.raises(UsageError, match="one source of config files"):
        ConfigDirectory(bundle="latest", config_dir=Path("config"))
    with pytest.raises(UsageError, match="export writes files on this host"):
        act(
            replace(developer, transport=Transport.LOCAL), ActionName.CONFIG_EXPORT, bundle="latest"
        )


def test_the_request_is_audited_without_file_contents(scene):
    p, folder = scene
    python_task(folder, "audited")
    code, output = p.run("deploy")
    assert code == 0, output
    with p.engine.connect() as conn:
        recorded = list(
            conn.execute(
                text("SELECT ARGUMENTS AS arguments FROM AUD_ACTIONS WHERE COMMAND='deploy'")
            ).scalars()
        )
    assert recorded and all("python_scripts/load.py" not in str(a) for a in recorded), recorded
