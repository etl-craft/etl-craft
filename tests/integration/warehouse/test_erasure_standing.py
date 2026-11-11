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
