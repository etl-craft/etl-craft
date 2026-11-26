"""Warehouse SQL that numbers rows from their writer's identity.

``ROW_ID = writer * 2^32 + n``. The writer is the ``TASK_RUN_ID`` of the task run that writes
the row, or the negated audited request ID of a writer outside a task run (a seed load, an
adoption), so two writers never share a range. A write numbers its rows after the largest ID
its writer already holds in the target, so a retry, or a second write by one task run (one
landing item after another), never repeats an ID. Nothing is stored outside the warehouse.
"""

from etl_craft.core.errors import SqlGuardError

WRITER_SPAN = 2**32
"""Rows one writer can number in one target."""

WRITER_LIMIT = 2**31
"""Writer identities stay below this in magnitude, so every ID fits a signed BIGINT."""


def writer_floor(target: str, writer: int) -> int:
    """Return the ID before ``writer``'s range; refuse a writer outside the limits."""
    if writer == 0 or abs(writer) >= WRITER_LIMIT:
        raise SqlGuardError(
            f"{target}: ROW_ID writer {writer}; expected a task run or audited request ID "
            f"below {WRITER_LIMIT} in magnitude; write through etl-craft"
        )
    return writer * WRITER_SPAN


def checked_base(target: str, writer: int, base: int, count: int) -> int:
    """Return ``base`` when ``count`` more rows still fit ``writer``'s range."""
    if base + count >= writer * WRITER_SPAN + WRITER_SPAN:
        raise SqlGuardError(
            f"{target}: writer {writer} would number {count} more row(s) after ROW_ID {base}; "
            f"expected fewer than {WRITER_SPAN} rows per writer and target; split the load "
            "across task runs"
        )
    return base


def next_id_sql(target: str) -> str:
    """Select the largest ID the writer holds in ``target``, or its floor (``:floor``)."""
    return (
        f"SELECT COALESCE(MAX(ROW_ID), :floor) AS base FROM {target} "
        "WHERE ROW_ID > :floor AND ROW_ID < :ceiling"
    )


def row_number(base: int | str, partition: str = "") -> str:
    """Return SQL numbering the rows of a materialized source after ``base``, per ``partition``."""
    return f"{base} + CAST(ROW_NUMBER() OVER ({partition}ORDER BY NULL) AS BIGINT)"
