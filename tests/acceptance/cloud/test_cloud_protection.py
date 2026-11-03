"""In-row protection uses the provider's target MERGE without cross-table transactions."""

import os
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from test_cloud_sql_actions import close_world, cloud_world

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole, TableFormat
from etl_craft.core.errors import HandlerError
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.cloud import DATABRICKS_VARS, SNOWFLAKE_VARS, require_variables
from fixtures.protection_acceptance import (
    check_locked_deletion,
    check_mutation_boundaries,
    check_outside_deletion,
)
from fixtures.single_merge import target_mutations

pytestmark = [pytest.mark.timeout(3600), pytest.mark.usefixtures("engine_actor")]


@pytest.mark.parametrize(
    ("provider", "variables"),
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
@pytest.mark.parametrize("table_format", [TableFormat.NATIVE, TableFormat.ICEBERG])
@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_protected_edits_reload_unlock_and_per_cell_writers(
    tmp_path, provider, variables, table_format, kind, monkeypatch
):
    vendor = provider.upper()
    require_variables(vendor, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{vendor}_{name}" for name in variables}
    w = cloud_world(
        tmp_path,
        provider,
        fields,
        table_format,
        os.environ[f"ETL_CRAFT_TEST_{vendor}_SCHEMA"],
    )
    monkeypatch.setenv("CLOUD_PRIVACY_HMAC", "cloud-test-only-project-privacy")
    w.config = replace(w.config, privacy_hmac_secret="CLOUD_PRIVACY_HMAC")
    targets = []
    try:
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
        check_locked_deletion(w, ctx, task, target, params)
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
        check_mutation_boundaries(w, ctx, task, target, params, monkeypatch)
        w.run(task, **params)
        check_outside_deletion(w, ctx, task, target)
        # Restore through the source before checking the independently named legacy state.
        w.run(task, **params)
        nested = target + "_nested"
        targets.append(nested)
        array = (
            "CAST(ARRAY_CONSTRUCT(1,2) AS ARRAY(NUMBER(38,0)))"
            if provider == "Snowflake"
            else "ARRAY(1,2)"
        )
        nested_source = (
            "SELECT 1 AS id,CAST('Source' AS VARCHAR(30)) AS name," + array + " AS numbers"
        )
        w.setup(nested, nested_source, kind)
        nested_task = "nested_" + target
        w.run(
            nested_task,
            SQL_ACTION=kind,
            TARGET_OBJECT=nested,
            SELECT_QUERY=nested_source,
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
        )
        with (
            target_mutations(w, nested) as nested_writes,
            pytest.raises(HandlerError, match="cast it to a scalar type in the SELECT"),
        ):
            act(
                ctx,
                ActionName.DATA_EDIT,
                pipeline_code="P",
                task_code=nested_task,
                key={"id": 1},
                values={"name": "Manual"},
                reason="correct",
            )
        assert nested_writes == []
        legacy = "etl_protection_" + sha256(w.name(target).lower().encode()).hexdigest()[:20]
        targets.append(legacy)
        w.execute(f"CREATE TABLE {w.name(legacy)} (id INTEGER)")
        with pytest.raises(HandlerError, match=r"back up.*recreate.*re-apply"):
            w.run(task, **params)
    finally:
        for target in targets:
            w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")
        close_world(w)


@pytest.mark.parametrize(
    ("provider", "variables"),
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
@pytest.mark.parametrize("table_format", [TableFormat.NATIVE, TableFormat.ICEBERG])
@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
@pytest.mark.timeout(7200)
def test_provider_upload_controls_and_mixed_writers(
    tmp_path, provider, variables, table_format, kind, monkeypatch, capsys, request
):
    from fixtures.scd_protection import use_postgres_engine
    from fixtures.stewardship import (
        check_upload_controls,
        check_upload_recovery,
        cleanup_upload_scratch,
        configure_upload_world,
    )

    vendor = provider.upper()
    require_variables(vendor, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{vendor}_{name}" for name in variables}
    w = cloud_world(
        tmp_path,
        provider,
        fields,
        table_format,
        os.environ[f"ETL_CRAFT_TEST_{vendor}_SCHEMA"],
        isolated=True,
    )
    w.engine_db.dispose()
    use_postgres_engine(w, request)
    monkeypatch.setenv("ETL_CRAFT_TEST_PRIVACY_SECRET", "cloud-test-only-project-privacy")
    prefix = "u" + uuid4().hex[:8] + "_"
    try:
        prepared = configure_upload_world(w, kind, prefix=prefix)
        check_upload_controls(prepared, monkeypatch, capsys, tmp_path, table=prefix + "uploaded")
        for point in ("before_pending", "after_pending", "after_merge", "after_committed"):
            check_upload_recovery(
                prepared, monkeypatch, point, table=prefix + "uploaded", kind=kind
            )
    finally:
        cleanup_upload_scratch(w)
        for target in ("uploaded", "landed"):
            w.execute(f"DROP TABLE IF EXISTS {w.name(prefix + target)}")
        close_world(w)


@pytest.mark.parametrize(
    ("provider", "variables"),
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
@pytest.mark.parametrize("table_format", [TableFormat.NATIVE, TableFormat.ICEBERG])
@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_provider_agent_recovers_every_mutation_boundary(
    tmp_path, provider, variables, table_format, kind, monkeypatch, request
):
    from fixtures.scd_protection import use_postgres_engine

    vendor = provider.upper()
    require_variables(vendor, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{vendor}_{name}" for name in variables}
    w = cloud_world(
        tmp_path,
        provider,
        fields,
        table_format,
        os.environ[f"ETL_CRAFT_TEST_{vendor}_SCHEMA"],
        isolated=True,
    )
    w.engine_db.dispose()
    use_postgres_engine(w, request)
    monkeypatch.setenv("CLOUD_PRIVACY_HMAC", "cloud-test-only-project-privacy")
    w.config = replace(w.config, privacy_hmac_secret="CLOUD_PRIVACY_HMAC")
    target = "etl_agent_protection_" + uuid4().hex[:10]
    source = "SELECT 1 AS id,CAST('Source' AS VARCHAR(30)) AS name,10 AS amount"
    try:
        w.setup(target, source, kind)
        params = {
            "SQL_ACTION": kind,
            "TARGET_OBJECT": target,
            "SELECT_QUERY": source,
            "MERGE_KEY": "id",
            "MERGE_COMPARE_COLUMNS": "name|amount",
        }
        w.run("load", **params)
        ctx = OperationContext(
            w.engine_db, w.config, Actor("alice", ActorKind.USER), role=ApiRole.ADMIN
        )
        check_mutation_boundaries(w, ctx, "load", target, params, monkeypatch, agent=True)
    finally:
        w.execute(f"DROP TABLE IF EXISTS {w.name(target)}")
        close_world(w)
