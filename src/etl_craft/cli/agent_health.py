"""The agent's port-free health probe, cheap enough to run every few seconds."""

from pathlib import Path

from etl_craft.agent.renewal import require_recent_renewal
from etl_craft.config.discovery import resolve_config_path


def agent_health(project_dir: Path | None, config: Path | None) -> None:
    """Refuse unless this agent's directory holds a recent renewal; contacts nothing."""
    path = resolve_config_path(
        config if project_dir is None else project_dir / "craft-connector.yml"
    )
    require_recent_renewal(path.parent)
