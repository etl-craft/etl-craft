"""Persist the supervisor's resource observation for a single attempt."""

import logging
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from etl_craft.core.error_anchors import ErrorPosition
from etl_craft.core.faults import fault_point
from etl_craft.engine.queries import statement

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttemptResources:
    """Resource values from the operating system's exact child wait."""

    peak_rss_bytes: int | None
    cpu_seconds: float | None
    first_error: ErrorPosition | None = None
    last_error: ErrorPosition | None = None


def record_resources(
    engine: Engine, attempt_id: int, owner: str, resources: AttemptResources
) -> None:
    """Publish observed child resources independently of its terminal outcome."""
    if all(
        value is None
        for value in (
            resources.peak_rss_bytes,
            resources.cpu_seconds,
            resources.first_error,
            resources.last_error,
        )
    ):
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
                **_position("first", resources.first_error),
                **_position("last", resources.last_error),
            },
        )


def _position(prefix: str, position: ErrorPosition | None) -> dict[str, int | None]:
    return {
        f"{prefix}_sequence": None if position is None else position.sequence,
        f"{prefix}_offset": None if position is None else position.offset,
        f"{prefix}_line": None if position is None else position.line,
    }
