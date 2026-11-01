"""Operation-scoped values that must not escape through observability or results."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

_VALUES: ContextVar[tuple[str, ...]] = ContextVar("redacted_values", default=())


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
        error.args = tuple(mask(arg) for arg in error.args)
        raise
    finally:
        _VALUES.reset(token)


def mask_text(value: str) -> str:
    """Remove registered values before text leaves the operation."""
    for secret in _VALUES.get():
        value = value.replace(secret, "[REDACTED]")
    return value


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
