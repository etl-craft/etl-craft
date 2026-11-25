"""Omitted seed fields retain declared types without changing blank cells."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlglot import Dialect, exp

from etl_craft.core.enums import SqlAction
from etl_craft.core.errors import MetadataError
from etl_craft.engine import locks
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.engine.task_store import LocalTaskStore
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.seed import replace_seed
from etl_craft.handlers.sql.session import Session
from etl_craft.services.seeds import Seed, cast_rows
from etl_craft.warehouse.connection import warehouse_dialect


@contextmanager
def seed_session(w, target):
    locker = LocalLocker(w.engine_db, w.config)
    with (
        locks.target(target, w.catalog).hold(locker),
        selected_project(1),
        w.warehouse.connect() as conn,
    ):
        session = Session(
            conn,
            warehouse_dialect(w.config),
            catalog=w.catalog,
            action=SqlAction.CREATE_TABLE,
            target_object=target,
            task_run_id=0,
            params={},
        )
        session.protection_store = LocalTaskStore.standalone(w.engine_db, w.config, locker)
        try:
            yield session
        finally:
            session.sweep()
        conn.commit()
        session.verify_row_ids()


def check_omitted_seed_columns(w, folder):
    folder.mkdir(exist_ok=True)
    path = folder / "data.csv"
    path.write_text("id|name\n1|\n2|Ada\n")
    dialect = warehouse_dialect(w.config)
    name = "seed_" + uuid4().hex[:12]
    normalize = Dialect.get_or_raise(dialect.sqlglot_dialect).normalize_identifier
    columns = tuple(
        (normalize(exp.to_identifier(column)).name, kind)
        for column, kind in (
            ("id", "INTEGER"),
            ("name", dialect.string_type),
            ("upload_id", "BIGINT"),
        )
    )
    seed = Seed(
        folder,
        (w.catalog, w.schema, name),
        columns,
        ("id",),
        "test",
    )
    try:
        with seed_session(w, f"{w.schema}.{name}") as session:
            values = cast_rows(session.conn, seed)
            assert [{key.lower(): value for key, value in row.items()} for row in values] == [
                {"id": 1, "name": "", "upload_id": None},
                {"id": 2, "name": "Ada", "upload_id": None},
            ]
            replace_seed(session, seed.columns, values, None, "seed-deployer")
        assert w.rows(f"SELECT id,name,upload_id FROM {w.name(name)} ORDER BY id") == [
            (1, "", None),
            (2, "Ada", None),
        ]
        for header, column, remedy in [
            ("name", "id", "include"),
            ("id|foreign", "foreign", "declare"),
        ]:
            path.write_text(header + "\n")
            with pytest.raises(MetadataError) as error:
                seed.rows()
            assert all(part in str(error.value) for part in (seed.target, column, remedy))
    finally:
        with w.warehouse.begin() as conn:
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {w.name(name)}")
