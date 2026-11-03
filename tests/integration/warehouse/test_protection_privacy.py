"""Private event identities and authenticated deletions agree on every local warehouse."""

from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.enums import ActionName
from etl_craft.core.erasure import ErasureEntry
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.privacy import PrivacyDomain, digest
from etl_craft.handlers.erasure import apply_entries
from etl_craft.services.protection import problems
from fixtures.actions import act
from fixtures.scd_protection import prepare


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_erased_locked_subject_keeps_only_private_events_and_no_missing_key_finding(
    sql_world, caplog, kind
):
    w = sql_world
    owner, _ = prepare(w, kind)
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": 1}}
    edited = act(
        owner, ActionName.DATA_EDIT, **fields, values={"name": "private-person"}, reason="fix"
    )
    private_key = next(r["key_hash"] for r in edited.records if r["column_name"] == "name")
    assert len(private_key) == 64
    apply_entries(w.engine_db, w.config, (ErasureEntry(w.name("protected"), "id", "1", "a" * 64),))
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('protected')}") == [(0,)]
    assert problems(w.engine_db, w.config) == []
    history = act(owner, ActionName.DATA_PROVENANCE, **fields)
    assert history.records == ()
    assert any(r["event_kind"] == "ERASURE" for r in history.history)
    with w.engine_db.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT KEY_HASH AS key_hash,VALUE_HASHES AS value_hashes "
                    "FROM AUD_PROTECTION_EVENTS"
                )
            )
            .mappings()
            .all()
        )
    assert all(r["key_hash"] is None or len(r["key_hash"]) == 64 for r in rows)
    import hashlib

    offline_guess = hashlib.md5(b"V1:1").hexdigest()
    assert offline_guess not in str(rows) + caplog.text + str(history.history)
    assert "private-person" not in str(rows) + caplog.text


def test_changed_privacy_secret_refuses_provenance_and_doctor(sql_world, monkeypatch):
    w = sql_world
    owner, _ = prepare(w, "SCD1_MERGE")
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": 1}}
    act(owner, ActionName.DATA_EDIT, **fields, values={"name": "private"}, reason="fix")
    monkeypatch.setenv("WRONG_PRIVACY", "wrong")
    config = replace(w.config, privacy_hmac_secret="WRONG_PRIVACY")
    for read in (
        lambda: act(replace(owner, config=config), ActionName.DATA_PROVENANCE, **fields),
        lambda: problems(w.engine_db, config),
    ):
        with pytest.raises(ConfigurationError) as error:
            read()
        for part in ("default", "Privacy.Hmac_secret", "differs", "restore the original secret"):
            assert part in str(error.value)
    assert digest("wrong", PrivacyDomain.CHECK) not in str(error.value)


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_provider_locked_deletion_and_rehash_contract(sql_world, kind):
    from fixtures.protection_acceptance import check_locked_deletion

    ctx, params = prepare(sql_world, kind)
    check_locked_deletion(sql_world, ctx, "load", "protected", params)


def test_driver_failure_never_prints_private_staging_fingerprints(sql_world, caplog):
    import hashlib
    import traceback

    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import DBAPIError

    from etl_craft.core.errors import HandlerError

    w = sql_world
    owner, _ = prepare(w, "SCD1_MERGE")
    fingerprint = hashlib.md5(b"V1:1").hexdigest()
    seen = []

    class DriverError(Exception):
        sqlstate = "22000"

        def __str__(self):
            return "injected staging failure: " + fingerprint

    def fail(conn, cursor, statement, parameters, context, executemany):
        if fingerprint in str(parameters):
            seen.append(True)
            cause = DriverError()
            raise DBAPIError(statement, parameters, cause, False) from cause

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(HandlerError) as error:
            act(
                owner,
                ActionName.DATA_EDIT,
                pipeline_code="P",
                task_code="load",
                key={"id": 1},
                values={"name": "private"},
                reason="fix",
            )
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert seen
    output = "".join(traceback.format_exception(error.value)) + caplog.text
    assert fingerprint not in output
    from etl_craft.core.enums import FailureClass
    from etl_craft.execution.classify import classify_failure

    failure = classify_failure(error.value, w.config)
    assert (failure.kind, failure.source, failure.code) == (
        FailureClass.PERMANENT,
        "DriverError",
        "22000",
    )
    with w.engine_db.connect() as conn:
        rows = conn.execute(text("SELECT KEY_HASH AS key_hash FROM AUD_PROTECTION_EVENTS")).all()
    assert fingerprint not in str(rows)


def test_protected_sql_binds_hostile_values_and_refuses_hostile_controls(sql_world):
    from etl_craft.core.errors import HandlerError, UsageError

    w = sql_world
    owner, params = prepare(w, "SCD1_MERGE")
    value = "x'); DROP TABLE protected; --"
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": 1}}
    act(owner, ActionName.DATA_EDIT, **fields, values={"name": value}, reason="literal")
    w.run("load", **params)
    assert w.rows(f"SELECT name FROM {w.name('protected')}") == [(value,)]
    for parameter in ("MERGE_KEY", "MERGE_COMPARE_COLUMNS"):
        with pytest.raises(HandlerError):
            w.run("hostile_control", **{**params, parameter: "id); DROP TABLE protected; --"})
    with pytest.raises(UsageError):
        act(
            owner,
            ActionName.DATA_EDIT,
            **{**fields, "key": {"id; DROP TABLE protected": 1}},
            values={"name": "forged"},
            reason="bad key",
        )
    with pytest.raises((HandlerError, UsageError)):
        act(
            owner,
            ActionName.DATA_EDIT,
            **{**fields, "key": {"id": value}},
            values={"name": "forged"},
            reason="bound hostile key",
        )
    with pytest.raises(HandlerError, match="expected BOOLEAN"):
        w.run(
            "hostile_control",
            **{
                **params,
                "SELECT_QUERY": params["SELECT_QUERY"] + ",CAST('maybe' AS VARCHAR(10)) AS LOCKED",
            },
        )
    assert w.rows(f"SELECT name FROM {w.name('protected')}") == [(value,)]
    with w.engine_db.connect() as conn:
        events = conn.execute(
            text("SELECT VALUE_HASHES AS value_hashes FROM AUD_PROTECTION_EVENTS")
        ).all()
    assert value not in str(events)


@pytest.mark.parametrize("kind", ["edit", "unlock", "rehash", "HARD_DELETE", "ERASURE"])
def test_agent_recovers_atomic_deletion_from_private_candidates(
    sql_world, request, monkeypatch, kind, caplog
):
    import hashlib

    from fixtures.protection_acceptance import check_mutation_boundaries
    from fixtures.scd_protection import use_postgres_engine

    w = sql_world
    use_postgres_engine(w, request)
    owner, params = prepare(w, "SCD1_MERGE")
    check_mutation_boundaries(
        w, owner, "load", "protected", params, monkeypatch, agent=True, kinds=(kind.lower(),)
    )
    assert hashlib.md5(b"V1:1").hexdigest() not in caplog.text


def test_missing_privacy_secret_refuses_activation_before_target_write(sql_world):
    from fixtures.single_merge import target_mutations

    w = sql_world
    owner, _ = prepare(w, "SCD1_MERGE")
    owner = replace(owner, config=replace(w.config, privacy_hmac_secret=None))
    with target_mutations(w, "protected") as writes, pytest.raises(ConfigurationError) as error:
        act(
            owner,
            ActionName.DATA_EDIT,
            pipeline_code="P",
            task_code="load",
            key={"id": 1},
            values={"name": "private"},
            reason="correct",
        )
    assert writes == []
    for part in ("default", "Privacy.Hmac_secret", "missing", "configure"):
        assert part in str(error.value)
    assert w.rows(f"SELECT name,amount FROM {w.name('protected')}") == [("Source", 10)]


@pytest.mark.parametrize("kind", ["SCD1_MERGE", "SCD2_MERGE"])
def test_physical_row_events_never_become_another_business_keys_provenance(sql_world, kind):
    w = sql_world
    owner, _ = prepare(
        w, kind, source="SELECT 42 AS id,CAST('Source' AS VARCHAR(30)) AS name,10 AS amount"
    )
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": 42}}
    act(owner, ActionName.DATA_EDIT, **fields, values={"name": "Private"}, reason="correct")
    act(owner, ActionName.REHASH, target=w.name("protected"))
    other = {**fields, "key": {"id": 1}}
    history = act(owner, ActionName.DATA_PROVENANCE, **other)
    assert history.records == history.history == ()
    act(
        owner,
        ActionName.ERASE,
        table=w.name("protected"),
        column="ROW_ID",
        value="1",
        reason="request",
    )
    history = act(owner, ActionName.DATA_PROVENANCE, **other)
    assert history.records == history.history == ()


@pytest.mark.parametrize("case", ["edit", "unlock", "provenance", "refusal"])
def test_failed_or_refused_operations_do_not_retain_private_inputs(sql_world, caplog, case):
    import traceback

    from etl_craft.core.enums import ApiRole
    from etl_craft.core.errors import HandlerError, PermissionDeniedError

    w = sql_world
    owner, _ = prepare(w, "SCD1_MERGE")
    act(
        owner,
        ActionName.DATA_EDIT,
        pipeline_code="P",
        task_code="load",
        key={"id": 1},
        values={"name": "warmup"},
        reason="activate",
    )
    private = "private-person-identifier"
    fields = {"pipeline_code": "P", "task_code": "load", "key": {"id": private}}
    if case == "edit":
        action = ActionName.DATA_EDIT
        fields.update(key={"id": 1}, values={"amount": private}, reason="replace " + private)
    elif case == "unlock":
        action = ActionName.DATA_UNLOCK
        fields.update(columns=("name",), reason="release " + private)
    elif case == "provenance":
        action = ActionName.DATA_PROVENANCE
    else:
        action = ActionName.DATA_EDIT
        owner = replace(owner, role=ApiRole.VIEWER)
        fields.update(values={"name": private}, reason="refuse " + private)
    with pytest.raises(PermissionDeniedError if case == "refusal" else HandlerError) as refused:
        act(owner, action, **fields)
    assert private not in "".join(traceback.format_exception(refused.value)) + caplog.text
    with w.engine_db.connect() as conn:
        audits = (
            conn.execute(text("SELECT ARGUMENTS AS arguments FROM AUD_ACTIONS")).scalars().all()
        )
        events = (
            conn.execute(
                text(
                    "SELECT KEY_HASH AS key_hash,VALUE_HASHES AS value_hashes "
                    "FROM AUD_PROTECTION_EVENTS"
                )
            )
            .mappings()
            .all()
        )
    assert private not in str(audits) + str(events)
