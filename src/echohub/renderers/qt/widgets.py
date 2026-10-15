"""Small building blocks shared by the Qt pages."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...formatting import compact
from ...today import HeatmapDay
from . import theme as T
from .tooltip import hide_tip, show_tip

PADLOCK_WIDTH = 14  # the mark plus its gap before the name


def draw_padlock(painter: QPainter, left: float, middle: float, color: str) -> None:
    """The private-repo mark: an 8 px padlock, vertically centred on ``middle``."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(left + 1.6, middle - 5.0, 4.8, 6.0), 0, 180 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRect(QRectF(left, middle - 1.5, 8.0, 5.5))
    painter.restore()


def padlock(color: str = T.MUTED) -> QLabel:
    """The private mark as a widget, for rows built from labels."""
    scale = 2.0
    pixmap = QPixmap(round(8 * scale), round(10 * scale))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.scale(scale, scale)
    draw_padlock(painter, 0, 5.5, color)
    _ = painter.end()
    pixmap.setDevicePixelRatio(scale)
    widget = QLabel()
    widget.setPixmap(pixmap)
    widget.setToolTip("Private repository")
    widget.setStyleSheet("background: transparent;")
    return widget


def repo_name(alias: str, private: bool, name: str = "") -> QWidget:
    """A repo name, led by the padlock when the repo is private."""
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(PADLOCK_WIDTH - 8)
    if private:
        row.addWidget(padlock())
    row.addWidget(label(alias, name), 1)
    return box


def label(text: str = "", name: str = "", *, tooltip: str = "") -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


class ElidedLabel(QLabel):
    """A label that ends in "…" instead of pushing its neighbours aside."""

    def __init__(self, text: str = "", name: str = "") -> None:
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width()
        )
        painter.drawText(rect, int(self.alignment()), text)


def hbox(*widgets: QWidget | None, spacing: int = 8, margins: int = 0) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(margins, margins, margins, margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            # Text that can shorten takes the spare room; the rest keep their size.
            layout.addWidget(widget, 1 if isinstance(widget, ElidedLabel) else 0)
    return layout


class Card(QFrame):
    """Bordered panel with a small title row; content goes in ``body``."""

    def __init__(self, title: str, meta: str = "", *, fill: bool = False) -> None:
        super().__init__()
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.CARD_X, T.CARD_Y, T.CARD_X, T.CARD_Y)
        outer.setSpacing(6)
        self.title = label(title, "CardTitle")
        self.meta = label(meta, "CardMeta")
        self.header = hbox(self.title, None, self.meta)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(0)
        self.body.setContentsMargins(0, 0, 0, 0)
        if fill:
            # The content (a table, a scroll area) takes all the height.
            outer.addLayout(self.body, 1)
        else:
            outer.addLayout(self.body)
            # Cards placed side by side share a height; keep content at the top.
            outer.addStretch(1)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)


def divider(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


class StatStrip(QFrame):
    """One bordered strip of headline numbers, divided like Zed's status items."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add(
        self, caption: str, value: str, note: str = "", tone: str = "StatNote"
    ) -> None:
        if self._layout.count():
            self._layout.addWidget(divider(vertical=True))
        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        column = QVBoxLayout(cell)
        column.setContentsMargins(12, 7, 12, 8)
        column.setSpacing(1)
        column.addWidget(label(caption, "StatLabel"))
        column.addWidget(label(value, "StatValue"))
        column.addWidget(label(note or " ", tone))
        self._layout.addWidget(cell, 1)


class Heatmap(QWidget):
    """GitHub-style contribution grid: weeks as columns, Sunday on top."""

    # Small squares with clear gaps, like GitHub's grid, at a fixed size.
    CELL = 10
    GAP = 4
    LEFT = 26
    TOP = 14

    def __init__(self, days: Sequence[HeatmapDay], ui_family: str, today: date) -> None:
        super().__init__()
        self._days = list(days)
        self._today = today
        self._font = T.font(ui_family, T.CAPTION)
        nonzero = sorted(day.count for day in self._days if day.count > 0)
        # Negative counts only pad the first week to Sunday; they stay blank.
        # Quartiles of active days, as GitHub does, so one huge day does not
        # wash every other cell out.
        self._thresholds = (
            [
                nonzero[min(len(nonzero) - 1, int(len(nonzero) * q))]
                for q in (0.25, 0.5, 0.75)
            ]
            if nonzero
            else []
        )
        self._cells: list[tuple[QRectF, HeatmapDay]] = []
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())

    def _weeks(self) -> int:
        return max(1, math.ceil(len(self._days) / 7))

    def sizeHint(self) -> QSize:
        step = self.CELL + self.GAP
        return QSize(
            self.LEFT + self._weeks() * step - self.GAP, self.TOP + 7 * step - self.GAP
        )

    def _level(self, count: int) -> int:
        if count <= 0 or not self._thresholds:
            return 0
        return 1 + sum(count > threshold for threshold in self._thresholds)

    def paintEvent(self, event: QPaintEvent) -> None:
        cell = self.CELL
        step = cell + self.GAP
        painter = QPainter(self)
        # Square cells on whole pixels stay crisp without antialiasing; text
        # still renders smoothly.
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._font)
        painter.setPen(T.color(T.MUTED))
        for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            painter.drawText(
                QRectF(0, self.TOP + row * step, self.LEFT - 6, cell),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                name,
            )
        self._cells = []
        last_month = None
        for index, day in enumerate(self._days):
            column, row = divmod(index, 7)
            x = self.LEFT + column * step
            if day.count < 0:
                continue
            if (
                day.day.month != last_month
                and day.day.day <= 7
                and (row == 0 or index < 7)
            ):
                painter.setPen(T.color(T.MUTED))
                painter.drawText(QPointF(x, self.TOP - 5), day.day.strftime("%b"))
                last_month = day.day.month
            rect = QRectF(x, self.TOP + row * step, cell, cell)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(T.color(T.HEAT[self._level(day.count)]))
            painter.drawRect(rect)
            if day.day == self._today:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(T.color(T.ROSE), 1.0))
                painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            self._cells.append((rect, day))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = event.position()
        for rect, day in self._cells:
            if rect.contains(point):
                noun = "contribution" if day.count == 1 else "contributions"
                show_tip(
                    event.globalPosition().toPoint(),
                    f"{day.count} {noun}\n{day.day.strftime('%A %d %B %Y')}",
                    self,
                )
                return
        hide_tip()


class Legend(QWidget):
    """ "Less ▪▪▪▪▪ More" key for the heatmap."""

    def __init__(self, ui_family: str) -> None:
        super().__init__()
        self._font = T.font(ui_family, T.CAPTION)
        self.setFixedSize(130, 14)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        painter.setPen(T.color(T.MUTED))
        painter.drawText(
            QRectF(0, 0, 28, 14), int(Qt.AlignmentFlag.AlignVCenter), "Less"
        )
        for index, shade in enumerate(T.HEAT):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(shade))
            painter.drawRect(QRectF(30 + index * 13, 2, 10, 10))
        painter.setPen(T.color(T.MUTED))
        painter.drawText(
            QRectF(98, 0, 32, 14), int(Qt.AlignmentFlag.AlignVCenter), "More"
        )


class ShareBar(QWidget):
    """A thin horizontal bar: ``share`` of the width in ``color``."""

    def __init__(self, share: float, color: str, height: int = 6) -> None:
        super().__init__()
        self._share = max(0.0, min(1.0, share))
        self._color = color
        self.setFixedHeight(height)
        self.setMinimumWidth(40)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(T.color(T.SELECTED))
        painter.drawRect(self.rect())
        painter.setBrush(T.color(self._color))
        painter.drawRect(QRectF(0, 0, self.width() * self._share, self.height()))


class StackedBar(QWidget):
    """Parts of a whole side by side, each in its own colour."""

    def __init__(
        self, parts: Sequence[tuple[str, float, str]], height: int = 8
    ) -> None:
        super().__init__()
        total = sum(max(0.0, value) for _, value, _ in parts) or 1.0
        self._parts = [
            (name, max(0.0, value) / total, color) for name, value, color in parts
        ]
        self.setFixedHeight(height)
        self.setMouseTracking(True)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        x = 0.0
        for _, share, color in self._parts:
            width = self.width() * share
            painter.setBrush(T.color(color))
            # One pixel of page background between parts keeps them readable.
            painter.drawRect(QRectF(x, 0, max(0.0, width - 1), self.height()))
            x += width

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = 0.0
        for name, share, _ in self._parts:
            width = self.width() * share
            if x <= event.position().x() < x + width:
                show_tip(
                    event.globalPosition().toPoint(),
                    f"{name}\n{share:.1%} of the code",
                    self,
                )
                return
            x += width


def page_header(title: str, subtitle: str = "", *extras: QWidget) -> QHBoxLayout:
    """Title and subtitle on the left, optional controls on the right."""
    titles = QVBoxLayout()
    titles.setSpacing(0)
    titles.addWidget(label(title, "PageTitle"))
    if subtitle:
        titles.addWidget(label(subtitle, "PageSubtitle"))
    header = QHBoxLayout()
    header.setSpacing(6)
    header.addLayout(titles, 1)
    for extra in extras:
        header.addWidget(extra, 0, Qt.AlignmentFlag.AlignBottom)
    return header


def button(text: str, kind: str = "Ghost", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(kind)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


class PanelHeader(QWidget):
    """Side-panel section header: a hairline, an uppercase caption, a count."""

    def __init__(self, text: str, meta: str, fonts: T.Fonts) -> None:
        super().__init__()
        self._text = text.upper()
        self._meta = meta
        self._font = T.font(fonts.ui, T.CAPTION, weight=QFont.Weight.DemiBold)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        self._mono = T.font(fonts.mono, T.CAPTION)
        self.setFixedHeight(30)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), 1, QColor(T.BORDER))
        text_rect = self.rect().adjusted(0, 0, 0, -5)
        bottom_left = int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
        painter.setFont(self._font)
        painter.setPen(QColor(T.MUTED))
        painter.drawText(text_rect, bottom_left, self._text)
        if self._meta:
            painter.setFont(self._mono)
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight),
                self._meta,
            )


class Chips(QWidget):
    """Small bordered tags that wrap onto as many lines as they need."""

    HEIGHT = 18
    GAP = 4
    PAD = 6

    def __init__(self, items: Sequence[str], fonts: T.Fonts) -> None:
        super().__init__()
        self._items = list(items)
        self._font = T.font(fonts.mono, T.CAPTION)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _boxes(self, width: int) -> list[QRectF]:
        metrics = QFontMetricsF(self._font)
        boxes: list[QRectF] = []
        x = y = 0.0
        for item in self._items:
            box_width = math.ceil(metrics.horizontalAdvance(item)) + 2 * self.PAD
            if x > 0 and x + box_width > width:
                x = 0.0
                y += self.HEIGHT + self.GAP
            boxes.append(QRectF(x, y, box_width, self.HEIGHT))
            x += box_width + self.GAP
        return boxes

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        boxes = self._boxes(width)
        return int(boxes[-1].bottom()) + 1 if boxes else 0

    def sizeHint(self) -> QSize:
        return QSize(200, self.heightForWidth(200))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setFont(self._font)
        for item, box in zip(self._items, self._boxes(self.width()), strict=True):
            painter.fillRect(box, QColor(T.SURFACE))
            painter.setPen(QColor(T.BORDER_STRONG))
            painter.drawRect(box.adjusted(0, 0, -1, -1))
            painter.setPen(QColor(T.SUBTLE))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), item)


class DiffBar(QWidget):
    """Removed (left, LOVE) and added (right, FOAM) around a centre tick, with
    the counts at either end; log scale, like Activity's Changes column."""

    TEXT = 40
    CAP = 5000

    def __init__(self, added: int, removed: int, fonts: T.Fonts) -> None:
        super().__init__()
        self._added = added
        self._removed = removed
        self._font = T.font(fonts.mono, T.SMALL)
        self.setFixedSize(190, 18)
        self.setToolTip(f"Changes\n{added:,} lines added · {removed:,} removed")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        axis = self.width() // 2
        middle = self.height() // 2
        half = axis - self.TEXT - 6
        scale = 1 / math.log1p(self.CAP)

        def length(value: int) -> int:
            if not value:
                return 0
            return min(half, max(1, round(half * math.log1p(value) * scale)))

        left, right = length(self._removed), length(self._added)
        red, green = QColor(T.LOVE), QColor(T.FOAM)
        red.setAlphaF(0.85)
        green.setAlphaF(0.85)
        painter.fillRect(axis - left, middle - 2, left, 4, red)
        painter.fillRect(axis + 1, middle - 2, right, 4, green)
        painter.fillRect(axis, middle - 5, 1, 10, QColor(T.BORDER_STRONG))
        painter.setFont(self._font)
        painter.setPen(QColor(T.LOVE if self._removed else T.MUTED))
        painter.drawText(
            QRectF(0, 0, self.TEXT, self.height()),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"−{compact(self._removed)}" if self._removed else "0",
        )
        painter.setPen(QColor(T.FOAM if self._added else T.MUTED))
        painter.drawText(
            QRectF(self.width() - self.TEXT, 0, self.TEXT, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"+{compact(self._added)}" if self._added else "0",
        )
