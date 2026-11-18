"""Every change to a ``CFG_`` row is a typed version in its history table, on both Engine DBs,
and ``AUD_METADATA_CHANGES`` gives each change's before and after values from those versions."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.time import as_utc
from fixtures.metadata import add_pipeline, add_task

ALICE = Actor("github:alice", ActorKind.USER)


def document(value):
    return value if value is None or isinstance(value, dict) else json.loads(value)


def changes(conn, table):
    rows = conn.execute(
        text(
            "SELECT CHANGE_ID AS change_id, OPERATION AS operation, ACTOR AS actor, "
            "ROW_KEY AS row_key, BEFORE_JSON AS before_json, AFTER_JSON AS after_json "
            "FROM AUD_METADATA_CHANGES WHERE TABLE_NAME = :table ORDER BY CHANGE_ID"
        ),
        {"table": table},
    ).mappings()
    return [
        {
            **row,
            "before_json": document(row["before_json"]),
            "after_json": document(row["after_json"]),
        }
        for row in rows
    ]


def test_each_change_is_a_typed_version_and_the_view_gives_before_and_after(engine_db):
    with acting_as(ALICE), engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "SALES")
        task = add_task(conn, pipeline, "load", NOTE="first")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET CATCHUP = 'Y' WHERE PIPELINE_ID = :p"), {"p": pipeline}
        )
        conn.execute(text("DELETE FROM CFG_TASK_PARAMETERS WHERE TASK_ID = :t"), {"t": task})
    with engine_db.engine.connect() as conn:
        versions = conn.execute(
            text(
                "SELECT OPERATION AS operation, ACTOR AS actor, ACTOR_KIND AS kind, "
                "PIPELINE_CODE AS code, CATCHUP AS catchup, CURRENT_FLAG AS current, "
                "VALID_FROM AS valid_from, VALID_TO AS valid_to FROM AUD_CFG_PIPELINES_HISTORY "
                "ORDER BY CHANGE_ID"
            )
        ).all()
        assert [tuple(row)[:6] for row in versions] == [
            ("INSERT", "github:alice", "USER", "SALES", "N", "N"),
            ("UPDATE", "github:alice", "USER", "SALES", "Y", "Y"),
        ]
        first, second = versions
        assert as_utc(first.valid_to) == as_utc(second.valid_from)
        assert as_utc(second.valid_to).year == 9999
        removed = conn.execute(
            text(
                "SELECT OPERATION AS operation, CURRENT_FLAG AS current FROM "
                "AUD_CFG_TASK_PARAMETERS_HISTORY WHERE TASK_ID = :t ORDER BY CHANGE_ID"
            ),
            {"t": task},
        ).all()
        assert [tuple(row) for row in removed] == [("INSERT", "N"), ("DELETE", "N")]
        inserted, updated = changes(conn, "CFG_PIPELINES")
        assert (inserted["operation"], inserted["before_json"]) == ("INSERT", None)
        assert updated["row_key"] == str(pipeline)
        assert (updated["before_json"]["catchup"], updated["after_json"]["catchup"]) == ("N", "Y")
        [*_, deleted] = changes(conn, "CFG_TASK_PARAMETERS")
        assert (deleted["operation"], deleted["after_json"]) == ("DELETE", None)
        assert deleted["before_json"]["parameter_value"] == "first"
        ids = [
            row["change_id"]
            for row in conn.execute(
                text("SELECT CHANGE_ID AS change_id FROM AUD_METADATA_CHANGES ORDER BY CHANGE_ID")
            ).mappings()
        ]
        assert len(ids) == len(set(ids))
    for statement in (
        "UPDATE AUD_CFG_PIPELINES_HISTORY SET CATCHUP = 'N'",
        "UPDATE AUD_CFG_PIPELINES_HISTORY SET CURRENT_FLAG = 'Y' WHERE CURRENT_FLAG = 'N'",
        "UPDATE AUD_CFG_PIPELINES_HISTORY SET CURRENT_FLAG = 'N', PIPELINE_NAME = 'x' "
        "WHERE CURRENT_FLAG = 'Y'",
        "DELETE FROM AUD_CFG_PIPELINES_HISTORY",
    ):
        with (
            pytest.raises(DBAPIError, match=r"immutable|append-only"),
            acting_as(ALICE),
            engine_db.engine.begin() as conn,
        ):
            conn.execute(text(statement))
