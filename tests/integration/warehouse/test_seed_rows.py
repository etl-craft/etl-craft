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
