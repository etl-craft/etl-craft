"""A complete bounded candidate scan is required before finalizing atomic deletions."""

from dataclasses import replace

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from etl_craft.core.actor import Actor
from etl_craft.core.enums import ActionName, ActorKind
from etl_craft.core.errors import InjectedFaultError
from etl_craft.core.protection import MAX_PROTECTION_EVENTS
from etl_craft.engine.task_store import LocalTaskStore
from fixtures.actions import act
from fixtures.stewardship import configure_upload_world


def test_interrupted_paged_deletion_scan_restarts_without_recording_an_outcome(
    sql_world, monkeypatch
):
    w = sql_world
    w, owner = configure_upload_world(w, "SCD1_MERGE")
    owner = replace(owner, actor=Actor("alice", ActorKind.USER))
    rows = ",".join(
        f"({i},'person-{i}',CAST(NULL AS BIGINT))" for i in range(MAX_PROTECTION_EVENTS + 1)
    )
    seeded = w.run(
        "seed_candidates",
        SQL_ACTION="SCD1_MERGE",
        TARGET_OBJECT="uploaded",
        SELECT_QUERY=f"SELECT * FROM (VALUES {rows}) AS candidates(id,name,UPLOAD_ID)",
        MERGE_KEY="id",
        MERGE_COMPARE_COLUMNS="name",
    )
    assert seeded.insert_count == MAX_PROTECTION_EVENTS + 1
    fields = {"pipeline_code": "P", "task_code": "apply", "key": {"id": 0}}
    act(
        owner,
        ActionName.DATA_EDIT,
        **fields,
        values={"name": "person-0"},
        reason="enable protection",
    )
    act(owner, ActionName.DATA_UNLOCK, **fields, columns=("name",), reason="allow deletion")
    monkeypatch.setenv("ETL_CRAFT_FAULT", "protection.after_pending")
    with pytest.raises(InjectedFaultError):
        w.run(
            "remove",
            SQL_ACTION="DELETE_ROWS",
            TARGET_OBJECT="uploaded",
            SELECT_QUERY=f"SELECT id FROM {w.name('uploaded')}",
            MERGE_KEY="id",
            HARD_DELETE="true",
        )
    monkeypatch.delenv("ETL_CRAFT_FAULT")
    with w.engine_db.connect() as conn:
        request = conn.execute(
            text(
                "SELECT REQUEST_ID AS request_id FROM AUD_PROTECTION_EVENTS "
                "WHERE KIND='HARD_DELETE' AND STATUS='PENDING' ORDER BY EVENT_ID DESC LIMIT 1"
            )
        ).scalar_one()
    original = LocalTaskStore.protection_match
    calls = []
    statements = []
    completed_reports = []

    def interrupt(store, target, candidates):
        calls.append(candidates.cursor)
        if len(calls) == 2:
            raise InjectedFaultError("interrupted candidate scan")
        return original(store, target, candidates)

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "AS key_hash" in statement and "ETL_PROTECTION IS NOT NULL" in statement:
            statements.append(statement)

    monkeypatch.setattr(LocalTaskStore, "protection_match", interrupt)
    event.listen(Engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(InjectedFaultError, match="interrupted candidate scan"):
            act(owner, ActionName.DATA_PROVENANCE, **fields)
        with w.engine_db.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS "
                        "WHERE REQUEST_ID=:request AND STATUS<>'PENDING'"
                    ),
                    {"request": request},
                ).scalar_one()
                == 0
            )

        def complete(store, target, candidates):
            completed_reports.append(len(candidates.hashes))
            return original(store, target, candidates)

        monkeypatch.setattr(LocalTaskStore, "protection_match", complete)
        for _ in range(2):
            act(owner, ActionName.DATA_PROVENANCE, **fields)
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert len(statements) == 2
    assert completed_reports == [MAX_PROTECTION_EVENTS, 1]
    assert all("OFFSET" not in sql for sql in statements)
    assert all("ETL_PROTECTION IS NOT NULL" in sql for sql in statements)
    with w.engine_db.connect() as conn:
        assert conn.execute(
            text(
                "SELECT STATUS AS status FROM AUD_PROTECTION_EVENTS "
                "WHERE REQUEST_ID=:request AND STATUS<>'PENDING'"
            ),
            {"request": request},
        ).scalars().all() == ["ABANDONED"]
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('uploaded')}") == [(MAX_PROTECTION_EVENTS + 1,)]
    from etl_craft.core.errors import SqlGuardError

    monkeypatch.setenv("ETL_CRAFT_FAULT", "protection.after_pending")
    with pytest.raises(InjectedFaultError):
        w.run(
            "remove",
            SQL_ACTION="DELETE_ROWS",
            TARGET_OBJECT="uploaded",
            SELECT_QUERY=f"SELECT id FROM {w.name('uploaded')}",
            MERGE_KEY="id",
            HARD_DELETE="true",
        )
    monkeypatch.delenv("ETL_CRAFT_FAULT")
    w.execute(f"DELETE FROM {w.name('uploaded')} WHERE id=0")
    with pytest.raises(SqlGuardError, match="256 of 257 deletion keys matched") as mixed:
        act(owner, ActionName.DATA_PROVENANCE, **fields)
    assert "request" in str(mixed.value) and "restore a consistent warehouse backup" in str(
        mixed.value
    )
