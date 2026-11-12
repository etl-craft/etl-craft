"""Webhook transport boundaries use real TLS and never forward redirects."""

from http.client import HTTPException
from urllib.error import URLError

import pytest

from fixtures.webhook import webhook as webhook

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status", [204, 302, 400, 503])
def test_https_delivery_never_follows_redirects_or_returns_response_bodies(webhook, status):
    from etl_craft.services.operations.alert_delivery import post

    address, received, state = webhook
    state["status"] = status
    code, error = post(
        address + "/private", b'{"event_id":"stable"}', {"Content-Type": "application/json"}
    )
    assert code == status
    assert len(received) == 1 and received[0][0] == "/private"
    assert state["body"].decode() not in str((code, error))


@pytest.mark.parametrize(
    "value",
    [
        "FAILURES",
        "GATE_WAIT_OVER_0",
        "LOST|LOST",
        "GATE_WAIT_OVER_-1",
        "GATE_WAIT_OVER_9999999999999999999999999999999",
    ],
)
def test_invalid_alert_selectors_name_the_input_and_remedy(value):
    from etl_craft.core.alerts import triggers
    from etl_craft.core.errors import MetadataError

    with pytest.raises(MetadataError, match="ALERT_ON") as caught:
        triggers(value)
    assert value.split("|")[0] in str(caught.value)


@pytest.mark.parametrize("failure", [URLError, HTTPException, UnicodeError])
def test_transport_exception_details_cannot_escape_into_logs_or_results(
    monkeypatch, caplog, failure
):

    from etl_craft.services.operations import alert_delivery

    private = "https://private.invalid/secret-value signing-key-material"

    class Failed:
        def open(self, *args, **kwargs):
            raise failure(private)

    monkeypatch.setattr(alert_delivery, "build_opener", lambda *args: Failed())
    assert alert_delivery.post("https://receiver.invalid", b"{}", {}) == (None, "TransportError")
    assert private not in caplog.text


def test_alert_channels_are_admin_tables_excluded_from_developer_configuration():
    from etl_craft.dialects.engine.guards import ADMIN_TABLES, PROJECT_CONFIG_TABLES
    from etl_craft.engine.repository.config_rows import TABLES

    assert "CFG_ALERT_CHANNELS" in ADMIN_TABLES
    assert "CFG_ALERT_CHANNELS" not in PROJECT_CONFIG_TABLES
    assert all(table.table != "CFG_ALERT_CHANNELS" for table in TABLES)
