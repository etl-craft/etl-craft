"""Recorded pipeline validation outcomes, shared by the CLI and HTTP interfaces."""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from etl_craft.core.enums import RunStatus


@dataclass(frozen=True)
class ReparseFinding:
    """A file location where applicable, or an exact Engine DB metadata identity."""

    file: str
    line: int | None
    value: str
    message: str
    remedy: str
    failed: bool = True


@dataclass(frozen=True)
class PipelineReparse:
    """One durable result; the bundle and metadata version identify the checked bytes."""

    reparse_id: int
    pipeline_code: str
    reparsed_at: datetime
    actor: str
    status: RunStatus
    metadata_version: str
    bundle_id: str | None
    findings: tuple[ReparseFinding, ...]
    changed: bool = True
    changes: tuple[str, ...] = ()
    previous_reparsed_at: datetime | None = None
    previous_status: RunStatus | None = None


@dataclass(frozen=True)
class ReparseResults:
    """Project re-parse results, or the recorded history for a pipeline."""

    SCHEMA: ClassVar[str] = "etl-craft/pipeline-reparse/1"
    reparses: tuple[PipelineReparse, ...]

    @property
    def failed(self) -> bool:
        """Whether any checked pipeline failed validation."""
        return any(result.status == RunStatus.FAILED for result in self.reparses)
