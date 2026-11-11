"""Canonical names for upload storage, independent of client paths."""

import re

from etl_craft.core.errors import ConfigurationError
from etl_craft.core.text import is_metadata_code


def stored_name(upload_id: int, original: str) -> str:
    """Retain recognizable ASCII characters behind the unique upload identity."""
    prefix = f"{upload_id}-"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", original)[: 255 - len(prefix)] or "upload"
    return prefix + safe


def upload_key(pipeline: str, name: str) -> str:
    """Refuse corrupt recorded paths rather than traversing outside managed storage."""
    if not is_metadata_code(pipeline) or not re.fullmatch(r"[1-9][0-9]*-[A-Za-z0-9._-]+", name):
        raise ConfigurationError(
            f"upload pipeline={pipeline!r}, STORED_NAME={name!r}; expected a pipeline code "
            "and an id-prefixed safe filename; restore the recorded upload identity"
        )
    return f"{pipeline}/{name}"
