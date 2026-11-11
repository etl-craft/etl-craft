"""Published seed project using either Engine DB and a real local warehouse."""

import pytest
import yaml

from etl_craft.config import ConnectionProfile, load_config
from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActionName, ActorKind, ApiRole
from etl_craft.engine.project_files import collect
from etl_craft.services.operations.context import OperationContext
from fixtures.actions import act
from fixtures.engine_db import profile_block


@pytest.fixture
def seed_project(engine_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_TEST_PRIVACY_KEY", "seed-fixture-key")
    profile = ConnectionProfile(
        "WAREHOUSE", "dev", f"jdbc:duckdb:{tmp_path / 'warehouse.db'}", "", "NONE"
    )
    raw = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {"Project": "default"},
        "Engine": {"dev": profile_block(engine_db.config.engine, engine_db.config.engine.schema)},
        "Warehouse": {"Name": "DuckDB", "dev": profile_block(profile, "ds")},
    }
    raw["Artifacts"] = {"Store": (tmp_path / "artifacts").as_uri()}
    raw["Privacy"] = {"Hmac_secret": "SEED_TEST_PRIVACY_KEY"}
    path = tmp_path / "craft-connector.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    config = load_config(path)
    ctx = OperationContext(
        engine_db.engine,
        config,
        Actor("seed-deployer", ActorKind.USER),
        role=ApiRole.ADMIN,
        project="default",
        project_id=1,
    )
    folder = tmp_path / "seeds/warehouse/ds/agents"
    folder.mkdir(parents=True)
    (folder / "columns.csv").write_text(
        "COLUMN_NAME|DATA_TYPE|KEY_FLAG\nid|INTEGER|Y\nname|VARCHAR|N\n"
    )
    (folder / "data.csv").write_text("id|name\n1|Ada\n2|Bob\n")
    import duckdb

    with duckdb.connect(str(tmp_path / "warehouse.db")) as conn:
        conn.execute("CREATE SCHEMA ds")

    def publish():
        return act(ctx, ActionName.BUNDLE_PUBLISH, files=collect(tmp_path))

    publish()
    return ctx, folder, publish
