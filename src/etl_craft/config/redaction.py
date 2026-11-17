"""Which team-named task parameters hide their values in the catalog, UI, API and clones."""

from pathlib import Path

from etl_craft.config.loader_helpers import mapping, reject_unknown
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.redaction import DEFAULT_SENSITIVE_PATTERNS

KEYS = frozenset({"Sensitive_patterns"})


def parse_redaction(raw: dict[str, object], path: Path) -> tuple[str, ...]:
    """Read case-insensitive name globs; an absent section keeps the defaults."""
    values = mapping(raw, "Redaction", path, required=False)
    reject_unknown(values, KEYS, "Redaction", path)
    patterns = values.get("Sensitive_patterns", list(DEFAULT_SENSITIVE_PATTERNS))
    if not isinstance(patterns, list) or not all(
        isinstance(p, str) and p.strip() for p in patterns
    ):
        raise ConfigurationError(
            f"{path}: Redaction.Sensitive_patterns is {patterns!r}; expected a list of name "
            "globs such as *TOKEN*; correct Redaction.Sensitive_patterns"
        )
    return tuple(p.strip() for p in patterns)
