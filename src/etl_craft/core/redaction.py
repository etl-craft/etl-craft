"""Operation-scoped values that must not escape through observability or results."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

_VALUES: ContextVar[tuple[str, ...]] = ContextVar("redacted_values", default=())
_RESOLVED: set[str] = set()
"""Secrets this process resolved itself; masked for the life of the process."""
SHORTEST_REMEMBERED = 4
"""Shorter values would mask ordinary words everywhere; they are not remembered."""
DEFAULT_SENSITIVE_PATTERNS = ("*TOKEN*", "*SECRET*", "*PASSWORD*", "*KEY*")
REDACTED = "[REDACTED]"


def remember(value: str) -> str:
    """Mask a secret this process resolved in every later log line, error and result."""
    if len(value) >= SHORTEST_REMEMBERED:
        _RESOLVED.add(value)
    return value


@contextmanager
def registering(*values: str) -> Iterator[None]:
    """Mask these values for the current operation, including nested operations."""
    token = _VALUES.set(
        tuple(sorted(set(_VALUES.get()) | {v for v in values if v}, key=len, reverse=True))
    )
    try:
        yield
    except Exception as error:
        # Materialize safe exception text before the operation scope ends.
        pending: list[BaseException] = [error]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            current.args = tuple(mask(arg) for arg in current.args)
            pending.extend(
                cause for cause in (current.__cause__, current.__context__) if cause is not None
            )
        raise
    finally:
        _VALUES.reset(token)


def mask_text(value: str) -> str:
    """Remove registered and resolved secret values before text leaves the operation."""
    secrets = set(_VALUES.get()) | _RESOLVED
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, REDACTED)
    return value


def sensitive(name: str, patterns: tuple[str, ...]) -> bool:
    """Whether a parameter name matches a ``Redaction.Sensitive_patterns`` glob, in any case."""
    from fnmatch import fnmatchcase

    return any(fnmatchcase(name.upper(), pattern.upper()) for pattern in patterns)


def public_parameters(
    parameters: Mapping[str, str], patterns: tuple[str, ...], package: frozenset[str]
) -> dict[str, str]:
    """Hide values of team-named sensitive parameters and sensitive ``INPUT_PARAMS`` keys.

    Package parameter names (``MERGE_KEY``, ``SQL_ACTION``) never hold a secret, since secrets
    are always variable names, so the patterns apply only to the names a team chose.
    """
    import json

    shown: dict[str, str] = {}
    for name, value in parameters.items():
        if name.upper() == "INPUT_PARAMS" and value:
            try:
                document = json.loads(value)
            except ValueError:
                document = None
            shown[name] = (
                json.dumps(
                    {
                        key: REDACTED if sensitive(str(key), patterns) else item
                        for key, item in document.items()
                    }
                )
                if isinstance(document, dict)
                else value
            )
        elif name.upper() not in package and sensitive(name, patterns):
            shown[name] = REDACTED
        else:
            shown[name] = value
    return shown


def mask(value: object) -> object:
    """Mask values recursively without changing non-text result types."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return {mask_text(str(key)): mask(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(mask(item) for item in value)
    if isinstance(value, list):
        return [mask(item) for item in value]
    return value
