"""The etl-craft banner: the product mark beside what this installation and session are.

Pure rendering: the caller reads the facts through the shared actions and writes the text.
Colour and the mark appear only on a terminal that wants them.
"""

import os
import shutil
from dataclasses import dataclass
from typing import TextIO

MARK = (
    "          ▄▄██▄▄          ",
    "       ▄██████████▄       ",
    "   ▄▄████████████████▄▄   ",
    " ▄██████████████████████▄ ",
    "  ▀▀██████████████████▀▀  ",
    "      ▀████████████▀      ",
    " ▄▄▄     ▀▀████▀▀     ▄▄▄ ",
    "▀█████▄            ▄█████▀",
    "   ▀▀████▄ ████ ▄████▀▀   ",
    " █▄▄  ▀▀██ ████ ██▀▀  ▄▄█ ",
    "▀▀████▄▄   ████   ▄▄████▀▀",
    "   ▀▀█████▄ ▀▀ ▄█████▀▀   ",
    "       ▀██████████▀       ",
    "          ▀▀██▀▀          ",
)
"""The mark: the product logo as half-block art, light above the stem and darker below it."""
MARK_TOP_ROWS = 6
WORDMARK = (
    "█████ █████ █         █████ ████   ███  █████ █████",
    "█       █   █         █     █   █ █   █ █       █  ",
    "████    █   █     ███ █     ████  █████ ████    █  ",
    "█       █   █         █     █  █  █   █ █       █  ",
    "█████   █   █████     █████ █   █ █   █ █       █  ",
)
"""The product name in block letters, drawn beside the mark and above the facts."""
WORDMARK_ROW = 2

LIGHT, TEAL, BOLD, RED, RESET = "\033[38;5;74m", "\033[38;5;31m", "\033[1m", "\033[1;31m", "\033[0m"


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


def suppressed() -> bool:
    """Whether ``ETL_CRAFT_NO_BANNER`` asks for no mark: plain rows, and nothing on a bare run."""
    return "ETL_CRAFT_NO_BANNER" in os.environ


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


def wants_art(stream: TextIO, facts: Facts) -> bool:
    """Draw the mark on a terminal wide enough for it beside the rows, unless suppressed."""
    if suppressed() or not is_terminal(stream):
        return False
    rows = _rows(facts)
    widest = max(len(label) + 2 + len(value) for label, value in rows)
    return shutil.get_terminal_size().columns >= len(MARK[0]) + 2 + max(widest, len(WORDMARK[0]))


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
    if not art:
        return "\n".join([paint("etl-craft", BOLD), "-" * len("etl-craft"), *lines])
    # The name in block letters sits beside the mark, and the facts follow it.
    right = [""] * WORDMARK_ROW + [paint(row, TEAL + BOLD) for row in WORDMARK] + ["", *lines]
    out = []
    for index in range(max(len(MARK), len(right))):
        if index < len(MARK):
            left = paint(MARK[index], LIGHT if index < MARK_TOP_ROWS else TEAL)
        else:
            left = " " * len(MARK[0])
        out.append(f"{left}  {right[index] if index < len(right) else ''}".rstrip())
    return "\n".join(out)
