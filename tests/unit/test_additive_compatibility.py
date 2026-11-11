"""The stable baseline gates later SQL; no released 0.9 binary exists yet."""

import subprocess
from pathlib import Path

import pytest

from etl_craft.core.errors import MigrationError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dialect", ["postgres", "sqlite"])
@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE EXAMPLE;",
        "-- etl-craft: rebuild-metadata\nCREATE TABLE EXAMPLE (ID INT);",
        "ALTER TABLE EXAMPLE RENAME TO REPLACEMENT;",
        "ALTER TABLE EXAMPLE DROP COLUMN VALUE;",
        "ALTER TABLE EXAMPLE ALTER COLUMN VALUE TYPE INTEGER;",
        "ALTER TABLE EXAMPLE ADD COLUMN VALUE TEXT NOT NULL;",
        "ALTER TABLE EXAMPLE ADD COLUMN VALUE SERIAL;",
        "ALTER TABLE EXAMPLE ADD COLUMN VALUE TEXT NOT NULL DEFAULT '';",
        "CREATE OR REPLACE TABLE EXAMPLE (ID INT);",
        "UPDATE EXAMPLE SET VALUE = 'changed';",
    ],
)
def test_non_additive_migration_is_refused(sql, dialect):
    from etl_craft.dialects.engine.compatibility import require_additive_migration

    with pytest.raises(MigrationError, match="non-additive migration"):
        require_additive_migration(sql, dialect, "future.sql")


@pytest.mark.parametrize("dialect", ["postgres", "sqlite"])
def test_new_table_nullable_column_and_index_are_additive(dialect):
    from etl_craft.dialects.engine.compatibility import require_additive_migration

    require_additive_migration(
        "CREATE TABLE NEW_TABLE (ID INT NOT NULL); "
        "ALTER TABLE NEW_TABLE ADD COLUMN VALUE TEXT; "
        "ALTER TABLE NEW_TABLE ADD COLUMN OTHER TEXT NULL; "
        "CREATE INDEX NEW_INDEX ON NEW_TABLE(VALUE);",
        dialect,
        "future.sql",
    )


def test_packaged_migrations_after_stable_baseline_are_additive():
    from etl_craft.dialects.engine.compatibility import require_additive_migration

    root = Path(__file__).parents[2]
    baseline = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "v0.9.0", "src/etl_craft/dialects/engine"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if baseline.returncode:
        # shortcut: no 0.9.0 tag exists; the release gate certifies the first mixed-version run.
        assert not (root / "tests/fixtures/schemas/0.9.0").exists(), (
            "stable schema exists but its baseline tag is missing; git fetch origin tag v0.9.0"
        )
        return
    released = set(baseline.stdout.splitlines())
    from etl_craft.engine.migrations import ENGINE, read_stream

    for dialect in ("postgres", "sqlite"):
        directory = root / f"src/etl_craft/dialects/engine/{dialect}/migrations"
        for migration in read_stream(ENGINE, directory, dialect).files:
            if str(migration.path.relative_to(root)) not in released:
                assert not migration.markers, (
                    f"{migration.version}: Python migration hooks are not additive"
                )
                require_additive_migration(migration.sql, dialect, migration.version)
