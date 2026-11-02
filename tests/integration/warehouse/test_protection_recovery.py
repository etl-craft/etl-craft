"""Killed writers recover from the warehouse evidence, never from a guessed status."""

import multiprocessing
from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.enums import ActionName
from fixtures.actions import act
from fixtures.lock_fencing import expire_leases
from fixtures.protection_crashes import mutate
from fixtures.scd_protection import prepare, use_postgres_engine
from fixtures.sql_warehouse import warehouses


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
@pytest.mark.parametrize("kind", ["edit", "unlock", "rehash", "erasure", "hard_delete"])
@pytest.mark.parametrize(
    "point",
    [
        "protection.before_pending",
        "protection.after_pending",
        "protection.after_merge",
        "protection.after_committed",
    ],
)
def test_killed_mutation_recovers_once_from_warehouse_evidence(
    sql_world, request, monkeypatch, engine_kind, kind, point
):
    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    monkeypatch.setenv("ERASURE_HMAC", "test-only-hmac")
    w.config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    ctx, _ = prepare(w, "SCD2_MERGE")
    act(
        ctx,
        ActionName.DATA_EDIT,
        pipeline_code="P",
        task_code="load",
        key={"id": 1},
        values={"name": "Before"},
        reason="correct",
    )
    context = None
    if kind == "hard_delete":
        act(
            ctx,
            ActionName.DATA_UNLOCK,
            pipeline_code="P",
            task_code="load",
            key={"id": 1},
            reason="delete",
            columns=(),
        )
        context = w.task(
            "remove",
            SQL_ACTION="DELETE_ROWS",
            TARGET_OBJECT="protected",
            SELECT_QUERY="SELECT 1 AS id",
            MERGE_KEY="id",
            HARD_DELETE="true",
        )
    with w.engine_db.connect() as conn:
        before = conn.execute(text("SELECT MAX(EVENT_ID) FROM AUD_PROTECTION_EVENTS")).scalar_one()
    w.warehouse.dispose()
    process = multiprocessing.get_context("spawn").Process(
        target=mutate, args=(w.config, kind, w.name("protected"), point, context)
    )
    try:
        process.start()
        process.join(60)
        assert process.exitcode == 137, (kind, point, process.exitcode)
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
    expire_leases(w.engine_db)
    for _ in range(2):
        act(ctx, ActionName.DATA_PROVENANCE, pipeline_code="P", task_code="load", key={"id": 1})
    with w.engine_db.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT STATUS AS status,REQUEST_ID AS request_id,"
                    "RECOVERY_ACTOR AS recovery_actor "
                    "FROM AUD_PROTECTION_EVENTS WHERE EVENT_ID>:before ORDER BY EVENT_ID"
                ),
                {"before": before},
            )
            .mappings()
            .all()
        )
    if point == "protection.before_pending":
        assert rows == []
    else:
        finals = [r for r in rows if r["status"] != "PENDING"]
        assert len(finals) == 1
        expected = "ABANDONED" if point == "protection.after_pending" else "COMMITTED"
        assert finals[0]["status"] == expected
        assert all(r["request_id"] == finals[0]["request_id"] for r in rows)
        if point != "protection.after_committed":
            assert finals[0]["recovery_actor"] == "alice"


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
def test_two_fenced_recovery_holders_append_one_final_status(
    sql_world, request, monkeypatch, engine_kind
):
    from etl_craft.core.errors import InjectedFaultError
    from etl_craft.handlers.resources import LocalLocker
    from fixtures.races import two_at_once

    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    ctx, _ = prepare(w, "SCD1_MERGE")
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": 1}}
    monkeypatch.setenv("ETL_CRAFT_FAULT", "protection.after_pending")
    with pytest.raises(InjectedFaultError):
        act(ctx, ActionName.DATA_EDIT, **fields, values={"name": "Human"}, reason="correct")
    monkeypatch.delenv("ETL_CRAFT_FAULT")
    with w.engine_db.connect() as conn:
        pending = conn.execute(
            text(
                "SELECT REQUEST_ID AS request_id FROM AUD_PROTECTION_EVENTS "
                "WHERE STATUS='PENDING' ORDER BY EVENT_ID LIMIT 1"
            )
        ).scalar_one()

    def recover():
        return act(ctx, ActionName.DATA_PROVENANCE, **fields)

    two_at_once(recover, recover, at=(LocalLocker, "hold"))
    with w.engine_db.connect() as conn:
        statuses = (
            conn.execute(
                text(
                    "SELECT STATUS AS status FROM AUD_PROTECTION_EVENTS "
                    "WHERE REQUEST_ID=:request AND STATUS<>'PENDING'"
                ),
                {"request": pending},
            )
            .scalars()
            .all()
        )
    assert statuses == ["ABANDONED"]


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
def test_standalone_event_fence_rechecks_engine_db_lease(sql_world, request, engine_kind):
    from datetime import UTC, datetime, timedelta

    from etl_craft.config.targets import active_catalog
    from etl_craft.core.enums_protection import ProtectionKind, ProtectionStatus
    from etl_craft.core.errors import StaleTransitionError
    from etl_craft.core.protection import ProtectionEvent, ProtectionReport
    from etl_craft.engine import locks
    from etl_craft.engine.task_store import LocalTaskStore
    from etl_craft.handlers.resources import LocalLocker

    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    locker = LocalLocker(w.engine_db, w.config)
    store = LocalTaskStore.standalone(w.engine_db, w.config, locker)
    lock = locks.target(w.name("people"), active_catalog(w.config))
    with lock.hold(locker):
        with w.engine_db.begin() as conn:
            conn.execute(
                text("UPDATE AUD_RESOURCE_LOCKS SET LEASE_EXPIRES_AT=:past WHERE LOCK_KEY=:key"),
                {"past": datetime.now(UTC) - timedelta(seconds=60), "key": lock.key},
            )
        with pytest.raises(StaleTransitionError, match="target-lock check failed"):
            store.protection_event(
                w.name("people"),
                ProtectionReport(
                    ProtectionStatus.PENDING,
                    (ProtectionEvent(ProtectionKind.WRITE, "a" * 32, ("name",), ("b" * 32,)),),
                ),
            )
    with w.engine_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_PROTECTION_EVENTS")).scalar_one() == 0


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
@pytest.mark.parametrize("point", ["protection.after_pending", "protection.after_merge"])
def test_controller_start_recovers_with_explicit_system_actor(
    sql_world, request, engine_kind, point
):
    from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
    from etl_craft.services.protection import startup

    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    _, _ = prepare(w, "SCD1_MERGE")
    w.warehouse.dispose()
    process = multiprocessing.get_context("spawn").Process(
        target=mutate, args=(w.config, "edit", w.name("protected"), point)
    )
    try:
        process.start()
        process.join(60)
        assert process.exitcode == 137
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
    expire_leases(w.engine_db)
    with acting_as(SYSTEM_ACTOR):
        startup(w.engine_db, w.config)
        startup(w.engine_db, w.config)
    with w.engine_db.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT STATUS AS status,RECOVERY_ACTOR AS recovery_actor "
                    "FROM AUD_PROTECTION_EVENTS "
                    "WHERE STATUS<>'PENDING' ORDER BY EVENT_ID"
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == ("COMMITTED" if point.endswith("after_merge") else "ABANDONED")
    assert rows[0]["recovery_actor"] == SYSTEM_ACTOR.name


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
@pytest.mark.parametrize("point", ["protection.after_pending", "protection.after_merge"])
def test_retry_attempt_recovers_lost_creator_and_retains_both_attempts(
    sql_world, request, engine_kind, point
):
    from datetime import UTC, datetime, timedelta

    from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
    from etl_craft.engine import transitions
    from etl_craft.engine.resource_locks import attempt_scope
    from etl_craft.handlers import sql

    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    ctx, params = prepare(w, "SCD1_MERGE")
    act(
        ctx,
        ActionName.DATA_EDIT,
        pipeline_code="P",
        task_code="load",
        key={"id": 1},
        values={"name": "Human"},
        reason="correct",
    )
    context = w.task(
        "load", **{**params, "SELECT_QUERY": params["SELECT_QUERY"].replace("10 AS", "20 AS")}
    )
    with acting_as(SYSTEM_ACTOR), w.engine_db.begin() as conn:
        first = transitions.queue_attempt(conn, context.task_run_id, SYSTEM_ACTOR)
        transitions.claim_attempt(
            conn,
            first,
            SYSTEM_ACTOR,
            owner="owner-A",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
    a = replace(context, attempt_id=first, owner="owner-A")
    w.warehouse.dispose()
    process = multiprocessing.get_context("spawn").Process(
        target=mutate, args=(w.config, "reload", w.name("protected"), point, a)
    )
    try:
        process.start()
        process.join(60)
        assert process.exitcode == 137
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
    expire_leases(w.engine_db)
    with acting_as(SYSTEM_ACTOR), w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE AUD_TASK_ATTEMPTS SET LEASE_EXPIRES_AT=:past WHERE ATTEMPT_ID=:id"),
            {"past": datetime.now(UTC) - timedelta(seconds=60), "id": first},
        )
        transitions.lose_attempt(conn, first, SYSTEM_ACTOR, owner="owner-A")
        second = transitions.queue_attempt(conn, context.task_run_id, SYSTEM_ACTOR)
        transitions.claim_attempt(
            conn,
            second,
            SYSTEM_ACTOR,
            owner="owner-B",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
    b = replace(context, attempt_id=second, owner="owner-B")
    with acting_as(SYSTEM_ACTOR), attempt_scope(second, "owner-B"):
        sql.run(b, w.engine_db)
        sql.run(b, w.engine_db)
    with w.engine_db.connect() as conn:
        recovered = (
            conn.execute(
                text(
                    "SELECT STATUS AS status,ATTEMPT_ID AS attempt_id,"
                    "RECOVERING_ATTEMPT_ID AS recovering_attempt_id,"
                    "RECOVERY_ACTOR AS recovery_actor "
                    "FROM AUD_PROTECTION_EVENTS WHERE ATTEMPT_ID=:first AND STATUS<>'PENDING'"
                ),
                {"first": first},
            )
            .mappings()
            .all()
        )
    assert len(recovered) == 1
    assert recovered[0]["attempt_id"] == first
    assert recovered[0]["recovering_attempt_id"] == second
    assert recovered[0]["recovery_actor"] == SYSTEM_ACTOR.name
    assert recovered[0]["status"] == ("COMMITTED" if point.endswith("after_merge") else "ABANDONED")


@warehouses("duckdb")
@pytest.mark.parametrize("engine_kind", ["sqlite", "postgresql"])
def test_controller_defers_an_inaccessible_project_then_recovers_before_next_write(
    sql_world, request, monkeypatch, engine_kind, caplog
):
    import logging

    from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
    from etl_craft.core.errors import ConfigurationError, InjectedFaultError
    from etl_craft.services import protection

    w = sql_world
    if engine_kind == "postgresql":
        use_postgres_engine(w, request)
    ctx, params = prepare(w, "SCD1_MERGE")
    monkeypatch.setenv("ETL_CRAFT_FAULT", "protection.after_pending")
    with pytest.raises(InjectedFaultError):
        act(
            ctx,
            ActionName.DATA_EDIT,
            pipeline_code="P",
            task_code="load",
            key={"id": 1},
            values={"name": "Human"},
            reason="correct",
        )
    monkeypatch.delenv("ETL_CRAFT_FAULT")
    opened = []

    def unavailable(*args, **kwargs):
        opened.append(True)
        raise ConfigurationError("warehouse credentials exist only on the agent")

    caplog.set_level(logging.INFO, logger="etl_craft.services.protection")
    with monkeypatch.context() as patch, acting_as(SYSTEM_ACTOR):
        patch.setattr(protection, "open_warehouse", unavailable)
        protection.startup(w.engine_db, w.config)
    assert opened == [True]
    assert sum("protection recovery deferred" in r.message for r in caplog.records) == 1
    w.run("load", **params)
    with w.engine_db.connect() as conn:
        statuses = (
            conn.execute(
                text("SELECT STATUS AS status FROM AUD_PROTECTION_EVENTS WHERE STATUS<>'PENDING'")
            )
            .scalars()
            .all()
        )
    assert statuses == ["ABANDONED"]
