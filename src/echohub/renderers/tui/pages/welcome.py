"""First run: shown until Echohub has a snapshot to draw.

What's happening (connecting, downloading), or what went wrong and how to
retry, plus where data comes from and whether private repos are included.
The token itself is never shown.
"""

from __future__ import annotations

from .... import palette as P
from ....config import DashboardConfig
from ..style import fit, paint
from ..widgets import hbar, keycap

CARD = 64


class Welcome:
    def __init__(self, config: DashboardConfig) -> None:
        self.config = config
        self.state = "idle"
        self.headline = "No snapshot yet"
        self.detail = "Press c to download it."
        self.progress: float | None = None
        self.sweep = 0

    def show_progress(self, message: str, fraction: float | None) -> None:
        self.state = "loading"
        self.headline = "Downloading your first snapshot"
        self.detail = message
        self.progress = fraction

    def show_failure(self, title: str, detail: str) -> None:
        self.state = "failed"
        self.headline = title
        self.detail = detail
        self.progress = None

    def render(self, cells: int, rows: int) -> list[str]:
        inner = min(CARD, cells - 4)
        lines = [
            paint("Welcome to Echohub", P.TEXT, bold=True),
            "",
            *(
                paint(line, P.SUBTLE)
                for line in _wrap(
                    "Your repos, commits, languages and packages, from your Echopoint "
                    "snapshot. The first download takes a few seconds; after that "
                    "Echohub opens instantly and checks for changes in the background.",
                    inner,
                )
            ),
            "",
            paint(
                self.headline, P.LOVE if self.state == "failed" else P.TEXT, bold=True
            ),
            *(paint(line, P.SUBTLE) for line in _wrap(self.detail, inner)),
            "",
        ]
        if self.state == "loading":
            if self.progress is None:
                self.sweep = (self.sweep + 1) % inner
                start = self.sweep
                track = [paint("━", P.BORDER_STRONG)] * inner
                for offset in range(min(10, inner)):
                    track[(start + offset) % inner] = paint("━", P.ACCENT)
                lines.append("".join(track))
            else:
                lines.append(hbar(self.progress, inner, P.ACCENT, P.BORDER_STRONG))
        else:
            action = "Try again" if self.state == "failed" else "Download snapshot"
            lines.append(keycap("c") + " " + paint(action, P.TEXT))
        lines.append("")
        private = bool(self.config.refresh_token)
        for caption, value in (
            ("Source", self.config.base_url),
            (
                "Token",
                "set · private repos included"
                if private
                else "not set · public repos only",
            ),
            ("Saved to", str(self.config.cache_dir)),
        ):
            lines.append(fit(paint(caption, P.MUTED), 10) + paint(value, P.SUBTLE))
        lines.append(
            paint(
                "ECHOHUB_SOURCE_URL · ECHOHUB_REFRESH_TOKEN · ECHOHUB_CACHE_DIR",
                P.MUTED,
            )
        )
        top = max(0, (rows - len(lines)) // 3)
        left = " " * max(0, (cells - inner) // 2)
        return [""] * top + [left + fit(line, inner) for line in lines]


def _wrap(text: str, cells: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > cells:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(line)
    return lines
