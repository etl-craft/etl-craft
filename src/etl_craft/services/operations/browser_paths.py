"""Same-site return addresses shared by sign-in operations and HTTP rendering."""

from urllib.parse import unquote, urlsplit

from etl_craft.core.errors import UsageError


def return_path(value: str) -> str:
    """Accept a same-site absolute path, refusing host, scheme and encoded authority tricks."""
    decoded = unquote(value)
    try:
        parts = urlsplit(decoded)
    except ValueError as error:
        raise UsageError("return_to is malformed; expected a same-site path; open /ui") from error
    if (
        len(value) > 4096
        or not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or parts.scheme
        or parts.netloc
        or unquote(decoded) != decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        raise UsageError(f"return_to={value!r}; expected a same-site path such as /ui; open /ui")
    return value
