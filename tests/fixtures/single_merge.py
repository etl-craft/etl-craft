"""Independent rows and target-statement observations for atomic SCD mutations."""

import hashlib
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine

from fixtures.sql_merges import merge_rows


@contextmanager
def target_mutations(world, target, *, fail=False):
    statements = []
    name = world.name(target).upper()

    def observe(conn, cursor, statement, parameters, context, executemany):
        upper = " ".join(statement.upper().split())
        if any(
            upper.startswith(f"{verb} {name} ")
            for verb in ("MERGE INTO", "UPDATE", "INSERT INTO", "DELETE FROM")
        ):
            statements.append(upper)
            if fail:
                return statement + " INVALID MERGE SYNTAX", parameters
        return statement, parameters

    event.listen(Engine, "before_cursor_execute", observe, retval=True)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", observe)


def check_single_merge(world, kind, target="single_merge_people"):
    w = world
    initial = "SELECT 1 AS id,CAST('old' AS VARCHAR(20)) AS name UNION ALL SELECT 2,'same'"
    w.setup(target, initial, kind)
    params = {
        "SQL_ACTION": kind,
        "TARGET_OBJECT": target,
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    w.run("seed_atomic", SELECT_QUERY=initial, **params)
    before = merge_rows(w, target)
    w.new_run()
    source = (
        "SELECT 1 AS id,CAST('new' AS VARCHAR(20)) AS name "
        "UNION ALL SELECT 2,'same' UNION ALL SELECT 3,'add'"
    )
    with target_mutations(w, target) as statements:
        result = w.run("atomic", SELECT_QUERY=source, **params)
    assert len(statements) == 1, statements
    assert statements[0].startswith("MERGE INTO "), statements
    expected_inserts = 2 if kind == "SCD2_MERGE" else 1
    assert result.insert_count == expected_inserts
    assert result.update_count == 1
    assert result.rows_written == expected_inserts + 1
    rows = merge_rows(w, target)
    expected = [(1, "new", "Y"), (2, "same", "Y"), (3, "add", "Y")]
    if kind == "SCD2_MERGE":
        expected.append((1, "old", "N"))
    assert sorted((r["id"], r["name"], r["active_flag"]) for r in rows) == sorted(expected)
    assert len({r["row_id"] for r in rows}) == len(rows)
    assert next(r for r in rows if r["id"] == 2) == next(r for r in before if r["id"] == 2)
    for row in rows:
        assert (
            row["hash_key"]
            == hashlib.md5(f"V{len(row['name'])}:{row['name']}".encode()).hexdigest()
        )
        assert row["delete_flag"] == "N"
        if row["id"] != 2:
            assert row["pipeline_run_id"] == w.pipeline_run_id
            assert row["update_date"] >= row["create_date"]
    with target_mutations(w, target) as statements:
        again = w.run("atomic", SELECT_QUERY=source, **params)
    assert len(statements) == 1
    assert again.insert_count == again.update_count == again.rows_written == 0
    assert merge_rows(w, target) == rows
