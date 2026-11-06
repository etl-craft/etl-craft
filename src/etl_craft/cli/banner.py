"""The etl-craft banner: the product mark beside what this installation and session are.

Pure rendering: the caller reads the facts through the shared actions and writes the text.
Colour and the mark appear only on a terminal that wants them.
"""

import os
from dataclasses import dataclass
from typing import TextIO

MARK = (
    "     /\\     ",
    "    /  \\    ",
    "    \\  /    ",
    "     \\/     ",
    "   \\  |  /   ",
    "    \\ | /    ",
    "   \\  |  /   ",
    "    \\ | /    ",
)
"""The mark: a plane over a stem and two chevrons, as the interface and the catalog draw it."""

BLUE, BOLD, RED, RESET = "\033[38;5;75m", "\033[1m", "\033[1;31m", "\033[0m"


@dataclass(frozen=True)
class Facts:
    """What the banner shows; any line without a value is left out."""

    version: str
    schema: str | None = None
    account: str | None = None
    role: str | None = None
    project: str | None = None
    environment: str | None = None
    production: bool = False
    controllers: int | None = None
    server: str | None = None
    docs: str | None = None


def is_terminal(stream: TextIO) -> bool:
    """Whether the stream is a terminal that has not asked for plain output."""
    return stream.isatty() and os.environ.get("TERM") != "dumb"


def wants_colour(stream: TextIO) -> bool:
    """Colour needs a terminal and no ``NO_COLOR`` (any value, as no-color.org asks)."""
    return is_terminal(stream) and "NO_COLOR" not in os.environ


def _rows(facts: Facts) -> list[tuple[str, str]]:
    rows = [("Version", facts.version)]
    if facts.schema:
        rows.append(("Engine DB", facts.schema))
    if facts.account:
        rows.append(("Account", f"{facts.account} ({facts.role})" if facts.role else facts.account))
    if facts.project:
        rows.append(("Project", facts.project))
    if facts.environment:
        rows.append(("Environment", facts.environment))
    if facts.controllers is not None:
        rows.append(
            ("Controllers", f"{facts.controllers} live" if facts.controllers else "none live")
        )
    if facts.server and facts.server != facts.version:
        rows.append(("Server", facts.server))
    if facts.docs:
        rows.append(("Docs", facts.docs))
    return rows


def render(facts: Facts, *, art: bool, colour: bool) -> str:
    """Render the mark (when ``art``) beside aligned label and value rows."""

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if colour else text

    rows = _rows(facts)
    width = max(len(label) for label, _ in rows)
    lines = []
    for label, value in rows:
        shown = paint(value, RED) if label == "Environment" and facts.production else value
        lines.append(f"{paint(label.ljust(width), BOLD)}  {shown}")
    title = paint("etl-craft", BOLD)
    body = [title, "-" * len("etl-craft"), *lines]
    if not art:
        return "\n".join(body)
    out = []
    for index in range(max(len(MARK), len(body))):
        left = paint(MARK[index], BLUE) if index < len(MARK) else " " * len(MARK[0])
        right = body[index] if index < len(body) else ""
        out.append(f"{left}  {right}".rstrip())
    return "\n".join(out)
