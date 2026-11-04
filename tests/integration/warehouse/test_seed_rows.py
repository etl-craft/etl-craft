"""Declared seeds retain exact rows, merge hashes and lifecycle columns on every warehouse."""

import hashlib

import pytest

from etl_craft.core.enums import SqlAction
from etl_craft.handlers.sql.seed import replace_seed
from etl_craft.handlers.sql.session import Session
from etl_craft.warehouse.connection import warehouse_dialect


@pytest.mark.parametrize("merge", [None, SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE])
def test_seed_replacement_retains_declared_values_and_merge_shape(sql_world, merge):
    w = sql_world
    columns = (("id", "INTEGER"), ("name", "VARCHAR(40)"))
    for rows in ([{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bo"}], [{"id": 3, "name": "Cy"}]):
        with w.warehouse.begin() as conn:
            session = Session(
                conn,
                warehouse_dialect(w.config),
                catalog=w.catalog,
                action=SqlAction.CREATE_TABLE,
                target_object=f"{w.schema}.reference",
                task_run_id=0,
                params={},
            )
            try:
                replace_seed(
                    session,
                    columns,
                    rows,
                    None if merge is None else (merge, ("name",)),
                    "deployer",
                )
            finally:
                session.sweep()
        actual = w.rows(f"SELECT id,name FROM {w.name('reference')} ORDER BY id")
        assert actual == [(row["id"], row["name"]) for row in rows]
        if merge:
            result = w.rows(
                f"SELECT "
                "id,HASH_KEY,CREATED_BY,UPDATED_BY,ACTIVE_FLAG,DELETE_FLAG,"
                f"PIPELINE_RUN_ID,TASK_RUN_ID FROM {w.name('reference')} ORDER BY id"
            )
            assert w.rows(
                f"SELECT COUNT(*) FROM {w.name('reference')} "
                "WHERE ETL_PROTECTION IS NULL OR ETL_ROW_FINGERPRINT IS NULL"
            ) == [(0,)]
            assert result == [
                (
                    row["id"],
                    hashlib.md5(f"V{len(row['name'])}:{row['name']}".encode()).hexdigest(),
                    "deployer",
                    "deployer",
                    "Y",
                    "N",
                    None,
                    None,
                )
                for row in rows
            ]
    if merge:
        from etl_craft.engine.repository.hash_versions import save_hash_version

        with w.engine_db.begin() as conn:
            save_hash_version(conn, w.name("reference"), 2)
        from etl_craft.core.actor import Actor, ActorKind
        from etl_craft.core.enums import ActionName, ApiRole
        from etl_craft.services.operations import OperationContext
        from fixtures.actions import act

        w.task(
            "reference_writer",
            SQL_ACTION=merge,
            TARGET_OBJECT="reference",
            SELECT_QUERY="SELECT 3 AS id,CAST('Cy' AS VARCHAR(40)) AS name",
            MERGE_KEY="id",
            MERGE_COMPARE_COLUMNS="name",
        )
        ctx = OperationContext(
            w.engine_db, w.config, Actor("steward", ActorKind.USER), role=ApiRole.ADMIN
        )
        act(
            ctx,
            ActionName.DATA_EDIT,
            pipeline_code="P",
            task_code="reference_writer",
            key={"id": 3},
            values={"name": "Corrected"},
            reason="correct reference",
        )
        assert w.rows(f"SELECT name FROM {w.name('reference')} WHERE ACTIVE_FLAG='Y'") == [
            ("Corrected",)
        ]


def test_seed_omitted_columns_are_typed_null(sql_world, tmp_path):
    from fixtures.seed_columns import check_omitted_seed_columns

    check_omitted_seed_columns(sql_world, tmp_path / "seed")
