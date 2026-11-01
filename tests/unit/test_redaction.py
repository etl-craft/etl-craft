"""Registered values cannot escape through messages, records or result documents."""

import logging

import pytest

from etl_craft.core.errors import HandlerError
from etl_craft.core.log import ContextFilter
from etl_craft.core.redaction import mask, registering
from etl_craft.services.operations.serialization import encode

pytestmark = pytest.mark.unit


def test_value_scope_masks_nested_values_records_errors_and_json():
    key = "private-person-key"
    with pytest.raises(HandlerError) as raised, registering(key):
        record = logging.LogRecord("test", logging.ERROR, "", 1, "value=%s", (key,), None)
        assert ContextFilter().filter(record)
        assert key not in record.getMessage()
        assert key not in str(encode({"nested": [key]}))
        with registering("inner-key"):
            assert mask([key, "inner-key"]) == ["[REDACTED]", "[REDACTED]"]
        raise HandlerError(f"invalid value {key}; expected safe input; correct input")
    assert key not in str(raised.value)
    assert mask(key) == key


def test_registered_value_is_masked_in_attempt_result():
    from etl_craft.handlers.registry import HandlerResult, format_task_log

    with registering("private-person-key"):
        result = HandlerResult(variables={"diagnostic": "private-person-key"})
        assert "private-person-key" not in format_task_log(result)


def test_agent_erasure_waits_for_host_without_transmitting_a_key():
    from etl_craft.agent.task_store import RemoteTaskStore
    from etl_craft.core.enums import ActionName, AgentReport
    from etl_craft.core.erasure import ErasureReport
    from etl_craft.services.operations.agent_models import AgentReply
    from etl_craft.services.operations.serialization import to_json

    sent = {}

    class Client:
        def call(self, name, request, *, timeout):
            sent.update(name=name, request=request, timeout=timeout)
            return AgentReply(to_json(ErasureReport()))

    store = RemoteTaskStore(Client(), 7, lambda _: None, "holder")
    assert store.erasure() == ErasureReport()
    assert sent["name"] == ActionName.AGENT_REPORT
    assert sent["request"].operation == AgentReport.ERASURE
    assert sent["request"].attempt_id == 7
    assert sent["timeout"] is None
