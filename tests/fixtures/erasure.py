"""Published erasure project with a private warehouse identifier."""

from dataclasses import replace

import pytest

from etl_craft.core.actor import acting_as
from etl_craft.core.enums import ActionName
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task


@pytest.fixture
def erasure_project(seed_project, monkeypatch):
    ctx, _, publish = seed_project
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    import yaml

    from etl_craft.config import load_config

    path = ctx.config.config_path
    raw = yaml.safe_load(path.read_text())
    raw["Erasure"] = {"Hmac_secret": "ERASURE_HMAC"}
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    ctx = replace(ctx, config=load_config(path))
    publish()
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "ERASURE_TEST")
        add_task(
            conn,
            pipeline,
            "LAND",
            handler="SQL",
            **{
                "SQL_ACTION": "CREATE_TABLE",
                "TARGET_OBJECT": "ds.people",
                "SELECT_QUERY": "SELECT 'template' AS person, 1 AS n",
            },
        )
    import duckdb

    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("CREATE TABLE ds.people(person VARCHAR,n INTEGER)")
        conn.execute("INSERT INTO ds.people VALUES ('private-person-key',1),('retained',2)")
    result = act(ctx, ActionName.PIPELINE_REFRESH)
    assert all(str(r.status) == "SUCCESS" for r in result.refreshes), result
    return ctx


@pytest.fixture
def erasure_world(sql_world, monkeypatch):
    from etl_craft.core.actor import Actor
    from etl_craft.core.enums import ActorKind, ApiRole
    from etl_craft.services.operations.context import OperationContext

    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    w.run(
        "land",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="landing",
        SELECT_QUERY="SELECT 'retained' AS person, 1 AS n",
    )
    w.execute(
        f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key,2)", key="private-world-key"
    )
    w.run(
        "copy",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="copied",
        SELECT_QUERY=f"SELECT person AS renamed,n FROM {w.name('landing')}",
    )
    ctx = OperationContext(
        w.engine_db,
        config,
        Actor("eraser", ActorKind.USER),
        role=ApiRole.ADMIN,
        project="default",
        project_id=1,
    )
    return ctx, w


def ordinary_erasure(ctx, world):
    from etl_craft.engine import transitions
    from etl_craft.handlers.registry import TaskContext

    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        task = add_task(conn, world.pipeline_id, "ERASE", handler="ERASURE")
        task_run = transitions.find_or_create_task_run(
            conn, task, world.pipeline_run_id
        ).task_run_id
    return TaskContext(
        ctx.config,
        world.pipeline_id,
        "P",
        task,
        "ERASE",
        world.pipeline_run_id,
        task_run,
        1,
        "ERASURE",
        "FULL",
        {},
    )


def killed_erasure(config, table, key):
    import os

    from etl_craft.core.actor import Actor
    from etl_craft.core.enums import ActorKind, ApiRole
    from etl_craft.dialects.engine import build_engine
    from etl_craft.services.operations.context import OperationContext

    os.environ["ETL_CRAFT_FAULT"] = "erasure.after_table:kill"
    ctx = OperationContext(
        build_engine(config),
        config,
        Actor("eraser", ActorKind.USER),
        role=ApiRole.ADMIN,
        project="default",
        project_id=1,
    )
    act(ctx, ActionName.ERASE, table=table, column="person", value=key, reason="request")
