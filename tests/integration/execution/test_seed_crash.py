"""A killed standalone seed load can be reapplied after its expired lock is reconciled."""

import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from etl_craft.core.actor import acting_as
from etl_craft.core.enums import ActionName
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.engine.repository.hash_versions import fetch_hash_version
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task
from fixtures.seeds import seed_project as seed_project

pytestmark = pytest.mark.chaos

PROGRAM = """
import sys
from etl_craft.config import load_config
from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActionName, ActorKind, ApiRole
from etl_craft.engine.connection import engine_db
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.requests import NoInput
config = load_config(sys.argv[1])
engine = engine_db(config)
ctx = OperationContext(engine, config, Actor('seed-deployer', ActorKind.USER), role=ApiRole.ADMIN)
invoke(ctx, ActionName.SEED_APPLY, NoInput())
"""


@pytest.mark.parametrize("point", ["seed.after_warehouse_commit", "seed.before_audit_commit"])
@pytest.mark.parametrize("existing", [False, True])
def test_killed_seed_reapply_keeps_exact_rows_and_one_completed_outcome(
    seed_project, point, existing
):
    import duckdb

    ctx, folder, publish = seed_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "REFERENCE")
        add_task(
            conn,
            pipeline,
            "merge",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="ds.agents",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
            SELECT_QUERY="SELECT 1 AS id, 'x' AS name",
        )
    if existing:
        assert act(ctx, ActionName.SEED_APPLY).loads[0].status == SeedStatus.LOADED
        (folder / "data.csv").write_text("id|name\n3|Cy\n")
    publish()
    done = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(ctx.config.config_path)],
        env=os.environ | {"ETL_CRAFT_FAULT": f"{point}:kill"},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert done.returncode == 137, done.stdout + done.stderr
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE AUD_RESOURCE_LOCKS SET LEASE_EXPIRES_AT=:past"),
            {"past": datetime(2000, 1, 1, tzinfo=UTC)},
        )
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_SEED_LOADS")).scalar_one() == int(
            existing
        )
        assert fetch_hash_version(conn, "warehouse.ds.agents") == (2 if existing else None)
    outcome = act(ctx, ActionName.SEED_APPLY).loads[0]
    assert outcome.status == SeedStatus.LOADED, outcome.message
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        expected = [(3, "Cy")] if existing else [(1, "Ada"), (2, "Bob")]
        assert conn.execute("SELECT id,name FROM ds.agents ORDER BY id").fetchall() == expected
    with ctx.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM AUD_SEED_LOADS")).scalar_one()
            == int(existing) + 1
        )
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PIPELINES_RUN_LOG")).scalar_one() == 0
        assert fetch_hash_version(conn, "warehouse.ds.agents") == 2
