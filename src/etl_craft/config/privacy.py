"""The variable naming the project's privacy HMAC secret."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etl_craft.config.model import ConnectorConfig

from etl_craft.config.loader_helpers import mapping, reject_unknown
from etl_craft.config.resolve import Resolver

KEYS = frozenset({"Hmac_secret"})


def parse_privacy(raw: dict[str, object], path: Path, resolver: Resolver) -> str | None:
    """Keep a variable name, never a resolved secret, in project settings."""
    values = mapping(raw, "Privacy", path, required=False)
    reject_unknown(values, KEYS, "Privacy", path)
    return resolver.secret_reference(values.get("Hmac_secret"), "Privacy.Hmac_secret")


def privacy_secret(config: "ConnectorConfig") -> str:
    """Require a resolved project privacy secret without retaining it in configuration."""
    from etl_craft.config.resolve import resolve_named_secret
    from etl_craft.core.errors import ConfigurationError

    name = config.privacy_hmac_secret
    project = config.project
    if not name:
        raise ConfigurationError(
            f"project {project}: Privacy.Hmac_secret=missing; expected a secret variable name; "
            "configure Privacy.Hmac_secret and set that variable before protection or erasure"
        )
    try:
        return resolve_named_secret(config, name)
    except ConfigurationError:
        raise ConfigurationError(
            f"project {project}: Privacy.Hmac_secret={name!r} is missing or empty; expected a "
            "resolved secret; set that variable in the configured Secrets provider"
        ) from None
