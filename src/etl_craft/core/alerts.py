"""Recorded alert identities and bounded delivery contracts."""

import re
from datetime import UTC, datetime, timedelta

from etl_craft.core.enums_alerts import AlertErrorClass as AlertErrorClass
from etl_craft.core.enums_alerts import AlertKind as AlertKind
from etl_craft.core.enums_alerts import AlertStatus as AlertStatus
from etl_craft.core.enums_alerts import AlertTrigger as AlertTrigger
from etl_craft.core.errors import MetadataError

RETRY_DELAYS = (5, 30, 120)
HTTP_TIMEOUT = 10


def triggers(value: str | None) -> tuple[str, ...]:
    """Refuse unknown selectors rather than quietly omitting an alert."""
    result = tuple(value.split("|")) if value else ()
    for item in result:
        if item not in {
            AlertTrigger.FAILURE,
            AlertTrigger.SLA_BREACH,
            AlertTrigger.LOST,
        } and not re.fullmatch(r"GATE_WAIT_OVER_[1-9][0-9]*", item):
            raise MetadataError(
                f"ALERT_ON={item!r}: expected FAILURE, SLA_BREACH, LOST or "
                "GATE_WAIT_OVER_<positive minutes>; correct the alert task or channel default"
            )
        if item.startswith("GATE_WAIT_OVER_"):
            try:
                datetime.now(UTC) - timedelta(minutes=int(item.rsplit("_", 1)[1]))
            except (ValueError, OverflowError):
                raise MetadataError(
                    f"ALERT_ON={item!r}: threshold exceeds the UTC timestamp range; "
                    "expected a representable positive-minute window; reduce the threshold"
                ) from None
    if len(set(result)) != len(result):
        raise MetadataError(f"ALERT_ON={value!r}: duplicate trigger; list each trigger once")
    return result
