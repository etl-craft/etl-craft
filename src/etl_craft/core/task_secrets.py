"""Names and admission checks shared by script credential readers."""

from collections.abc import Mapping

from etl_craft.core.errors import PermanentError
from etl_craft.core.text import is_env_name, pipe_list


def declared(params: Mapping[str, str], label: str) -> tuple[str, ...]:
    """Require explicit, unique provider names, never secret values."""
    written = params.get("SECRETS", "").strip()
    names = pipe_list(written)
    if len(set(names)) != len(names) or any(not is_env_name(name) for name in names):
        raise PermanentError(
            f"{label}: invalid SECRETS declaration; expected unique pipe-separated variable names; "
            "declare names such as SOURCE_USER|SOURCE_PASSWORD, never values"
        )
    return names


def read(
    values: Mapping[str, str], names: tuple[str, ...], label: str, provider: str, name: str
) -> str:
    """Never resolve an undeclared name or fall back to a task's process environment."""
    if name not in names:
        raise PermanentError(
            f"{label}: secret {name!r} is undeclared for provider {provider}; "
            "add its variable name to SECRETS and republish the task"
        )
    if name not in values:
        raise PermanentError(
            f"{label}: secret {name!r} is missing from provider {provider}; "
            "set the declared variable in the configured provider and retry"
        )
    return values[name]
