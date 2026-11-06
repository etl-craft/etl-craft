"""`config plan` and `config apply` read a published bundle for a caller with no host."""

import csv
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from etl_craft.config import load_config
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole, Transport
from etl_craft.core.errors import PermissionDeniedError, ResourceNotFoundError, UsageError
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


def test_a_published_bundle_is_applied_not_the_files_edited_after_it(scene):
    p, folder = scene
    python_task(folder, "published")
    code, output = p.run("bundle", "publish")
    assert code == 0, output
    python_task(folder, "unpublished")  # edited after publishing
    code, output = p.run("config", "plan", "--bundle", "latest")
    assert code == 0 and "bundle " in output and "published" in output, output
    assert "published" not in codes(p)  # a plan changes nothing
    bundles = count_bundles(p)
    code, output = p.run("config", "apply", "--bundle", "latest")
    assert code == 0, output
    assert count_bundles(p) == bundles  # the refresh pins the applied bundle; it publishes nothing
    assert {"published", "load"} <= codes(p) and "unpublished" not in codes(p)
    code, output = p.run("config", "plan", "--bundle", "latest")
    assert code == 0 and "0 change(s)" in output, output
    code, output = p.run("config", "apply")  # the host's own files still apply as before
    assert code == 0, output
    assert "unpublished" in codes(p)


def over_http(p, role):
    return OperationContext(
        p.engine, p.config, SYSTEM_ACTOR, role=role, project="default", transport=Transport.HTTP
    )


def test_over_the_api_a_developer_needs_a_bundle_and_nothing_else_is_accepted(scene):
    p, _ = scene
    developer = over_http(p, ApiRole.ADMIN)  # CAN_MANAGE on the project, which apply needs
    with pytest.raises(UsageError, match="reads a published bundle"):
        act(developer, ActionName.CONFIG_APPLY)
    with pytest.raises(UsageError, match="no config/ folder"):  # published before config/ existed
        act(developer, ActionName.CONFIG_APPLY, bundle="latest")
    code, output = p.run("bundle", "publish")
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


def test_the_result_names_the_bundle_and_the_request_is_audited(scene):
    p, _ = scene
    code, output = p.run("bundle", "publish")
    assert code == 0, output
    done = act(over_http(p, ApiRole.ADMIN), ActionName.CONFIG_APPLY, bundle="latest")
    applied = done.directory.split()[1]
    assert done.directory.startswith("bundle ") and len(applied) == 64
    assert done.refreshes and {r.bundle_id for r in done.refreshes} == {applied}
    with p.engine.connect() as conn:
        recorded = list(
            conn.execute(
                text("SELECT ARGUMENTS AS arguments FROM AUD_ACTIONS WHERE COMMAND LIKE 'config%'")
            ).scalars()
        )
    assert any("latest" in str(arguments) for arguments in recorded), recorded
