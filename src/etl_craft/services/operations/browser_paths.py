"""Same-site return addresses shared by sign-in operations and HTTP rendering."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etl_craft.config.model import ConnectorConfig

from urllib.parse import unquote, urlsplit

from etl_craft.core.errors import ConfigurationError, UsageError


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


def public_origin(config: "ConnectorConfig") -> str:
    """Return the configured HTTPS public origin, independent of request headers."""
    site = config.docs_site
    base = site.external_url or (f"https://{site.domain}" if site.domain else None)
    if not base or not base.startswith("https://"):
        raise ConfigurationError(
            "browser SSO needs an HTTPS public address; configure Docs_site.External_url "
            "or Docs_site.Domain for this deployment"
        )
    origin = urlsplit(base)
    return f"{origin.scheme}://{origin.netloc}"
