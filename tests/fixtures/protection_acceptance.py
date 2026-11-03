"""Independent provider oracles for row locks, rehash and authenticated deletion."""

from sqlalchemy import text

from etl_craft.core.enums import ActionName
from etl_craft.services.protection import problems
from fixtures.actions import act


def check_locked_deletion(w, ctx, task, target, params):
    """Keep human rows on reload/hard delete, then account for explicit erasure."""
    base = {"pipeline_code": "P", "task_code": task, "key": {"id": 2}}
    act(ctx, ActionName.DATA_EDIT, **base, values={"name": "Human", "amount": 30}, reason="insert")
    reload = params["SELECT_QUERY"].replace("1 AS id", "2 AS id")
    w.run(task, **{**params, "SELECT_QUERY": reload})
    assert w.rows(f"SELECT name,amount FROM {w.name(target)} WHERE id=2 AND ACTIVE_FLAG='Y'") == [
        ("Human", 30)
    ]
    delete = {
        "SQL_ACTION": "DELETE_ROWS",
        "TARGET_OBJECT": target,
        "SELECT_QUERY": "SELECT 2 AS id",
        "MERGE_KEY": "id",
        "HARD_DELETE": "true",
    }
    assert w.run("remove_" + target, **delete).delete_count == 0
    act(ctx, ActionName.REHASH, target=w.name(target))
    locked = act(ctx, ActionName.DATA_PROVENANCE, **base)
    assert any(r["column_name"] == "*" and r["locked"] for r in locked.records)
    act(ctx, ActionName.ERASE, table=w.name(target), column="id", value="2", reason="request")
    assert w.rows(f"SELECT COUNT(*) FROM {w.name(target)} WHERE id=2") == [(0,)]
    erased = act(ctx, ActionName.DATA_PROVENANCE, **base)
    assert erased.records == ()
    assert any(r["event_kind"] == "ERASURE" for r in erased.history)
    assert problems(w.engine_db, w.config) == []
    # The source may legitimately resend a different, unlocked key.
    w.run(task, **{**params, "SELECT_QUERY": reload})
    assert w.run("remove_" + target, **delete).delete_count >= 1
    assert problems(w.engine_db, w.config) == []
    with w.engine_db.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT KEY_HASH AS key_hash,VALUE_HASHES AS value_hashes "
                    "FROM AUD_PROTECTION_EVENTS WHERE KEY_HASH IS NOT NULL"
                )
            )
            .mappings()
            .all()
        )
    assert all(len(r["key_hash"]) == 64 for r in rows)
    assert "Human" not in str(rows)


def check_outside_deletion(w, ctx, task, target):
    """Distinguish a warehouse-side deletion from authenticated erasure."""
    fields = {"pipeline_code": "P", "task_code": task, "key": {"id": 1}}
    act(ctx, ActionName.DATA_EDIT, **fields, values={"name": "Manual"}, reason="lock")
    w.execute(f"DELETE FROM {w.name(target)} WHERE id=1")
    findings = problems(w.engine_db, w.config)
    assert len(findings) == 1
    assert target.lower() in findings[0].lower()
    for expected in ("1 locked key hashes", "restore", "permissions"):
        assert expected in findings[0]


def check_mutation_boundaries(
    w,
    ctx,
    task,
    target,
    params,
    monkeypatch,
    *,
    agent=False,
    kinds=("edit", "unlock", "rehash", "hard_delete", "erasure"),
):
    """Replay each atomic mutation from independently checked event and row outcomes."""
    import pytest

    from etl_craft.core.errors import InjectedFaultError

    fields = {"pipeline_code": "P", "task_code": task, "key": {"id": 1}}
    for kind in kinds:
        for ordinal, point in enumerate(
            ("before_pending", "after_pending", "after_merge", "after_committed")
        ):
            act(
                ctx,
                ActionName.DATA_EDIT,
                **fields,
                values={"name": f"Before-{kind}-{ordinal}", "amount": 10},
                row_lock=kind == "unlock",
                reason="reset",
            )
            if kind == "hard_delete":
                act(ctx, ActionName.DATA_UNLOCK, **fields, columns=(), reason="release")
            with w.engine_db.connect() as conn:
                before = conn.execute(
                    text("SELECT MAX(EVENT_ID) FROM AUD_PROTECTION_EVENTS")
                ).scalar_one()
            monkeypatch.setenv("ETL_CRAFT_FAULT", "protection." + point)
            try:
                with pytest.raises(InjectedFaultError):
                    if kind == "edit":
                        act(
                            ctx,
                            ActionName.DATA_EDIT,
                            **fields,
                            values={"name": "After"},
                            reason="correct",
                        )
                    elif kind == "unlock":
                        act(ctx, ActionName.DATA_UNLOCK, **fields, columns=(), reason="release")
                    elif kind == "rehash":
                        act(ctx, ActionName.REHASH, target=w.name(target))
                    elif kind == "erasure":
                        act(
                            ctx,
                            ActionName.ERASE,
                            table=w.name(target),
                            column="id",
                            value="1",
                            reason="request",
                        )
                    else:
                        w.run(
                            "delete_" + target,
                            SQL_ACTION="DELETE_ROWS",
                            TARGET_OBJECT=target,
                            SELECT_QUERY="SELECT 1 AS id",
                            MERGE_KEY="id",
                            HARD_DELETE="true",
                        )
            except BaseException as error:
                error.add_note(f"{kind} at {point}; agent={agent}")
                raise
            finally:
                monkeypatch.delenv("ETL_CRAFT_FAULT")
            recover_mutation(w, ctx, task, target, params, agent)
            with w.engine_db.connect() as conn:
                states = (
                    conn.execute(
                        text(
                            "SELECT STATUS AS status FROM AUD_PROTECTION_EVENTS "
                            "WHERE EVENT_ID>:before AND STATUS<>'PENDING'"
                        ),
                        {"before": before},
                    )
                    .scalars()
                    .all()
                )
            assert states == (
                []
                if point == "before_pending"
                else ["ABANDONED" if point == "after_pending" else "COMMITTED"]
            )
            deleted = kind in {"hard_delete", "erasure"} and point in {
                "after_merge",
                "after_committed",
            }
            assert w.rows(
                f"SELECT COUNT(*) FROM {w.name(target)} WHERE id=1 AND ACTIVE_FLAG='Y'"
            ) == [(0 if deleted else 1,)]


def recover_mutation(w, ctx, task, target, params, agent):
    """Replay twice through the chosen fenced backend under the target lock."""
    import hashlib
    from contextlib import nullcontext

    from etl_craft.core.actor import acting_as
    from etl_craft.engine import locks
    from etl_craft.engine.task_store import LocalTaskStore
    from etl_craft.handlers.protection_recovery import recover
    from etl_craft.handlers.resources import LocalLocker
    from etl_craft.handlers.sql.session import Session
    from etl_craft.warehouse.connection import warehouse_dialect
    from fixtures.protection_agent import recovery_agent

    context = (
        recovery_agent(w, task)
        if agent
        else nullcontext(
            (
                LocalTaskStore.standalone(
                    w.engine_db, w.config, LocalLocker(w.engine_db, w.config)
                ),
                [],
            )
        )
    )
    with context as (store, replies), acting_as(ctx.actor):
        lock = locks.target(w.name(target), w.catalog)
        with store.hold(lock.key, lock.name, 30), w.warehouse.begin() as conn:
            session = Session(
                conn,
                warehouse_dialect(w.config),
                catalog=w.catalog,
                action=params["SQL_ACTION"],
                target_object=w.name(target),
                task_run_id=0,
                params={},
            )
            session.protection_store = store
            recover(session, store)
            recover(session, store)
        assert hashlib.md5(b"V1:1").hexdigest() not in str(replies)
