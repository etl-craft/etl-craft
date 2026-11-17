"""Standing-entry state and crash recovery use the same contracts on each warehouse."""

import multiprocessing

import pytest
from sqlalchemy import text

from etl_craft.core.actor import acting_as
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import ConfigurationError, HandlerError
from etl_craft.handlers.erasure import run
from fixtures.actions import act
from fixtures.erasure import erasure_world as erasure_world
from fixtures.erasure import killed_erasure, ordinary_erasure

KEY = "private-world-key"


def test_preview_resends_lift_double_lift_and_registration(erasure_world):
    ctx, w = erasure_world
    args = {"table": w.name("landing"), "column": "person", "value": KEY, "reason": "request"}
    task = ordinary_erasure(ctx, w)
    preview = act(ctx, ActionName.ERASE, **args, dry_run=True)
    assert sum(t.rows for t in preview.tables) == 2
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 0
    assert sum(t.rows for t in act(ctx, ActionName.ERASE, **args).tables) == 2
    for table, column in (("landing", "person"), ("copied", "renamed")):
        w.execute(f"INSERT INTO {w.name(table)} ({column},n) VALUES (:key,3)", key=KEY)
    with acting_as(ctx.actor):
        assert run(task, ctx.engine).delete_count == 2
    act(ctx, ActionName.ERASE, **args, lift=True)
    w.execute(f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key,4)", key=KEY)
    with acting_as(ctx.actor):
        assert run(task, ctx.engine).delete_count == 0
    with pytest.raises(HandlerError, match="already lifted"):
        act(ctx, ActionName.ERASE, **args, lift=True)
    assert sum(t.rows for t in act(ctx, ActionName.ERASE, **args).tables) == 1
    listed = act(ctx, ActionName.ERASURE_LIST)
    assert len(listed.entries) == 2 and KEY not in str(listed)


def test_missing_secret_and_unknown_objects_change_nothing(erasure_world, monkeypatch):
    ctx, w = erasure_world
    args = {"table": w.name("landing"), "column": "person", "value": KEY, "reason": "request"}
    monkeypatch.delenv("ERASURE_HMAC")
    with pytest.raises(ConfigurationError, match="Hmac_secret"):
        act(ctx, ActionName.ERASE, **args)
    with acting_as(ctx.actor), pytest.raises(ConfigurationError, match="Hmac_secret"):
        run(ordinary_erasure(ctx, w), ctx.engine)
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    for changed in ({"table": w.name("missing")}, {"column": "missing"}):
        with pytest.raises(HandlerError):
            act(ctx, ActionName.ERASE, **(args | changed))
    with ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 0
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('landing')} WHERE person=:key", key=KEY) == [(1,)]


def test_process_loss_after_first_table_is_completed_by_next_run(erasure_world):
    ctx, w = erasure_world
    task = ordinary_erasure(ctx, w)
    w.warehouse.dispose()
    child = multiprocessing.get_context("spawn").Process(
        target=killed_erasure, args=(ctx.config, w.name("landing"), KEY)
    )
    try:
        child.start()
        child.join(60)
        assert child.exitcode == 137
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('landing')} WHERE person=:key", key=KEY) == [(0,)]
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('copied')} WHERE renamed=:key", key=KEY) == [(1,)]
    with acting_as(ctx.actor):
        assert run(task, ctx.engine).delete_count == 1


def test_snapshot_formats_report_old_versions_and_nothing_expires_them(erasure_world):
    import re

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from etl_craft.services.erasure import findings
    from fixtures.warehouse_retention import configure

    ctx, w = erasure_world
    args = {"table": w.name("landing"), "column": "person", "value": KEY, "reason": "request"}
    snapshots = f'{w.catalog}.{w.schema}."landing$snapshots"'
    if w.kind == "trino_iceberg":
        before = w.rows(f"SELECT snapshot_id FROM {snapshots} ORDER BY committed_at DESC")[0][0]
    statements: list[str] = []

    def spy(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        report = act(ctx, ActionName.ERASE, **args)
        with acting_as(ctx.actor):
            task = run(ordinary_erasure(ctx, w), ctx.engine)
        coverage, unbounded = findings(ctx.engine, ctx.config)
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    # Erasure states physical retention; it never expires, restores or rolls back snapshots.
    side_effects = r"expire_snapshots|remove_orphan_files|rollback_to|\bRESTORE\b|\bVACUUM\b"
    assert not [s for s in statements if re.search(side_effects, s, re.IGNORECASE)]
    landing = next(t for t in report.tables if t.table == w.name("landing"))
    recorded = next(
        t for t in task.variables["ERASURE"]["tables"] if t["table"] == w.name("landing")
    )
    assert recorded["retention"] == landing.retention
    assert coverage == []
    if w.kind in {"postgres", "duckdb"}:
        assert (landing.old_versions, landing.bounded, landing.retention) == (None, None, None)
        assert unbounded == []
        return
    assert landing.old_versions == "Iceberg snapshots" and landing.bounded is False
    assert "no expiry bound is configured" in landing.retention
    assert "SNAPSHOT_RETENTION_DAYS" in landing.retention
    message = next(m for m in unbounded if m.startswith(w.name("landing")))
    assert "with no bounded expiry; expected a snapshot expiry bound" in message
    if w.kind != "trino_iceberg":
        return
    # The current table no longer holds the key, but the snapshot before erasure still does.
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('landing')} WHERE person=:key", key=KEY) == [(0,)]
    old = f"SELECT COUNT(*) FROM {w.name('landing')} FOR VERSION AS OF {before} WHERE person=:key"
    assert w.rows(old, key=KEY) == [(1,)]
    configure(w, table="landing", SNAPSHOT_RETENTION_DAYS=7)
    bounded = act(ctx, ActionName.ERASE, **args, dry_run=True)
    landing = next(t for t in bounded.tables if t.table == w.name("landing"))
    assert landing.bounded is True and "older than 7 days" in landing.retention
    assert not [m for m in findings(ctx.engine, ctx.config)[1] if m.startswith(w.name("landing"))]
