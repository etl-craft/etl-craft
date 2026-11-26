"""A writer's ROW_ID range and its limits, refused before any row is written."""

import pytest

from etl_craft.core.errors import SqlGuardError
from etl_craft.dialects.warehouse.row_ids import (
    WRITER_LIMIT,
    WRITER_SPAN,
    checked_base,
    writer_floor,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("writer", "floor"), [(7, 7 * 2**32), (-3, -3 * 2**32)])
def test_each_writer_owns_its_own_range(writer, floor):
    assert writer_floor("c.s.t", writer) == floor


@pytest.mark.parametrize("writer", [0, WRITER_LIMIT, -WRITER_LIMIT])
def test_a_writer_outside_the_limits_is_refused(writer):
    with pytest.raises(SqlGuardError, match=rf"c\.s\.t: ROW_ID writer {writer}; expected"):
        writer_floor("c.s.t", writer)


def test_a_write_that_would_leave_its_range_is_refused():
    floor = writer_floor("c.s.t", 5)
    assert checked_base("c.s.t", 5, floor + 10, WRITER_SPAN - 11) == floor + 10
    with pytest.raises(SqlGuardError, match=r"writer 5 would number .* split the load"):
        checked_base("c.s.t", 5, floor + 10, WRITER_SPAN - 10)
