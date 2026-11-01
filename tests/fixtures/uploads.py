"""Real received upload fixtures shared by HTTP, storage and recovery tests."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from etl_craft.api.app import create_app
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.tokens import TokenCreate
from fixtures.metadata import add_pipeline, add_task


@pytest.fixture
def upload_api(engine_db, tmp_path):
    config = replace(engine_db.config, config_path=tmp_path / "craft-connector.yml")
    folder = config.project_dir / "validation_scripts"
    folder.mkdir()
    (folder / "check.py").write_text("def validate(task):\n    list(task.reader.rows())\n")
    ctx = OperationContext(engine_db.engine, config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    writer = invoke(ctx, ActionName.TOKEN_CREATE, TokenCreate(name="writer", role=ApiRole.ADMIN))
    viewer = invoke(ctx, ActionName.TOKEN_CREATE, TokenCreate(name="viewer", role=ApiRole.VIEWER))
    with ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(
            conn,
            pipeline,
            "check",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
        )
        conn.execute(text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y'"))
    with TestClient(create_app(ctx)) as client:
        yield ctx, client, writer, viewer
