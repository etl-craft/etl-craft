"""Hash-only protection boundaries shared by local and remote callers."""

import pytest

from etl_craft.core.enums_protection import ProtectionKind, ProtectionStatus
from etl_craft.core.errors import UsageError
from etl_craft.core.protection import (
    MAX_PROTECTION_COLUMNS,
    MAX_PROTECTION_EVENTS,
    ProtectionEvent,
    ProtectionPage,
    ProtectionReport,
    validate_cursor,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["private-value", "a" * 31, "A" * 32])
def test_non_hash_business_text_is_refused_without_echoing_it(value):
    with pytest.raises(UsageError) as error:
        ProtectionEvent(ProtectionKind.WRITE, value, ("name",), ("b" * 32,))
    assert value not in str(error.value)
    assert "32 hex digits" in str(error.value)


@pytest.mark.parametrize("case", ["empty", "oversized", "duplicate", "length", "row_scope", "hash"])
def test_event_column_and_hash_lists_are_bounded_and_unambiguous(case):
    columns, hashes = ("name",), ("b" * 32,)
    if case == "empty":
        columns, hashes = (), ()
    elif case == "oversized":
        columns = tuple(f"c_{i}" for i in range(MAX_PROTECTION_COLUMNS + 1))
        hashes = ("b" * 32,) * len(columns)
    elif case == "duplicate":
        columns, hashes = ("name", "name"), ("b" * 32, "b" * 32)
    elif case == "length":
        hashes = ()
    elif case == "row_scope":
        columns = ("*",)
    else:
        hashes = ("private-value",)
    with pytest.raises(UsageError):
        ProtectionEvent(ProtectionKind.WRITE, "a" * 32, columns, hashes)


def test_report_and_page_refuse_exceeding_the_shared_limit():
    event = ProtectionEvent(ProtectionKind.WRITE, "a" * 32, ("name",), ("b" * 32,))
    with pytest.raises(UsageError, match=str(MAX_PROTECTION_EVENTS)):
        ProtectionReport(ProtectionStatus.PENDING, (event,) * (MAX_PROTECTION_EVENTS + 1))
    with pytest.raises(UsageError, match="nonempty"):
        ProtectionReport(ProtectionStatus.PENDING)
    with pytest.raises(UsageError, match="existing request"):
        ProtectionReport(ProtectionStatus.COMMITTED)
    assert ProtectionPage((), None).records == ()


@pytest.mark.parametrize("cursor", [-1, 2**63])
def test_cursor_must_fit_an_engine_db_identity(cursor):
    with pytest.raises(UsageError, match="restart the read"):
        validate_cursor(cursor)


def test_uppercase_warehouse_labels_match_canonical_cell_names():
    from etl_craft.dialects.warehouse.protection import ProtectionSql

    sql = ProtectionSql("people", "locks", "t.ID", {}, "fingerprint")
    stage = sql.protect_stage("incoming", ("ID", "NAME"), delete=False)
    prevented = sql.prevented("incoming", ("ID", "NAME"), delete=False)
    assert "p.column_name = 'name'" in stage
    assert "THEN t.NAME" in stage
    assert "p.column_name IN ('*', 'name')" in prevented
    assert "p.column_name = 'NAME'" not in stage
