"""Styled text for the terminal: truecolor spans, cell widths, fitting.

Text is kept as ANSI strings. Helpers end every span with RESET, and
``surface`` re-applies a line's background after each one, so a span never
leaks its colours into the rest of the line.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from ... import palette as P

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
_SGR = re.compile(r"\x1b\[[0-9;]*m")
# Anything a terminal would act on: C0 and C1 controls, DEL. Snapshot text
# (commit messages, descriptions) must never move the cursor or restyle.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


@lru_cache(maxsize=128)
def fg(colour: str) -> str:
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


@lru_cache(maxsize=128)
def bg(colour: str) -> str:
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[48;2;{r};{g};{b}m"


def clean(text: str) -> str:
    """Tabs and newlines become spaces; other control characters go."""
    return _CONTROL.sub(
        lambda m: " " if m.group() in "\t\n\r" else "", text.replace("\r\n", " ")
    )


def paint(
    text: str, colour: str = P.TEXT, *, bold: bool = False, back: str | None = None
) -> str:
    if not text:
        return ""
    return (
        (BOLD if bold else "")
        + fg(colour)
        + (bg(back) if back else "")
        + clean(text)
        + RESET
    )


def plain(text: str) -> str:
    return _SGR.sub("", text)


@lru_cache(maxsize=4096)
def char_width(char: str) -> int:
    code = ord(char)
    if code < 0x300:
        return 1 if code >= 0x20 else 0
    if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def width(text: str) -> int:
    return sum(char_width(char) for char in plain(text))


def clip(text: str, cells: int) -> str:
    """Cut styled text to at most ``cells`` columns, ending in … when cut."""
    if cells <= 0:
        return ""
    if width(text) <= cells:
        return text
    out: list[str] = []
    used = 0
    for match in re.finditer(r"\x1b\[[0-9;]*m|.", text, re.DOTALL):
        token = match.group()
        if token.startswith("\x1b"):
            out.append(token)
            continue
        size = char_width(token)
        if used + size > cells - 1:
            break
        out.append(token)
        used += size
    return "".join(out) + "…" + " " * (cells - 1 - used) + RESET


def fit(text: str, cells: int, align: str = "left") -> str:
    """Exactly ``cells`` columns: clipped, then padded."""
    text = clip(text, cells)
    gap = " " * max(0, cells - width(text))
    if align == "right":
        return gap + text
    if align == "center":
        half = len(gap) // 2
        return gap[:half] + text + gap[half:]
    return text + gap


def surface(text: str, cells: int, back: str = P.BASE) -> str:
    """A line exactly ``cells`` wide on ``back``, default text colour TEXT."""
    base = bg(back) + fg(P.TEXT)
    return base + fit(text, cells).replace(RESET, RESET + base) + RESET


def spread(left: str, right: str, cells: int) -> str:
    """``left`` and ``right`` at either end of ``cells`` columns; left wins."""
    room = cells - width(right)
    if room < width(left) + 1:
        return fit(left, cells)
    return fit(left, room) + right


def hjoin(*panes: tuple[list[str], int], gap: int = 2) -> list[str]:
    """Panes side by side; each is (lines, width) and is padded to its width."""
    rows = max((len(lines) for lines, _ in panes), default=0)
    out: list[str] = []
    for index in range(rows):
        cells = [
            fit(lines[index] if index < len(lines) else "", cells)
            for lines, cells in panes
        ]
        out.append((" " * gap).join(cells))
    return out
