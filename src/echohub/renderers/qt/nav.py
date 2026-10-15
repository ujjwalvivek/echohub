"""Sidebar navigation: drawn icons, a label and a count per view.

Icons are painted line glyphs on a 14 px grid, so they stay crisp at any
scale and follow the item's state colour, with no icon font or image files.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QEnterEvent, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from . import theme as T

ITEM_HEIGHT = 28
ICON = 14.0

Icon = Callable[[QPainter], None]


def _today(p: QPainter) -> None:
    p.drawRect(QRectF(1.5, 2.5, 11, 10))
    p.drawLine(QPointF(1.5, 5.5), QPointF(12.5, 5.5))
    p.drawLine(QPointF(4.5, 1), QPointF(4.5, 3.5))
    p.drawLine(QPointF(9.5, 1), QPointF(9.5, 3.5))
    p.fillRect(QRectF(7.5, 8, 3, 2.5), p.pen().color())


def _projects(p: QPainter) -> None:
    for x, y in ((1.5, 1.5), (8, 1.5), (1.5, 8), (8, 8)):
        p.drawRect(QRectF(x, y, 4.5, 4.5))


def _activity(p: QPainter) -> None:
    p.drawPolyline(
        [
            QPointF(0.5, 7.5),
            QPointF(3.5, 7.5),
            QPointF(5.5, 2.5),
            QPointF(8.5, 12),
            QPointF(10.5, 7.5),
            QPointF(13.5, 7.5),
        ]
    )


def _languages(p: QPainter) -> None:
    for y, length in ((3, 11), (7, 7), (11, 9)):
        p.drawLine(QPointF(1.5, y), QPointF(1.5 + length, y))


def _contributions(p: QPainter) -> None:
    colour = p.pen().color()
    for row in range(3):
        for column in range(3):
            tint = QColor(colour)
            tint.setAlphaF(0.35 + 0.65 * ((row + column) % 3) / 2)
            p.fillRect(QRectF(1 + column * 4.5, 1 + row * 4.5, 3, 3), tint)


def _sources(p: QPainter) -> None:
    for y in (1.5, 5.5, 9.5):
        p.drawRect(QRectF(1.5, y, 11, 3))


def _constellation(p: QPainter) -> None:
    points = (QPointF(3, 3.5), QPointF(11, 5), QPointF(6, 11.5))
    p.drawLine(points[0], points[1])
    p.drawLine(points[1], points[2])
    p.drawLine(points[2], points[0])
    p.setBrush(p.pen().color())
    for point in points:
        p.drawEllipse(point, 1.8, 1.8)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _inspector(p: QPainter) -> None:
    p.drawPolyline(
        [QPointF(5, 1.5), QPointF(3, 1.5), QPointF(3, 6), QPointF(1.5, 7),
         QPointF(3, 8), QPointF(3, 12.5), QPointF(5, 12.5)]
    )  # fmt: skip
    p.drawPolyline(
        [QPointF(9, 1.5), QPointF(11, 1.5), QPointF(11, 6), QPointF(12.5, 7),
         QPointF(11, 8), QPointF(11, 12.5), QPointF(9, 12.5)]
    )  # fmt: skip


ICONS: dict[str, Icon] = {
    "Today": _today,
    "Projects": _projects,
    "Activity": _activity,
    "Languages": _languages,
    "Contributions": _contributions,
    "Sources": _sources,
    "Constellation": _constellation,
    "Inspector": _inspector,
}


class NavButton(QAbstractButton):
    """Icon, name and an optional count; the checked item gets the accent bar."""

    def __init__(self, name: str, fonts: T.Fonts) -> None:
        super().__init__()
        self.setText(name)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(ITEM_HEIGHT)
        self.count = ""
        self._hover = False
        self._icon = ICONS.get(name)
        self._font = T.font(fonts.ui, T.BODY)
        self._strong = T.font(fonts.ui, T.BODY, weight=QFont.Weight.Medium)
        self._mono = T.font(fonts.mono, T.CAPTION)

    def set_count(self, value: str) -> None:
        self.count = value
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(160, ITEM_HEIGHT)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, e: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()
        checked = self.isChecked()
        if checked:
            painter.fillRect(rect, QColor(T.SELECTED))
            painter.fillRect(QRect(0, 0, 2, rect.height()), QColor(T.ACCENT))
        elif self._hover:
            painter.fillRect(rect, QColor(T.HOVER))
        colour = T.TEXT if checked or self._hover else T.SUBTLE
        if self._icon is not None:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(12, (rect.height() - ICON) / 2)
            pen = QPen(QColor(T.ACCENT if checked else colour), 1.2)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            self._icon(painter)
            painter.restore()
        painter.setFont(self._strong if checked else self._font)
        painter.setPen(QColor(colour))
        text_rect = rect.adjusted(36, 0, -10, 0)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        if self.count:
            painter.setFont(self._mono)
            painter.setPen(QColor(T.SUBTLE if checked else T.MUTED))
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                self.count,
            )


class NavHeader(QWidget):
    """Uppercase caption over a group of items, like the table headers."""

    def __init__(self, text: str, fonts: T.Fonts) -> None:
        super().__init__()
        self._text = text.upper()
        self._font = T.font(fonts.ui, T.CAPTION, weight=QFont.Weight.DemiBold)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        self.setFixedHeight(26)

    def paintEvent(self, e: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setFont(self._font)
        painter.setPen(QColor(T.MUTED))
        painter.drawText(
            self.rect().adjusted(12, 0, -10, -4),
            int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft),
            self._text,
        )
