"""Direct renamed identifiers are deleted upstream-first on every local warehouse."""

from dataclasses import replace

from etl_craft.core.erasure import ErasureEntry
from etl_craft.handlers.erasure import apply_entries

KEY = "person-private-793"


def test_renames_people_versions_rejects_boundaries_and_resends(sql_world, monkeypatch):
    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    w.run(
        "land",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="landing",
        SELECT_QUERY="SELECT 'retained' AS person, 1 AS n",
    )
    w.execute(f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key, 2)", key=KEY)
    w.run(
        "first",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="first",
        SELECT_QUERY=f"SELECT person AS renamed, n FROM {w.name('landing')}",
    )
    w.setup("people_versions", "SELECT CAST('x' AS VARCHAR(100)) AS customer, 1 AS n", "SCD2_MERGE")
    merge = {
        "SQL_ACTION": "SCD2_MERGE",
        "TARGET_OBJECT": "people_versions",
        "SELECT_QUERY": f"SELECT renamed AS customer,n FROM {w.name('first')}",
        "MERGE_KEY": "customer",
        "MERGE_COMPARE_COLUMNS": "n",
    }
    w.run("versions", **merge)
    w.execute(f"UPDATE {w.name('first')} SET n=3 WHERE renamed=:key", key=KEY)
    w.run("versions", **merge)
    w.run(
        "rejects",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="people_versions__rejects",
        SELECT_QUERY=f"SELECT customer,n FROM {w.name('people_versions')}",
    )
    w.run(
        "hashed",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="hashed",
        SELECT_QUERY=f"SELECT UPPER(person) AS identifier FROM {w.name('landing')}",
    )
    w.run(
        "grouped",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="grouped",
        SELECT_QUERY=f"SELECT person,COUNT(*) AS n FROM {w.name('landing')} GROUP BY person",
    )
    entry = ErasureEntry(w.name("landing"), "person", KEY, "a" * 64)
    preview = apply_entries(w.engine_db, config, (entry,), dry_run=True)
    assert any(t.table == w.name("people_versions") and t.rows == 2 for t in preview.tables)
    assert any(b.table == w.name("hashed") for b in preview.unfollowed)
    assert any(b.table == w.name("grouped") for b in preview.unfollowed)
    report = apply_entries(w.engine_db, config, (entry,))
    for table, column in (
        ("landing", "person"),
        ("first", "renamed"),
        ("people_versions", "customer"),
        ("people_versions__rejects", "customer"),
    ):
        assert w.rows(f"SELECT COUNT(*) FROM {w.name(table)} WHERE {column}=:key", key=KEY) == [
            (0,)
        ]
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('hashed')}") == [(2,)]
    assert KEY not in repr(report)
    w.execute(f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key, 3)", key=KEY)
    assert sum(t.rows for t in apply_entries(w.engine_db, config, (entry,)).tables) == 1
    second = ErasureEntry(w.name("hashed"), "identifier", KEY.upper(), "b" * 64)
    assert sum(t.rows for t in apply_entries(w.engine_db, config, (second,)).tables) == 1
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('grouped')}") == [(2,)]
    grouped = ErasureEntry(w.name("grouped"), "person", KEY, "c" * 64)
    assert sum(t.rows for t in apply_entries(w.engine_db, config, (grouped,)).tables) == 1


def test_erasure_and_merge_take_the_same_target_lock(sql_world, monkeypatch):
    import threading
    from contextlib import contextmanager

    from etl_craft.handlers import sql
    from etl_craft.handlers.resources import LocalLocker
    from fixtures.races import two_at_once

    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    w.run(
        "land",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="landing",
        SELECT_QUERY="SELECT 'retained' AS person, 1 AS n",
    )
    w.execute(f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key,2)", key=KEY)
    w.setup("people", "SELECT CAST('x' AS VARCHAR(100)) AS person, 1 AS n", "SCD1_MERGE")
    params = {
        "SQL_ACTION": "SCD1_MERGE",
        "TARGET_OBJECT": "people",
        "SELECT_QUERY": f"SELECT person,n FROM {w.name('landing')}",
        "MERGE_KEY": "person",
        "MERGE_COMPARE_COLUMNS": "n",
    }
    w.run("merge", **params)
    context = w.task("merge", **params)
    entry = ErasureEntry(w.name("people"), "person", KEY, "a" * 64)
    original, active, acquired, guard = LocalLocker.hold, [], [], threading.Lock()

    @contextmanager
    def observed(self, key, name, wait_seconds):
        with original(self, key, name, wait_seconds):
            if name == f"target {w.name('people')}":
                with guard:
                    assert not active
                    active.append(name)
                    acquired.append(key)
            try:
                yield
            finally:
                if name == f"target {w.name('people')}":
                    with guard:
                        active.remove(name)

    monkeypatch.setattr(LocalLocker, "hold", observed)
    report, _ = two_at_once(
        lambda: apply_entries(w.engine_db, config, (entry,)),
        lambda: sql.run(context, w.engine_db),
        at=(LocalLocker, "hold"),
        timeout=30,
    )
    assert len(acquired) >= 2 and len(set(acquired)) == 1
    assert sum(t.rows for t in report.tables) == 1
    assert w.rows(f"SELECT COUNT(*) FROM {w.name('people')} WHERE person=:key", key=KEY) in (
        [(0,)],
        [(1,)],
    )


def test_two_direct_columns_are_one_atomic_table_selection(sql_world, monkeypatch):
    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    w.run(
        "land",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="landing",
        SELECT_QUERY="SELECT 'retained' AS person, 1 AS n",
    )
    w.execute(f"INSERT INTO {w.name('landing')} (person,n) VALUES (:key,2)", key=KEY)
    w.run(
        "copies",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="copies",
        SELECT_QUERY=f"SELECT person AS primary_id,person AS secondary_id FROM {w.name('landing')}",
    )
    entry = ErasureEntry(w.name("landing"), "person", KEY, "a" * 64)
    report = apply_entries(w.engine_db, config, (entry,))
    selected = [t for t in report.tables if t.table == w.name("copies")]
    assert len(selected) == 1 and selected[0].rows == 1
    assert w.rows(f"SELECT primary_id,secondary_id FROM {w.name('copies')}") == [
        ("retained", "retained")
    ]


def test_numeric_identifier_uses_native_bound_equality(sql_world, monkeypatch):
    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    w.run(
        "land",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT="numeric_people",
        SELECT_QUERY="SELECT 1 AS person UNION ALL SELECT 2",
    )
    report = apply_entries(
        w.engine_db, config, (ErasureEntry(w.name("numeric_people"), "person", "1", "1" * 64),)
    )
    assert sum(t.rows for t in report.tables) == 1
    assert all(t.key_hmac == "1" * 64 for t in report.tables)
    assert w.rows(f"SELECT person FROM {w.name('numeric_people')}") == [(2,)]


def test_quoted_native_identifier_keeps_its_physical_case(sql_world, monkeypatch):
    w = sql_world
    monkeypatch.setenv("ERASURE_HMAC", "test-hmac-secret")
    config = replace(w.config, erasure_hmac_secret="ERASURE_HMAC")
    from etl_craft.dialects.warehouse.erasure import column_identity
    from etl_craft.handlers.erasure import identity
    from etl_craft.warehouse.connection import warehouse_dialect

    quoted = f'{w.catalog}.{w.schema}."QuotedPeople"'
    from fixtures.metadata import add_task

    with w.engine_db.begin() as conn:
        add_task(
            conn,
            w.pipeline_id,
            "quoted",
            handler="PYTHON",
            SCRIPT_KIND="INGESTION",
            TARGET_OBJECT=quoted,
            SCRIPT_FILE="python_scripts/quoted.py",
        )
    w.execute(f'CREATE TABLE {quoted} AS SELECT 1 AS "PersonKey" UNION ALL SELECT 2')
    table = identity(config, quoted)
    column = column_identity('"PersonKey"', warehouse_dialect(config))
    report = apply_entries(w.engine_db, config, (ErasureEntry(table, column, "1", "a" * 64),))
    assert sum(t.rows for t in report.tables) == 1
    assert w.rows(f'SELECT "PersonKey" FROM {quoted}') == [(2,)]
