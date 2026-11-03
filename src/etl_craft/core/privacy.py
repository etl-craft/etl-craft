"""Domain-separated host-side identities for private project history."""

import hashlib
import hmac

from etl_craft.core.enums_privacy import PrivacyDomain as PrivacyDomain


def digest(secret: str, domain: PrivacyDomain, value: str = "") -> str:
    """Never expose an unkeyed fingerprint as a persistent private identity."""
    return hmac.new(
        secret.encode(), domain.encode() + b"\x00" + value.encode(), hashlib.sha256
    ).hexdigest()


def fingerprint(
    secret: str, domain: PrivacyDomain, target: str, value: str, column: str | None = None
) -> str:
    """Keep known values in another target or column from identifying private history."""
    import json

    return digest(secret, domain, json.dumps([target, column, value], separators=(",", ":")))
