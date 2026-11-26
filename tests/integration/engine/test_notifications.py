"""Startup proves notification delivery instead of trusting a successful LISTEN."""

from dataclasses import replace

import pytest

from etl_craft.core.errors import ConfigurationError
from etl_craft.engine.notifications import check_notifications, notification_hub


def test_notification_round_trip_on_the_resolved_connection(engine_db):
    check_notifications(engine_db.config, engine_db.engine)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    "empty_engine_db",
    [pytest.param("postgresql", marks=pytest.mark.engine_postgres)],
    indirect=True,
)
def test_a_listener_that_drops_notifications_is_refused(engine_db, monkeypatch, explicit):
    cfg = engine_db.config
    if explicit:
        cfg = replace(cfg, engine=replace(cfg.engine, listen_jdbc_url=cfg.engine.jdbc_url))
    monkeypatch.setattr(engine_db.dialect, "notifications", lambda conn, timeout: iter(()))
    with pytest.raises(ConfigurationError) as caught:
        check_notifications(cfg, engine_db.engine)
    message = str(caught.value)
    assert ("Listen_jdbc_url" if explicit else "Jdbc_url") in message
    assert "no matching notification" in message
    assert "direct PostgreSQL connection or a session-mode pool" in message
    assert cfg.engine.jdbc_url in message


def test_all_waiters_share_one_listener_and_dispose_stops_it(engine_db):
    hub = notification_hub(engine_db.config, engine_db.engine)
    assert notification_hub(engine_db.config, engine_db.engine) is hub
    engine_db.engine.dispose()
    assert hub.stop.is_set()
    assert hub.thread is None or not hub.thread.is_alive()


def _signals_before_sentinel(engine_db, listener, write) -> list[str]:
    """Commit ``write``, then a unique sentinel; every signal read before it came from ``write``."""
    from uuid import uuid4

    from etl_craft.engine.notifications import CHANNEL
    from etl_craft.engine.queries import statement

    with engine_db.engine.begin() as conn:
        write(conn)
    sentinel = uuid4().hex
    with engine_db.engine.begin() as conn:
        conn.execute(statement(conn, "execution_notify"), {"channel": CHANNEL, "payload": sentinel})
    seen = []
    for channel, payload in engine_db.dialect.notifications(listener, 10):
        if channel == CHANNEL and payload == sentinel:
            return seen
        seen.append(payload)
    raise AssertionError(f"sentinel {sentinel} did not arrive; read {seen}")


@pytest.mark.parametrize(
    "empty_engine_db",
    [pytest.param("postgresql", marks=pytest.mark.engine_postgres)],
    indirect=True,
)
@pytest.mark.usefixtures("selected_default_project")
def test_wait_reasons_signal_waiting_claims_only_when_a_reason_changes(engine_db):
    from etl_craft.core.actor import current_actor
    from etl_craft.engine import transitions
    from etl_craft.engine.notifications import listener_connection
    from etl_craft.engine.placement import record_wait_reasons
    from etl_craft.engine.queries import statement
    from etl_craft.engine.run_definitions import for_run
    from fixtures.metadata import add_pipeline, add_task, start_run

    def reasons(conn):
        record_wait_reasons(conn, None, pool="default")

    with listener_connection(engine_db.config, engine_db.engine).execution_options(
        isolation_level="AUTOCOMMIT"
    ) as listener:
        listener.execute(statement(listener, "controller_listen"))
        assert _signals_before_sentinel(engine_db, listener, reasons) == []

        def queue(conn):
            pipeline = add_pipeline(conn, "P")
            task = add_task(conn, pipeline, "T", "PYTHON")
            run = start_run(conn, pipeline)
            with for_run(conn, run):
                task_run = transitions.find_or_create_task_run(conn, task, run)
                transitions.queue_attempt(conn, task_run.task_run_id, current_actor())

        assert _signals_before_sentinel(engine_db, listener, queue)
        assert _signals_before_sentinel(engine_db, listener, reasons)
        assert _signals_before_sentinel(engine_db, listener, reasons) == []
