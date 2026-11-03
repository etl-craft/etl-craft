"""The project-wide ceiling for stewardship files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from etl_craft.config.object_models import Artifacts

if TYPE_CHECKING:
    from etl_craft.config.resolve import Resolver

from etl_craft.core.errors import ConfigurationError

KEYS = frozenset({"Max_file_mb", "Archive_to"})
ARCHIVE_KEYS = frozenset({"Store", "Profile"})


@dataclass(frozen=True)
class Uploads:
    """Bound live upload storage before any pipeline-specific validation."""

    max_file_mb: int = 50
    archive_to: Artifacts = field(default_factory=Artifacts)

    def __post_init__(self) -> None:
        """Require a positive whole-megabyte ceiling."""
        if (
            isinstance(self.max_file_mb, bool)
            or not isinstance(self.max_file_mb, int)
            or self.max_file_mb < 1
        ):
            raise ConfigurationError(
                f"Uploads.Max_file_mb={self.max_file_mb!r}; expected a positive integer; "
                "set the maximum file size in MiB"
            )


def parse_uploads(raw: dict[str, object], path: Path, resolver: Resolver) -> Uploads:
    """Parse the blanket limit without accepting unused configuration keys."""
    from etl_craft.config.loader_helpers import mapping, reject_unknown
    from etl_craft.config.object_stores import parse_location, parse_stores

    values = mapping(raw, "Uploads", path, required=False)
    reject_unknown(values, KEYS, "Uploads", path)
    value = values.get("Max_file_mb", 50)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(
            f"Uploads.Max_file_mb={value!r}; expected a positive integer; "
            "set the maximum file size in MiB"
        )
    archive = values.get("Archive_to")
    location = {} if archive is None else archive
    if isinstance(location, str):
        location = {"Store": location}
    if not isinstance(location, dict):
        raise ConfigurationError(
            f"{path}: Uploads.Archive_to={archive!r}; expected file:// or a Store/Profile "
            "mapping for s3://; set Archive_to to a location and name an existing "
            "Object_stores profile for S3"
        )
    reject_unknown(location, ARCHIVE_KEYS, "Uploads.Archive_to", path)
    return Uploads(
        value,
        parse_location(location, parse_stores(raw, path, resolver), path, "Uploads.Archive_to"),
    )
