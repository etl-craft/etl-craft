"""The public non-secret references of one project alert channel."""

from dataclasses import dataclass

from etl_craft.core.alerts import AlertKind
from etl_craft.core.enums import YesNo


@dataclass(frozen=True)
class AlertChannel:
    """Resolved secret values never enter this metadata record."""

    channel_id: int
    channel_name: str
    kind: AlertKind
    url_secret: str
    signing_secret: str
    default_alert_on: str | None
    active_flag: YesNo = YesNo.YES
