"""A real configured SCD target shared by protection and crash tests."""

from dataclasses import replace

from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActorKind, ApiRole
from etl_craft.services.operations import OperationContext


def prepare(w, kind, compare="name|amount", *, source=None):
    source = source or "SELECT 1 AS id, CAST('Source' AS VARCHAR(30)) AS name, 10 AS amount"
    w.setup("protected", source, kind)
    params = {
        "SQL_ACTION": kind,
        "TARGET_OBJECT": "protected",
        "SELECT_QUERY": source,
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": compare,
    }
    w.run("load", **params)
    ctx = OperationContext(
        w.engine_db, w.config, Actor("alice", ActorKind.USER), role=ApiRole.ADMIN
    )
    return ctx, params


def use_postgres_engine(w, request):
    from fixtures.engine_db import prepare_postgres_engine_db
    from fixtures.metadata import add_pipeline, start_run

    db = request.getfixturevalue("postgres_database")
    prepare_postgres_engine_db(db, request.getfixturevalue("postgres_schema_template"))
    w.config = replace(w.config, engine=db.config.engine)
    w.engine_db = db.engine
    with db.engine.begin() as conn:
        w.pipeline_id = add_pipeline(conn, "P")
        w.pipeline_run_id = start_run(conn, w.pipeline_id)
