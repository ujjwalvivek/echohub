"""Languages: what the portfolio is written in, overall and per repo."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....formatting import human_bytes
from ....insights import Fingerprint, language_fingerprint
from ....models import DashboardState, LanguageSlice
from .. import theme as T
from ..table import Column, RecordTable
from ..tooltip import hide_tip, show_tip
from ..widgets import PADLOCK_WIDTH, Card, StackedBar, draw_padlock, label, page_header

_LEGEND_COUNT = 8
_MATRIX_LANGUAGES = 18

COLUMNS: list[Column[LanguageSlice]] = [
    Column(
        "Language",
        lambda s: s.language.lower(),
        lambda s: s.language,
        stretch=True,
        tone=lambda s: T.series_color(s.language),
        kind="swatch",
        help="Language as GitHub detects it",
    ),
    Column(
        "Bytes",
        lambda s: s.bytes,
        lambda s: human_bytes(s.bytes),
        numeric=True,
        kind="bar",
        tone=lambda s: T.series_color(s.language),
        help="GitHub language bytes across all repos",
    ),
    Column(
        "Share",
        lambda s: s.share,
        lambda s: f"{s.share:.1%}",
        numeric=True,
        help="Share of all code",
    ),
    Column(
        "Repos", lambda s: s.projects, numeric=True, help="Repos that use this language"
    ),
    Column(
        "Private",
        lambda s: s.private_bytes,
        lambda s: human_bytes(s.private_bytes) if s.private_bytes else "",
        numeric=True,
        hide_if_empty=True,
        help="Bytes from private repos",
    ),
]


def _largest_repos(state: DashboardState) -> dict[str, tuple[str, int]]:
    """Per language, the repo holding the most of it and how many bytes."""
    largest: dict[str, tuple[str, int]] = {}
    for project in state.projects:
        for language, value in project.languages.items():
            if value > largest.get(language, ("", 0))[1]:
                largest[language] = (project.alias, value)
    return largest


def _largest_text(entry: tuple[str, int] | None) -> str:
    if entry is None:
        return ""
    alias, value = entry
    return f"{alias}  ·  {human_bytes(value)}"


class FingerprintMatrix(QWidget):
    """Repos down, languages across; each square's strength is that
    language's share of the repo."""

    CELL = 10
    GAP = 4
    LEFT = 136
    TOP = 92

    def __init__(self, fingerprint: Fingerprint, ui_family: str) -> None:
        super().__init__()
        self._data = fingerprint
        self._font = T.font(ui_family, T.SMALL)
        self._cells: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        step = self.CELL + self.GAP
        return QSize(
            self.LEFT + len(self._data.languages) * step,
            self.TOP + len(self._data.rows) * step,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        step = self.CELL + self.GAP
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._font)
        for column, language in enumerate(self._data.languages):
            x = self.LEFT + column * step + self.CELL - 1
            painter.save()
            painter.translate(QPointF(x, self.TOP - 6))
            painter.rotate(-90)
            painter.setPen(T.color(T.series_color(language)))
            painter.drawText(QPointF(0, 0), language)
            painter.restore()
        self._cells = []
        for row_index, row in enumerate(self._data.rows):
            y = self.TOP + row_index * step
            painter.setPen(T.color(T.SUBTLE))
            indent = PADLOCK_WIDTH if row.private else 0
            if row.private:
                draw_padlock(painter, 0, y + self.CELL / 2, T.MUTED)
                painter.setPen(T.color(T.SUBTLE))
            elided = painter.fontMetrics().elidedText(
                row.alias, Qt.TextElideMode.ElideRight, self.LEFT - 12 - indent
            )
            painter.drawText(
                QRectF(indent, y - 2, self.LEFT - 12 - indent, self.CELL + 4),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                elided,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            for column, language in enumerate(self._data.languages):
                rect = QRectF(self.LEFT + column * step, y, self.CELL, self.CELL)
                share = row.shares.get(language, 0.0)
                if share <= 0:
                    painter.setBrush(T.color(T.HEAT[0]))
                else:
                    tint = QColor(T.series_color(language))
                    tint.setAlphaF(0.25 + 0.75 * min(1.0, share * 1.6))
                    painter.setBrush(tint)
                painter.drawRect(rect)
                tip = (
                    f"{row.alias}\n{language} is {share:.0%} of its code"
                    if share > 0
                    else f"{row.alias}\nno {language}"
                )
                self._cells.append((rect, tip))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = event.position()
        for rect, tip in self._cells:
            if rect.contains(point):
                show_tip(event.globalPosition().toPoint(), tip, self)
                return
        hide_tip()


class LanguagesPage(QWidget):
    def __init__(self, state: DashboardState, fonts: T.Fonts) -> None:
        super().__init__()
        slices = state.analytics.languages
        total = sum(item.bytes for item in slices)
        private = sum(item.private_bytes for item in slices)
        subtitle = f"{human_bytes(total)} of code across {len(slices)} languages"
        if private:
            subtitle += f" · {human_bytes(private)} from private repos"

        composition = Card("Composition", "GitHub language bytes, not lines of code")
        composition.add(
            StackedBar(
                [
                    (item.language, item.bytes, T.series_color(item.language))
                    for item in slices
                ]
            )
        )
        legend = QHBoxLayout()
        legend.setSpacing(14)
        for item in slices[:_LEGEND_COUNT]:
            swatch = label("■")
            swatch.setStyleSheet(f"color: {T.series_color(item.language)};")
            legend.addWidget(swatch)
            legend.addSpacing(-10)
            legend.addWidget(label(f"{item.language} {item.share:.0%}", "Subtle"))
        if len(slices) > _LEGEND_COUNT:
            legend.addWidget(label(f"+{len(slices) - _LEGEND_COUNT} more", "Muted"))
        legend.addStretch(1)
        composition.body.addSpacing(6)
        composition.body.addLayout(legend)

        largest = _largest_repos(state)
        # Annotate the variable, not the call: Column[LanguageSlice](...) sets
        # __orig_class__ on the instance, which a frozen slots dataclass
        # rejects on Python 3.11.
        largest_column: Column[LanguageSlice] = Column(
            "Largest repo",
            lambda s: largest.get(s.language, ("", 0))[0].lower(),
            lambda s: _largest_text(largest.get(s.language)),
            width=220,
            kind="muted",
            help="The repo with the most code in this language",
        )
        columns = [COLUMNS[0], largest_column, *COLUMNS[1:]]
        self.table: RecordTable[LanguageSlice] = RecordTable(columns, slices, fonts)
        self.table.sort_by("Bytes")
        ledger = QVBoxLayout()
        ledger.setSpacing(4)
        ledger.addWidget(label("Ledger", "CardTitle"))
        ledger.addWidget(self.table, 1)

        fingerprint = language_fingerprint(state.projects, limit=_MATRIX_LANGUAGES)
        matrix_card = Card(
            "Repo fingerprints",
            "square strength = that language's share of the repo",
            fill=True,
        )
        matrix = FingerprintMatrix(fingerprint, fonts.ui)
        scroll = QScrollArea()
        scroll.setWidget(matrix)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        matrix_card.add(scroll)
        # The card hugs the matrix (plus room for the scroll bar); the ledger
        # takes the rest of the width instead of leaving a blank strip.
        matrix_card.setFixedWidth(matrix.width() + 2 * T.CARD_X + 14)

        lower = QHBoxLayout()
        lower.setSpacing(T.GAP)
        lower.addLayout(ledger, 1)
        lower.addWidget(matrix_card)

        page = QVBoxLayout(self)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        page.setSpacing(T.GAP)
        page.addLayout(page_header("Languages", subtitle))
        page.addWidget(composition)
        page.addLayout(lower, 1)
