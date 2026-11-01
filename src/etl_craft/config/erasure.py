"""The variable naming the project's erasure HMAC secret."""

from pathlib import Path

from etl_craft.config.loader_helpers import mapping, reject_unknown
from etl_craft.config.resolve import Resolver


def parse_erasure(raw: dict[str, object], path: Path, resolver: Resolver) -> str | None:
    """Keep a variable name, never a resolved secret, in project settings."""
    values = mapping(raw, "Erasure", path, required=False)
    reject_unknown(values, frozenset({"Hmac_secret"}), "Erasure", path)
    return resolver.secret_reference(values.get("Hmac_secret"), "Erasure.Hmac_secret")
