"""Persist the supervisor's resource observation for a single attempt."""

import logging
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from etl_craft.core.faults import fault_point
from etl_craft.engine.queries import statement

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttemptResources:
    """Resource values from the operating system's exact child wait."""

    peak_rss_bytes: int | None
    cpu_seconds: float | None


def record_resources(
    engine: Engine, attempt_id: int, owner: str, resources: AttemptResources
) -> None:
    """Publish observed child resources independently of its terminal outcome."""
    if resources.peak_rss_bytes is None and resources.cpu_seconds is None:
        return
    logger.debug("attempt %d: post-reap resources remain absent until commit", attempt_id)
    fault_point("supervisor.before_attempt_resources")
    with engine.begin() as conn:
        conn.execute(
            statement(conn, "record_attempt_resources"),
            {
                "attempt_id": attempt_id,
                "owner": owner,
                "peak_rss_bytes": resources.peak_rss_bytes,
                "cpu_seconds": resources.cpu_seconds,
            },
        )
