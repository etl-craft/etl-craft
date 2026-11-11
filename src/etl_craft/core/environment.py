"""Presentation of the existing project environment identity."""

from dataclasses import dataclass

from etl_craft.core.enums_access import EnvironmentType


@dataclass(frozen=True)
class Environment:
    """Administrator-declared type and optional display name."""

    type: str
    name: str | None = None

    @property
    def label(self) -> str:
        """Make production unmistakable; retain names for the other environments."""
        if self.type == EnvironmentType.PROD:
            return "PRODUCTION"
        return self.type + (f" · {self.name}" if self.name else "")
