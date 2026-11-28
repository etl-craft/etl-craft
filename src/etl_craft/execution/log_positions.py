"""Observe the canonical positions while the supervisor writes attempt output."""

from typing import IO

from etl_craft.core.error_anchors import ErrorPosition


class LogPositions:
    """Track line starts without buffering individual lines."""

    def __init__(self, output: IO[bytes]) -> None:
        """Include log context already written before the child starts."""
        self.output = output
        self.offset = 0
        self.line = 1
        self.line_offset = 0
        self.first: ErrorPosition | None = None
        self.last: ErrorPosition | None = None
        output.seek(0)
        while data := output.read(65536):
            self._advance(data)

    def write(self, content: bytes) -> None:
        """Persist bytes and account for any line breaks after redaction."""
        self.output.write(content)
        self._advance(content)

    def marker(self, sequence: int, token: bytes) -> None:
        """Record the position of an authenticated marker before writing it."""
        position = ErrorPosition(sequence, self.line_offset, self.line)
        if self.first is None:
            self.first = position
        self.last = position
        self.write(token)

    def _advance(self, content: bytes) -> None:
        self.line += content.count(b"\n")
        newline = content.rfind(b"\n")
        if newline >= 0:
            self.line_offset = self.offset + newline + 1
        self.offset += len(content)
