"""Local agent renewal evidence for port-free process probes."""

from pathlib import Path
from time import time

from etl_craft.core.errors import RunStateError

MAX_AGE_SECONDS = 30


def renewal_marker(project_dir: Path) -> Path:
    """Each agent has its own writable bootstrap directory."""
    return project_dir / ".agent-renewed"


def require_recent_renewal(project_dir: Path) -> None:
    """Refuse missing, stale or future renewal evidence without contacting the API."""
    marker = renewal_marker(project_dir)
    try:
        age = time() - marker.stat().st_mtime
    except OSError as error:
        raise RunStateError(
            f"{marker}: renewal evidence unavailable ({type(error).__name__}); expected an "
            "agent renewal in this directory; check the agent and its API connection"
        ) from None
    if not 0 <= age < MAX_AGE_SECONDS:
        raise RunStateError(
            f"{marker}: last renewal age is {age:.1f}s; expected 0 to {MAX_AGE_SECONDS}s; "
            "check the agent, clock and API connection"
        )
