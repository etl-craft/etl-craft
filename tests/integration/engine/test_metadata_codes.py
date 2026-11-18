"""Metadata code checks on fresh schemas and generated commands."""

from pathlib import Path

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from etl_craft.dialects.engine import for_engine
from etl_craft.engine.queries import run_script
from fixtures.metadata import add_pipeline, add_task


@pytest.mark.parametrize(
    "code",
    ["__init__", "__finalize__", "load $(touch x); echo", "1load", "a" * 129, "task-name", "P\n"],
)
@pytest.mark.parametrize("object", ["pipeline", "task"])
def test_database_refuses_invalid_metadata_codes(engine_db, code, object):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
    with pytest.raises(IntegrityError), engine_db.engine.begin() as conn:
        if object == "pipeline":
            add_pipeline(conn, code)
        else:
            add_task(conn, pipeline, code)


@pytest.fixture
def legacy(empty_engine_db):
    engine = empty_engine_db.engine
    kind = "sqlite" if engine.dialect.name == "sqlite" else "postgres"
    schema = Path(__file__).parents[2] / "fixtures" / "schemas" / "0.1.0" / f"{kind}.sql"
    with engine.begin() as conn:
        run_script(conn, for_engine(engine).split_statements(schema.read_text("utf-8")))
    return empty_engine_db


def test_database_refuses_embedded_nul_codes(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
    error = DataError if engine_db.engine.dialect.name == "postgresql" else IntegrityError
    with pytest.raises(error), engine_db.engine.begin() as conn:
        add_task(conn, pipeline, "P\x00hidden")
