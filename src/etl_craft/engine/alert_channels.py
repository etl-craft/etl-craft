"""One project alert channel: its kind, recipients or secret variable names."""

from dataclasses import dataclass

from etl_craft.core.alerts import AlertKind
from etl_craft.core.enums import YesNo


@dataclass(frozen=True)
class AlertChannel:
    """Resolved secret values never enter this metadata record."""

    channel_id: int
    channel_name: str
    kind: AlertKind
    url_secret: str | None
    signing_secret: str | None
    recipients: str | None
    default_alert_on: str | None
    active_flag: YesNo = YesNo.YES
