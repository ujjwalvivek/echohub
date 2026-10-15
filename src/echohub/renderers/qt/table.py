"""One compact, sortable, filterable table used by every list view.

Cells are painted by ``_Cells`` and the header by ``_Header``, not by the
platform style: each ``Column`` names a ``kind`` (a name with a private mark,
a language swatch, a number with an inline bar, a tag pill, a recency-toned
time...) so a table reads as data, not as a grid of plain strings.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSize,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from ...formatting import compact as _compact
from . import theme as T
from .widgets import PADLOCK_WIDTH, draw_padlock

R = TypeVar("R")
_SORT_ROLE = Qt.ItemDataRole.UserRole + 1
_CELL_ROLE = Qt.ItemDataRole.UserRole + 2
_Index = QModelIndex | QPersistentModelIndex

ROW_HEIGHT = 26
HEADER_HEIGHT = 28
PAD_X = 10
BAR_TRACK = 40  # inline bar width in "bar" cells
BAR_GAP = 8
DIFF_TEXT = 40  # room for each count in "diff" cells
DIFF_GAP = 6
DIFF_CAP = 5000  # lines at which a "diff" bar is full
SWATCH = 8

# text    plain text (tone or TEXT)
# strong  primary name, medium weight; ``flag`` adds a padlock (private)
# muted   secondary text in SUBTLE
# code    mono, left-aligned, MUTED (hashes, URLs, versions)
# number  mono, right-aligned (tone or SUBTLE)
# bar     number with a sqrt-scaled bar against the column's largest value
# pill    tag in a bordered box (release tags, registries)
# swatch  square in the tone colour, then the text (languages)
# dot     square status mark in the tone colour, no text
# age     relative time; ``value`` is an ISO date, brighter when recent
# diff    diverging bar (log scale): ``pair`` gives (added, removed); removed grows left
#         in LOVE, added grows right in FOAM, counts at either end
Kind = Literal[
    "text",
    "strong",
    "muted",
    "code",
    "number",
    "bar",
    "pill",
    "swatch",
    "dot",
    "age",
    "diff",
]
_RIGHT = frozenset({"number", "bar", "age"})


@dataclass(frozen=True, slots=True)
class Column(Generic[R]):
    title: str
    # What the column sorts by (numbers sort as numbers, ISO dates as text).
    value: Callable[[R], object]
    # What it shows; defaults to str(value).
    text: Callable[[R], str] | None = None
    numeric: bool = False
    width: int | None = None
    stretch: bool = False
    tone: Callable[[R], str | None] | None = None
    tooltip: Callable[[R], str] | None = None
    # Drop the column when no row has anything in it (all zero or blank).
    hide_if_empty: bool = False
    # How the cell is drawn; defaults to "number" for numeric columns.
    kind: Kind | None = None
    # "strong" cells: True draws a padlock before the text.
    flag: Callable[[R], bool] | None = None
    # Header tooltip: what the column means.
    help: str = ""
    # "diff" cells: (added, removed).
    pair: Callable[[R], tuple[int, int]] | None = None

    def display(self, row: R) -> str:
        return self.text(row) if self.text else str(self.value(row))

    @property
    def style(self) -> Kind:
        return self.kind or ("number" if self.numeric else "text")

    @property
    def right_aligned(self) -> bool:
        return self.style in _RIGHT


@dataclass(frozen=True, slots=True)
class _Cell:
    column: Column[object]
    row: object
    peak: float


def _sort_key(value: object) -> object:
    # None sorts below everything instead of raising on comparison.
    if value is None:
        return ""
    return value


def _alignment(column: Column[R]) -> int:
    if column.style == "diff":
        return int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    horizontal = (
        Qt.AlignmentFlag.AlignRight
        if column.right_aligned
        else Qt.AlignmentFlag.AlignLeft
    )
    return int(horizontal | Qt.AlignmentFlag.AlignVCenter)


def _alpha_color(color: str, alpha: float) -> QColor:
    value = QColor(color)
    value.setAlphaF(alpha)
    return value


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _age_color(value: object) -> str:
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return T.MUTED
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - when).total_seconds() / 86400
    if days < 1:
        return T.TEXT
    if days < 30:
        return T.SUBTLE
    return T.MUTED


def _peak(column: Column[R], rows: Sequence[R]) -> float:
    """Largest value a "bar" or "diff" column draws, for scaling its bars."""
    if column.style == "bar":
        return max((_number(column.value(row)) for row in rows), default=0.0)
    if column.style == "diff" and column.pair is not None:
        return float(max((max(column.pair(row)) for row in rows), default=0))
    return 0.0


class _Model(QAbstractTableModel, Generic[R]):
    def __init__(self, columns: Sequence[Column[R]], rows: Sequence[R]) -> None:
        super().__init__()
        self.columns = list(columns)
        self.rows = list(rows)
        # Largest value per "bar" column, for the inline bars.
        self.peaks = [_peak(column, self.rows) for column in self.columns]

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008 > Qt default
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008 > Qt default
        return 0 if parent.isValid() else len(self.columns)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if orientation != Qt.Orientation.Horizontal:
            return None
        column = self.columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.title
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _alignment(column)
        if role == Qt.ItemDataRole.ToolTipRole and column.help:
            return f"{column.title}\n{column.help}"
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.display(row)
        if role == _SORT_ROLE:
            return _sort_key(column.value(row))
        if role == _CELL_ROLE:
            return _Cell(column, row, self.peaks[index.column()])  # pyright: ignore[reportArgumentType]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _alignment(column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return column.tooltip(row) if column.tooltip else None
        return None


class _Proxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.predicate: Callable[[int], bool] | None = None
        self.setSortRole(_SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        if self.predicate is not None and not self.predicate(source_row):
            return False
        if not self.text:
            return True
        model = self.sourceModel()
        needle = self.text.casefold()
        for column in range(model.columnCount()):
            value = model.data(model.index(source_row, column, source_parent))
            if needle in str(value).casefold():
                return True
        return False


class _Fonts:
    def __init__(self, fonts: T.Fonts) -> None:
        self.body = T.font(fonts.ui, T.BODY)
        self.strong = T.font(fonts.ui, T.BODY, weight=QFont.Weight.Medium)
        self.mono = T.font(fonts.mono, T.SMALL)
        self.pill = T.font(fonts.mono, T.CAPTION)
        self.header = T.font(fonts.ui, T.CAPTION, weight=QFont.Weight.DemiBold)
        self.header.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)


def _text_width(font: QFont, text: str) -> int:
    # Fractional advance rounded up: integer metrics can come out a pixel
    # short of what drawText needs, and the text then elides.
    return math.ceil(QFontMetricsF(font).horizontalAdvance(text)) + 2


def _draw_text(
    painter: QPainter, rect: QRect, text: str, font: QFont, color: str, align: int
) -> None:
    painter.setFont(font)
    painter.setPen(QColor(color))
    metrics = QFontMetrics(font)
    elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
    painter.drawText(rect, align, elided)


class _Cells(QStyledItemDelegate):
    def __init__(self, table: RecordTable[object], fonts: _Fonts) -> None:
        super().__init__(table)
        self._table = table
        self._fonts = fonts

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: _Index
    ) -> None:
        cell = index.data(_CELL_ROLE)
        if not isinstance(cell, _Cell):
            return
        rect = QRect(option.rect)  # pyright: ignore[reportAttributeAccessIssue]
        state = option.state  # pyright: ignore[reportAttributeAccessIssue]
        selected = bool(state & QStyle.StateFlag.State_Selected)
        painter.save()
        if selected:
            painter.fillRect(rect, QColor(T.SELECTED))
        elif index.row() == self._table.hover_row:
            painter.fillRect(rect, QColor(T.HOVER))
        painter.fillRect(
            QRect(rect.left(), rect.bottom(), rect.width(), 1), QColor(T.BORDER)
        )
        header = self._table.horizontalHeader()
        if selected and header.visualIndex(index.column()) == 0:
            painter.fillRect(
                QRect(rect.left(), rect.top(), 2, rect.height() - 1), QColor(T.ACCENT)
            )
        self._content(painter, rect.adjusted(PAD_X, 0, -PAD_X, -1), cell)
        painter.restore()

    def _content(self, painter: QPainter, inner: QRect, cell: _Cell) -> None:
        column, row = cell.column, cell.row
        text = column.display(row)
        tone = column.tone(row) if column.tone else None
        kind = column.style
        fonts = self._fonts
        left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        middle = inner.center().y()
        if kind == "strong":
            if column.flag is not None and column.flag(row):
                draw_padlock(painter, inner.left(), middle, T.MUTED)
                inner = inner.adjusted(PADLOCK_WIDTH, 0, 0, 0)
            _draw_text(painter, inner, text, fonts.strong, tone or T.TEXT, left)
        elif kind == "muted":
            _draw_text(painter, inner, text, fonts.body, tone or T.SUBTLE, left)
        elif kind == "code":
            _draw_text(painter, inner, text, fonts.mono, tone or T.MUTED, left)
        elif kind == "number":
            _draw_text(painter, inner, text, fonts.mono, tone or T.SUBTLE, right)
        elif kind == "age":
            color = tone or _age_color(column.value(row))
            _draw_text(painter, inner, text, fonts.mono, color, right)
        elif kind == "bar":
            value = _number(column.value(row))
            track = QRect(inner.left(), middle - 1, BAR_TRACK, 3)
            painter.fillRect(track, QColor(T.BORDER))
            if value > 0 and cell.peak > 0:
                share = math.sqrt(value / cell.peak)
                filled = max(1, round(BAR_TRACK * share))
                bar = QColor(tone or T.ACCENT)
                bar.setAlpha(200)
                painter.fillRect(
                    QRect(track.left(), track.top(), filled, track.height()), bar
                )
            number = inner.adjusted(BAR_TRACK + BAR_GAP, 0, 0, 0)
            _draw_text(painter, number, text, fonts.mono, T.TEXT, right)
        elif kind == "pill":
            if text:
                self._pill(painter, inner, text, tone or T.SUBTLE)
        elif kind == "swatch":
            color = tone or T.series_color(text)
            painter.fillRect(
                QRect(inner.left(), middle - SWATCH // 2, SWATCH, SWATCH),
                QColor(color),
            )
            rest = inner.adjusted(SWATCH + 8, 0, 0, 0)
            muted = color == T.MUTED
            _draw_text(
                painter, rest, text, fonts.body, T.MUTED if muted else T.TEXT, left
            )
        elif kind == "diff":
            self._diff(painter, inner, column, row, cell.peak)
        elif kind == "dot":
            size = 7
            painter.fillRect(
                QRect(inner.center().x() - size // 2, middle - size // 2, size, size),
                QColor(tone or T.MUTED),
            )
        else:
            _draw_text(painter, inner, text, fonts.body, tone or T.TEXT, left)

    def _diff(
        self,
        painter: QPainter,
        inner: QRect,
        column: Column[object],
        row: object,
        peak: float,
    ) -> None:
        if column.pair is None:
            return
        added, removed = column.pair(row)
        fonts = self._fonts
        middle = inner.center().y()
        axis = inner.center().x()
        half = max(10, (inner.width() - 2 * (DIFF_TEXT + DIFF_GAP)) // 2)
        # Log scale: commit sizes span 1 to a million lines, and a typical
        # commit should still show a bar next to a giant import.
        # The scale tops out at DIFF_CAP lines so one giant import does not
        # flatten every other bar; anything bigger fills its half.
        top = min(peak, DIFF_CAP)
        scale = 1 / math.log1p(top) if top > 0 else 0.0
        left = min(
            half, max(1 if removed else 0, round(half * math.log1p(removed) * scale))
        )
        right = min(
            half, max(1 if added else 0, round(half * math.log1p(added) * scale))
        )
        if removed:
            painter.fillRect(
                QRect(axis - left, middle - 2, left, 4), _alpha_color(T.LOVE, 0.85)
            )
        if added:
            painter.fillRect(
                QRect(axis + 1, middle - 2, right, 4), _alpha_color(T.FOAM, 0.85)
            )
        painter.fillRect(QRect(axis, middle - 5, 1, 10), QColor(T.BORDER_STRONG))
        removed_box = QRect(
            axis - half - DIFF_GAP - DIFF_TEXT, inner.top(), DIFF_TEXT, inner.height()
        )
        added_box = QRect(
            axis + half + DIFF_GAP, inner.top(), DIFF_TEXT, inner.height()
        )
        right_align = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left_align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _draw_text(
            painter,
            removed_box,
            f"−{_compact(removed)}" if removed else "0",
            fonts.mono,
            T.LOVE if removed else T.MUTED,
            right_align,
        )
        _draw_text(
            painter,
            added_box,
            f"+{_compact(added)}" if added else "0",
            fonts.mono,
            T.FOAM if added else T.MUTED,
            left_align,
        )

    def _pill(self, painter: QPainter, inner: QRect, text: str, color: str) -> None:
        width = min(inner.width(), _text_width(self._fonts.pill, text) + 12)
        box = QRect(inner.left(), inner.center().y() - 8, width, 16)
        painter.fillRect(box, QColor(T.SURFACE))
        painter.setPen(QColor(T.BORDER_STRONG))
        painter.drawRect(box.adjusted(0, 0, -1, -1))
        centre = int(Qt.AlignmentFlag.AlignCenter)
        _draw_text(
            painter, box.adjusted(6, 0, -6, 0), text, self._fonts.pill, color, centre
        )

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        cell = index.data(_CELL_ROLE)
        if not isinstance(cell, _Cell):
            return QSize(0, ROW_HEIGHT)
        column, row = cell.column, cell.row
        kind = column.style
        text = column.display(row)
        fonts = self._fonts
        font = {
            "strong": fonts.strong,
            "code": fonts.mono,
            "number": fonts.mono,
            "age": fonts.mono,
            "bar": fonts.mono,
            "pill": fonts.pill,
        }.get(kind, fonts.body)
        width = _text_width(font, text) + 2 * PAD_X
        if kind == "strong" and column.flag is not None and column.flag(row):
            width += PADLOCK_WIDTH
        elif kind == "bar":
            width += BAR_TRACK + BAR_GAP
        elif kind == "pill":
            width += 12
        elif kind == "swatch":
            width += SWATCH + 8
        elif kind == "dot":
            width = 7 + 2 * PAD_X
        elif kind == "diff":
            width = 2 * (DIFF_TEXT + DIFF_GAP + 40) + 2 * PAD_X
        return QSize(width, ROW_HEIGHT)


class _Header(QHeaderView):
    """Uppercase captions; the sorted column is bright with an accent arrow."""

    def __init__(self, parent: QWidget, fonts: _Fonts) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._font = fonts.header
        self._hover = -1
        self.setFixedHeight(HEADER_HEIGHT)
        self.setMouseTracking(True)
        self.setHighlightSections(False)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)

    def _title(self, logical: int) -> str:
        title = self.model().headerData(logical, Qt.Orientation.Horizontal)
        return str(title or "").upper()

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        painter.save()
        painter.fillRect(rect, QColor(T.PANEL))
        painter.fillRect(
            QRect(rect.left(), rect.bottom(), rect.width(), 1), QColor(T.BORDER_STRONG)
        )
        alignment = self.model().headerData(
            logicalIndex,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.TextAlignmentRole,
        )
        on_right = isinstance(alignment, int) and bool(
            alignment & Qt.AlignmentFlag.AlignRight
        )
        centred = isinstance(alignment, int) and bool(
            alignment & Qt.AlignmentFlag.AlignHCenter
        )
        sorted_here = self.sortIndicatorSection() == logicalIndex
        if sorted_here:
            color = T.TEXT
        elif logicalIndex == self._hover:
            color = T.SUBTLE
        else:
            color = T.MUTED
        title = self._title(logicalIndex)
        inner = rect.adjusted(PAD_X, 0, -PAD_X, -1)
        arrow_room = 10 if sorted_here else 0
        text_rect = (
            inner.adjusted(arrow_room, 0, 0, 0)
            if on_right
            else inner.adjusted(0, 0, -arrow_room, 0)
        )
        if centred:
            text_rect = inner
            horizontal = Qt.AlignmentFlag.AlignHCenter
        elif on_right:
            horizontal = Qt.AlignmentFlag.AlignRight
        else:
            horizontal = Qt.AlignmentFlag.AlignLeft
        flags = int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        _draw_text(painter, text_rect, title, self._font, color, flags)
        if sorted_here and title:
            width = min(
                QFontMetrics(self._font).horizontalAdvance(title), text_rect.width()
            )
            if centred:
                x = text_rect.center().x() + width // 2 + 4
            elif on_right:
                x = text_rect.right() - width - 9
            else:
                x = text_rect.left() + width + 4
            self._arrow(painter, x, inner.center().y())
        painter.restore()

    def _arrow(self, painter: QPainter, x: int, y: int) -> None:
        descending = self.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        if descending:
            points = [QPointF(x, y - 2), QPointF(x + 6, y - 2), QPointF(x + 3, y + 2)]
        else:
            points = [QPointF(x, y + 2), QPointF(x + 6, y + 2), QPointF(x + 3, y - 2)]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(T.ACCENT))
        painter.drawPolygon(QPolygonF(points))

    def sectionSizeFromContents(self, logicalIndex: int) -> QSize:
        width = _text_width(self._font, self._title(logicalIndex))
        return QSize(width + 2 * PAD_X + 14, HEADER_HEIGHT)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        hover = self.logicalIndexAt(e.position().toPoint())
        if hover != self._hover:
            self._hover = hover
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, event: object) -> None:
        self._hover = -1
        self.viewport().update()


class RecordTable(QTableView, Generic[R]):
    """Rows of ``R`` shown through ``Column`` specs.

    Emits ``selected(row)`` when the current row changes and ``activated(row)``
    on double-click or Enter.
    """

    selected = Signal(object)
    activated = Signal(object)

    def __init__(
        self,
        columns: Sequence[Column[R]],
        rows: Sequence[R],
        fonts: T.Fonts,
        parent: QWidget | None = None,
        *,
        empty: str = "Nothing matches",
    ) -> None:
        super().__init__(parent)
        visible = [
            column
            for column in columns
            if not column.hide_if_empty
            or any(column.value(row) not in (0, None, "", 0.0) for row in rows)
        ]
        self.hover_row = -1
        self._empty = empty
        self._fonts = _Fonts(fonts)
        self._model: _Model[R] = _Model(visible, rows)
        self._proxy = _Proxy()
        self._proxy.setSourceModel(self._model)
        self.setHorizontalHeader(_Header(self, self._fonts))
        self.setModel(self._proxy)
        self.setItemDelegate(_Cells(self, self._fonts))  # pyright: ignore[reportArgumentType]
        self.setSortingEnabled(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setMinimumSectionSize(ROW_HEIGHT)
        header = self.horizontalHeader()
        header.setMinimumSectionSize(36)
        for index, column in enumerate(visible):
            if column.stretch:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            elif column.width is not None:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
                self.setColumnWidth(index, column.width)
            else:
                header.setSectionResizeMode(
                    index, QHeaderView.ResizeMode.ResizeToContents
                )
        selection = self.selectionModel()
        selection.currentRowChanged.connect(self._on_current)
        self.doubleClicked.connect(self._on_activated)

    @property
    def visible_titles(self) -> list[str]:
        return [column.title for column in self._model.columns]

    def row_count(self) -> int:
        return self._proxy.rowCount()

    def row_at(self, proxy_row: int) -> R:
        source = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
        return self._model.rows[source.row()]

    def set_filter(self, text: str) -> None:
        self._proxy.text = text.strip()
        self._proxy.invalidate()

    def set_predicate(self, predicate: Callable[[R], bool] | None) -> None:
        rows = self._model.rows
        self._proxy.predicate = (
            None if predicate is None else (lambda index: predicate(rows[index]))
        )
        self._proxy.invalidate()

    def sort_by(
        self, title: str, order: Qt.SortOrder = Qt.SortOrder.DescendingOrder
    ) -> None:
        if title in self.visible_titles:
            self.sortByColumn(self.visible_titles.index(title), order)

    def select_first(self) -> None:
        if self._proxy.rowCount():
            self.selectRow(0)

    # Hover row -----------------------------------------------------------------

    def _track_hover(self, point: QPoint) -> None:
        index = self.indexAt(point)
        row = index.row() if index.isValid() else -1
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._track_hover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._track_hover(
            self.viewport().mapFromGlobal(event.globalPosition().toPoint())
        )
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:
        self.hover_row = -1
        self.viewport().update()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        # Rows move under a still pointer; keep the highlight on the one below it.
        if self.hover_row != -1:
            cursor = self.viewport().mapFromGlobal(self.cursor().pos())
            self._track_hover(cursor)

    def paintEvent(self, e: QPaintEvent) -> None:
        super().paintEvent(e)
        if self._proxy.rowCount():
            return
        painter = QPainter(self.viewport())
        _draw_text(
            painter,
            self.viewport().rect(),
            self._empty,
            self._fonts.body,
            T.MUTED,
            int(Qt.AlignmentFlag.AlignCenter),
        )

    # Signals ---------------------------------------------------------------------

    def _on_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.selected.emit(self._row_for(current))

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.activated.emit(self._row_for(index))

    def _row_for(self, index: QModelIndex) -> R:
        source = self._proxy.mapToSource(index)
        return self._model.rows[source.row()]
