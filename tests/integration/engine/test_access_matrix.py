"""Every action's authorization decision, for every kind of principal, matches the recorded table.

The table is the contract the access evaluator must keep. A change to any decision fails here;
review it, then record it with ETL_CRAFT_RECORD_ACCESS_MATRIX=1.
"""

import difflib
import os

import pytest

from fixtures.access_matrix import MATRIX, build_estate, render


def test_every_decision_matches_the_recorded_matrix(engine_db, engine_actor):
    written = render(build_estate(engine_db))
    if os.environ.get("ETL_CRAFT_RECORD_ACCESS_MATRIX") == "1":
        MATRIX.write_text(written, encoding="utf-8")
    recorded = MATRIX.read_text(encoding="utf-8")
    if written != recorded:
        diff = "".join(
            difflib.unified_diff(
                recorded.splitlines(keepends=True),
                written.splitlines(keepends=True),
                "recorded access_matrix.tsv",
                "decided now",
            )
        )
        pytest.fail(
            "authorization decisions changed; review them, then record them with "
            f"ETL_CRAFT_RECORD_ACCESS_MATRIX=1\n{diff}"
        )
