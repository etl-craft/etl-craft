"""In-row protection uses the provider's target MERGE without cross-table transactions."""

import os
from uuid import uuid4

import pytest
from test_cloud_sql_actions import close_world, cloud_world

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole, TableFormat
from etl_craft.core.errors import HandlerError
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.cloud import DATABRICKS_VARS, SNOWFLAKE_VARS, require_variables
from fixtures.single_merge import target_mutations

pytestmark = [pytest.mark.timeout(1200), pytest.mark.usefixtures("engine_actor")]


@pytest.mark.parametrize(
    ("provider", "variables"),
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
def test_protected_edits_reload_unlock_and_per_cell_writers(tmp_path, provider, variables):
    vendor = provider.upper()
    require_variables(vendor, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{vendor}_{name}" for name in variables}
    w = cloud_world(
        tmp_path,
        provider,
        fields,
        TableFormat.NATIVE,
        os.environ[f"ETL_CRAFT_TEST_{vendor}_SCHEMA"],
    )
    targets = []
    try:
        for kind in ("SCD1_MERGE", "SCD2_MERGE"):
            target = "etl_protected_" + uuid4().hex[:10]
            targets.append(target)
            source = (
                "SELECT 1 AS id,CAST('Source' AS VARCHAR(30)) AS name,10 AS amount,"
                "CAST(NULL AS BOOLEAN) AS LOCKED"
            )
            w.setup(target, source, kind)
            task = "load_" + target
            params = {
                "SQL_ACTION": kind,
                "TARGET_OBJECT": target,
                "SELECT_QUERY": source,
                "MERGE_KEY": "id",
                "MERGE_COMPARE_COLUMNS": "name|amount",
            }
            w.run(task, **params)
            ctx = OperationContext(
                w.engine_db, w.config, Actor("alice", ActorKind.USER), role=ApiRole.ADMIN
            )
            base = {"pipeline_code": "P", "task_code": task, "key": {"id": 1}}
            with target_mutations(w, target) as statements:
                act(ctx, ActionName.DATA_EDIT, **base, values={"name": "Manual"}, reason="correct")
            assert len(statements) == 1 and statements[0].startswith("MERGE INTO ")
            w.run(task, **{**params, "SELECT_QUERY": source.replace("10 AS", "20 AS")})
            provenance = act(ctx, ActionName.DATA_PROVENANCE, **base)
            cells = {r["column_name"]: r for r in provenance.records}
            assert cells["name"]["locked"] and cells["name"]["writer"] == "alice"
            assert cells["amount"]["writer"] == "etl-craft"
            act(ctx, ActionName.DATA_UNLOCK, **base, columns=("name",), reason="return")
            w.run(task, **params)
            rows = w.rows(f"SELECT name,amount FROM {w.name(target)} WHERE ACTIVE_FLAG='Y'")
            assert rows == [("Source", 10)]
            empty = w.run(task, **{**params, "SELECT_QUERY": source + " WHERE 1=0"})
            assert empty.insert_count == empty.update_count == 0
            with (
                target_mutations(w, target) as statements,
                pytest.raises(HandlerError, match=r"staged LOCKED type=.*expected BOOLEAN"),
            ):
                w.run(
                    task,
                    **{
                        **params,
                        "SELECT_QUERY": source.replace(
                            "CAST(NULL AS BOOLEAN)", "CAST('true' AS VARCHAR(10))"
                        ),
                    },
                )
            assert statements == []
            assert w.rows(f"SELECT name,amount FROM {w.name(target)} WHERE ACTIVE_FLAG='Y'") == rows
    finally:
        for target in targets:
            w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")
        close_world(w)
