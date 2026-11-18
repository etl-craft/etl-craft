"""Every dialect writes the same SQL for each action as its golden file records.

A change to generated SQL fails here, offline, for every warehouse at once; the cloud
dialects need no cloud run to see it. Review the difference, then record the new SQL with
ETL_CRAFT_RECORD_GOLDEN_SQL=1.
"""

import difflib
import os

import pytest

from etl_craft.dialects.warehouse.registry import all_dialects
from fixtures.golden_sql import GOLDEN, SCENARIOS, render

pytestmark = pytest.mark.unit

KEYS = [dialect.spec.key for dialect in all_dialects()]


@pytest.mark.parametrize("key", KEYS)
def test_each_dialect_writes_its_recorded_sql(key, tmp_path):
    dialect = next(d for d in all_dialects() if d.spec.key == key)
    path = GOLDEN / f"{key}.sql"
    written = render(dialect, tmp_path)
    if os.environ.get("ETL_CRAFT_RECORD_GOLDEN_SQL") == "1":
        path.write_text(written, encoding="utf-8")
    recorded = path.read_text(encoding="utf-8")
    if written != recorded:
        diff = "".join(
            difflib.unified_diff(
                recorded.splitlines(keepends=True),
                written.splitlines(keepends=True),
                f"recorded {path.name}",
                "written now",
            )
        )
        pytest.fail(
            f"{key}: generated SQL changed; review it, then record it with "
            f"ETL_CRAFT_RECORD_GOLDEN_SQL=1\n{diff}"
        )


def test_every_dialect_and_action_is_recorded():
    assert {p.stem for p in GOLDEN.glob("*.sql")} == set(KEYS)
    for key in KEYS:
        recorded = (GOLDEN / f"{key}.sql").read_text(encoding="utf-8")
        assert [
            line[3:]
            for line in recorded.splitlines()
            if line.startswith("-- ") and not line.startswith("-- refused")
        ] == [s.name for s in SCENARIOS], key
