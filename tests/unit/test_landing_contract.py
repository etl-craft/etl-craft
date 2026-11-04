"""Landing writes refuse a foreign fan-out key before touching a warehouse."""

import logging
from types import SimpleNamespace

import pytest

from etl_craft.core.errors import HandlerError
from etl_craft.scripting import ScriptTask

pytestmark = pytest.mark.unit


def test_item_replacement_outside_fanout_is_refused():
    task = ScriptTask(
        "P",
        "load",
        1,
        1,
        1,
        "INCREMENTAL",
        None,
        {},
        {"SCRIPT_KIND": "INGESTION"},
        False,
        SimpleNamespace(),
        logging.getLogger("test"),
    )
    with pytest.raises(HandlerError, match=r"item_key.*partition-1.*fan_out.*remedy"):
        task.replace_landing(iter(()), item_key="partition-1")


def test_streaming_batches_do_not_materialize_the_input():
    from etl_craft.warehouse.landing import batches

    seen = 0

    def source():
        nonlocal seen
        for value in range(1000000):
            seen += 1
            yield {"id": value}

    iterator = batches(source(), ("id",))
    first = next(iterator)
    assert len(first) == 250
    assert seen == 251
    iterator.close()


@pytest.mark.parametrize(
    "target,column",
    [("safe.x; DROP TABLE victim", "id"), ("safe.x", "id; SELECT 1"), ("safe.x", "task_run_id")],
)
def test_landing_identifiers_are_refused(target, column):
    from etl_craft.core.landing import LandingContract, LandingWrite
    from etl_craft.dialects.warehouse import for_key
    from etl_craft.dialects.warehouse.landing import columns

    write = LandingWrite(LandingContract(1, target, ((column, "BIGINT"),)), 1, 1, 1, None)
    with pytest.raises(HandlerError, match="replace_landing"):
        columns(for_key("duckdb"), write)


def test_snowflake_landing_publication_commits_as_one_statement():
    from unittest.mock import Mock

    from etl_craft.dialects.warehouse import for_key

    conn = Mock()
    for_key("snowflake").prepare_landing_publication(conn)
    conn.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
