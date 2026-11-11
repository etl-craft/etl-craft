"""Upload identities carried from admission to warehouse writes."""

from dataclasses import dataclass, field
from pathlib import Path

from etl_craft.core.enums import ActorKind
from etl_craft.core.enums_uploads import UploadStatus as UploadStatus


@dataclass(frozen=True)
class UploadWriter:
    """One admitted file's identity and authenticated account."""

    upload_id: int
    account: str


@dataclass(frozen=True)
class UploadInfo(UploadWriter):
    """Recorded file facts safe to send to an API-only task host."""

    file_name: str
    size_bytes: int
    sha256: str
    stored_name: str = field(kw_only=True)
    actor_kind: ActorKind = field(default=ActorKind.USER, kw_only=True)


@dataclass(frozen=True)
class UploadFile(UploadInfo):
    """A verified local file made available to a task script."""

    path: Path

    @property
    def label(self) -> str:
        """Name the file the way every upload message does."""
        return f"upload {self.upload_id} {self.file_name!r}"

    @property
    def ref(self) -> str:
        """Name the file by its identity alone."""
        return f"upload {self.upload_id}"


@dataclass(frozen=True)
class SourceFile:
    """A file an event wait admitted: validated where it is, never copied or re-attributed."""

    path: Path
    size_bytes: int
    sha256: str

    @property
    def file_name(self) -> str:
        """The file's own name, which decides the extension check."""
        return self.path.name

    @property
    def label(self) -> str:
        """Name the file by its canonical path, which is its identity."""
        return f"event file {str(self.path)!r}"

    @property
    def ref(self) -> str:
        """Name the file by its identity alone."""
        return self.label


CheckedFile = UploadFile | SourceFile
"""What the readers and the format check accept: an upload or an event-admitted file."""
