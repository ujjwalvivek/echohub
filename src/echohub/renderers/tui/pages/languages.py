"""Languages: what the portfolio is written in, overall and per repo."""

from __future__ import annotations

from .... import palette as P
from ....formatting import human_bytes
from ....insights import Fingerprint, language_fingerprint
from ....models import DashboardState, LanguageSlice
from ..style import fit, hjoin, paint, width
from ..table import Column, Table
from ..widgets import page_title, private_mark, scrollbar, section
from .base import Context, Page, list_moves

# One colour per matrix column: SERIES has ten, so ten columns stay distinct.
MATRIX_LANGUAGES = len(P.SERIES)
_NAME = 16
SIDE_FROM = 110


def _matrix_width(fingerprint: Fingerprint) -> int:
    return 2 + _NAME + 1 + 2 * len(fingerprint.languages)


class LanguagesPage(Page):
    name = "Languages"
    keys = (
        ("Tab / h l", "switch between the ledger and the fingerprints"),
        ("s / S", "next sort column / reverse the order"),
    )

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.slices: list[LanguageSlice] = []
        self.largest: dict[str, tuple[str, int]] = {}
        self.fingerprint = Fingerprint([], [])
        self.table: Table[LanguageSlice] = Table(self._columns(False), [], sort="Bytes")
        self.pane = 0  # 0 ledger, 1 fingerprints
        self.matrix_offset = 0
        self._rows = 0
        self._matrix_rows = 0

    def _columns(self, private: bool) -> list[Column[LanguageSlice]]:
        columns: list[Column[LanguageSlice]] = [
            Column(
                "Language",
                lambda s: s.language,
                width=14,
                stretch=True,
                kind="swatch",
                tone=lambda s: P.series_color(s.language),
                sort=lambda s: s.language.lower(),
                descending=False,
            ),
            Column(
                "Largest repo",
                lambda s: self._largest(s.language),
                width=24,
                kind="muted",
                drop=3,
            ),
            Column(
                "Bytes",
                lambda s: human_bytes(s.bytes),
                width=9,
                kind="bar",
                value=lambda s: s.bytes,
                tone=lambda s: P.series_color(s.language),
                sort=lambda s: s.bytes,
            ),
            Column(
                "Share",
                lambda s: f"{s.share:.1%}",
                width=6,
                kind="number",
                sort=lambda s: s.share,
            ),
            Column(
                "Repos",
                lambda s: str(s.projects),
                width=5,
                kind="number",
                sort=lambda s: s.projects,
                drop=2,
            ),
        ]
        if private:
            columns.append(
                Column(
                    "Private",
                    lambda s: human_bytes(s.private_bytes) if s.private_bytes else "",
                    width=9,
                    kind="number",
                    sort=lambda s: s.private_bytes,
                    drop=1,
                )
            )
        return columns

    def _largest(self, language: str) -> str:
        entry = self.largest.get(language)
        if entry is None:
            return ""
        alias, value = entry
        return f"{alias} · {human_bytes(value)}"

    def set_state(self, state: DashboardState) -> None:
        self.slices = state.analytics.languages
        self.largest = {}
        for project in state.projects:
            for language, value in project.languages.items():
                if value > self.largest.get(language, ("", 0))[1]:
                    self.largest[language] = (project.alias, value)
        private = any(item.private_bytes for item in self.slices)
        sort = self.table.sort_column.title if self.table.sort_column else "Bytes"
        self.table = Table(self._columns(private), self.slices, sort=sort)
        self.fingerprint = language_fingerprint(state.projects, limit=MATRIX_LANGUAGES)

    def render(self, cells: int, rows: int) -> list[str]:
        self._rows = rows
        total = sum(item.bytes for item in self.slices)
        private = sum(item.private_bytes for item in self.slices)
        subtitle = f"{human_bytes(total)} of code across {len(self.slices)} languages"
        if private:
            subtitle += f" · {human_bytes(private)} from private repos"
        lines = [page_title("Languages", subtitle, cells), ""]
        lines.append(
            section("Composition", "GitHub language bytes, not lines of code", cells)
        )
        lines.append(self._composition(cells))
        lines.append(self._legend(cells))
        lines.append("")
        body = rows - len(lines)
        matrix_width = _matrix_width(self.fingerprint)
        if cells >= SIDE_FROM and cells - matrix_width - 3 >= 50:
            left = cells - matrix_width - 3
            ledger = [self._pane_title("Ledger", 0, left)] + self.table.render(
                left, body - 1, focused=self.pane == 0
            )
            matrix = self._matrix(matrix_width, body, focused=self.pane == 1)
            lines += hjoin((ledger, left), (matrix, matrix_width), gap=3)
        elif self.pane == 0:
            lines.append(self._pane_title("Ledger", 0, cells, "Tab fingerprints"))
            lines += self.table.render(cells, body - 1)
        else:
            lines += self._matrix(cells, body, focused=True, hint="Tab ledger")
        return lines

    def _pane_title(self, title: str, pane: int, cells: int, meta: str = "") -> str:
        colour = P.TEXT if self.pane == pane else P.SUBTLE
        left = paint(title, colour, bold=True)
        if meta:
            return fit(left + "  " + paint(meta, P.MUTED), cells)
        return fit(left, cells)

    def _composition(self, cells: int) -> str:
        total = sum(item.bytes for item in self.slices) or 1
        out: list[str] = []
        used = 0
        for index, item in enumerate(self.slices):
            if index == len(self.slices) - 1:
                size = cells - used
            else:
                size = round(item.bytes / total * cells)
            size = max(0, min(size, cells - used))
            if size:
                out.append(paint("█" * size, P.series_color(item.language)))
                used += size
        return "".join(out)

    def _legend(self, cells: int) -> str:
        parts = [
            paint("■ ", P.series_color(item.language))
            + paint(f"{item.language} {item.share:.0%}", P.SUBTLE)
            for item in self.slices
        ]
        line = ""
        for index, part in enumerate(parts):
            more = paint(f"+{len(parts) - index} more", P.MUTED)
            candidate = f"{line}   {part}" if line else part
            if width(candidate) + 3 + width(more) > cells and index < len(parts) - 1:
                return f"{line}   {more}" if line else more
            line = candidate
        return line

    def _matrix(
        self, cells: int, rows: int, *, focused: bool, hint: str = ""
    ) -> list[str]:
        """Repos down, languages across; each square's strength is that
        language's share of the repo. Column heads are the language colours,
        named in the legend above."""
        data = self.fingerprint
        title = self._pane_title("Repo fingerprints", 1, cells, hint)
        head = " " * (2 + _NAME + 1) + "".join(
            paint("■ ", P.series_color(language)) for language in data.languages
        )
        body = max(1, rows - 3)
        self._matrix_rows = body
        self.matrix_offset = max(
            0, min(self.matrix_offset, max(0, len(data.rows) - body))
        )
        bar = scrollbar(len(data.rows), self.matrix_offset, body)
        lines = [title, fit(head, cells)]
        for index, row in enumerate(
            data.rows[self.matrix_offset : self.matrix_offset + body]
        ):
            marks: list[str] = []
            for language in data.languages:
                share = row.shares.get(language, 0.0)
                if share <= 0:
                    marks.append(paint("■ ", P.HEAT[0]))
                else:
                    strength = 0.25 + 0.75 * min(1.0, share * 1.6)
                    marks.append(
                        paint("■ ", P.blend(P.BASE, P.series_color(language), strength))
                    )
            line = (
                private_mark(row.private)
                + fit(paint(row.alias, P.SUBTLE if focused else P.MUTED), _NAME)
                + " "
                + "".join(marks)
            )
            lines.append(fit(line, cells - 1) + bar[index])
        lines.append(paint("strength = that language's share of the repo", P.MUTED))
        return lines

    def key(self, key: str) -> bool:
        if key in ("tab", "backtab", "h", "l", "left", "right"):
            self.pane = 1 - self.pane
            return True
        if self.pane == 0:
            move = list_moves(key, self._rows - 8)
            if move is not None:
                self.table.move(move)
                return True
            if key in ("s", "S"):
                self.table.cycle_sort(reverse=key == "S")
                return True
            return False
        move = list_moves(key, self._matrix_rows)
        if move is not None:
            self.matrix_offset = max(0, self.matrix_offset + move)
            return True
        return False
