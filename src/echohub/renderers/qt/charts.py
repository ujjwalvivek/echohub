"""Charts shared by the pages: a filled line over a faint grid."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...formatting import compact
from . import theme as T

CHART_MIN_HEIGHT = 120


def _nice_step(peak: float, lines: int = 4) -> float:
    """A round grid step (1, 2, 2.5 or 5 x 10^n) giving about ``lines`` lines."""
    if peak <= 0:
        return 1.0
    raw = peak / lines
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


class AreaChart(QWidget):
    """A filled line over a faint grid: round-value rows with axis labels and a
    column per point. Square markers; ``None`` values leave a gap (months
    still to come). Hovering shows a guide line and the exact value."""

    point_clicked = Signal(int)

    AXIS = 40  # room for the y labels
    TOP = 22
    BOTTOM = 20
    RIGHT = 12

    def __init__(
        self,
        ui_family: str,
        mono_family: str,
        colour: str,
        *,
        clickable: bool = False,
    ) -> None:
        super().__init__()
        self._labels: list[str] = []
        self._values: list[int | None] = []
        self._selected = -1
        self._hover = -1
        self._colour = colour
        self._clickable = clickable
        self._font = T.font(ui_family, T.CAPTION)
        self._mono = T.font(mono_family, T.CAPTION)
        self.setMouseTracking(True)
        self.setMinimumSize(260, CHART_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_points(
        self, labels: list[str], values: list[int | None], selected: int = -1
    ) -> None:
        self._labels = labels
        self._values = values
        self._selected = selected
        self.update()

    def set_selected(self, index: int) -> None:
        self._selected = index
        self.update()

    # Geometry ------------------------------------------------------------------

    def _plot(self) -> QRectF:
        return QRectF(
            self.AXIS,
            self.TOP,
            self.width() - self.AXIS - self.RIGHT,
            self.height() - self.TOP - self.BOTTOM,
        )

    def _x(self, index: int, plot: QRectF) -> float:
        count = max(1, len(self._values))
        return plot.left() + plot.width() * (index + 0.5) / count

    def _scale(self) -> tuple[float, float]:
        peak = max((value for value in self._values if value is not None), default=0)
        step = _nice_step(float(peak))
        top = step * max(1, math.ceil(peak / step)) if peak else step * 4
        return step, top

    def _y(self, value: float, plot: QRectF, top: float) -> float:
        return plot.bottom() - plot.height() * (value / top if top else 0)

    def _index_at(self, x: float) -> int:
        plot = self._plot()
        if not self._values or not plot.left() <= x <= plot.right():
            return -1
        slot = plot.width() / len(self._values)
        return min(len(self._values) - 1, int((x - plot.left()) / slot))

    # Painting ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        plot = self._plot()
        step, top = self._scale()
        count = len(self._values)
        if not count:
            return

        # Grid: a row per step with its value, a column per point.
        painter.setFont(self._mono)
        value = 0.0
        while value <= top + 1e-9:
            y = round(self._y(value, plot, top)) + 0.5
            line = T.BORDER_STRONG if value == 0 else T.BORDER
            painter.setPen(QPen(QColor(line), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(T.MUTED))
            painter.drawText(
                QRectF(0, y - 7, self.AXIS - 8, 14),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                compact(round(value)),
            )
            value += step
        grid = QColor(T.BORDER)
        grid.setAlphaF(0.6)
        painter.setPen(QPen(grid, 1))
        for index in range(count):
            x = round(self._x(index, plot)) + 0.5
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        # Hover and selection guides sit under the line.
        for index, colour in (
            (self._hover, T.BORDER_STRONG),
            (self._selected, T.ACCENT),
        ):
            if 0 <= index < count:
                x = round(self._x(index, plot)) + 0.5
                guide = QColor(colour)
                guide.setAlphaF(0.55 if colour == T.ACCENT else 1.0)
                painter.setPen(QPen(guide, 1))
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        # Area and line, broken where a value is missing.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        runs: list[list[QPointF]] = [[]]
        for index, item in enumerate(self._values):
            if item is None:
                if runs[-1]:
                    runs.append([])
                continue
            runs[-1].append(QPointF(self._x(index, plot), self._y(item, plot, top)))
        fill = QLinearGradient(0, plot.top(), 0, plot.bottom())
        strong, faint = QColor(self._colour), QColor(self._colour)
        strong.setAlphaF(0.28)
        faint.setAlphaF(0.02)
        fill.setColorAt(0, strong)
        fill.setColorAt(1, faint)
        for run in runs:
            if not run:
                continue
            area = QPainterPath(QPointF(run[0].x(), plot.bottom()))
            for point in run:
                area.lineTo(point)
            area.lineTo(QPointF(run[-1].x(), plot.bottom()))
            area.closeSubpath()
            painter.fillPath(area, fill)
            painter.setPen(QPen(QColor(self._colour), 1.6))
            painter.drawPolyline(run)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Markers, value labels and x labels. With many points, label every
        # n-th x tick and show values only where they matter.
        peak_value = max((v for v in self._values if v is not None), default=0)
        slot = plot.width() / count
        widest = max(
            (
                QFontMetricsF(self._font).horizontalAdvance(text)
                for text in self._labels
            ),
            default=0.0,
        )
        every = max(1, math.ceil((widest + 10) / slot))
        crowded = count > 14
        last = max((i for i, v in enumerate(self._values) if v is not None), default=-1)
        for index, item in enumerate(self._values):
            x = self._x(index, plot)
            chosen = index == self._selected
            active = chosen or index == self._hover
            if item is not None:
                y = self._y(item, plot, top)
                size = 7 if active else 5
                painter.fillRect(
                    QRectF(x - size / 2, y - size / 2, size, size),
                    QColor(T.ACCENT if chosen else self._colour),
                )
                show_value = (
                    not crowded or active or item == peak_value or index == last
                )
                bright = active or item == peak_value
                text = f"{item:,}" if active else compact(item)
                # A solid backing keeps the value legible where the line
                # runs behind it.
                if show_value:
                    painter.setFont(self._mono)
                    width = QFontMetricsF(self._mono).horizontalAdvance(text) + 6
                    box = QRectF(x - width / 2, y - 19, width, 12)
                    painter.fillRect(box, QColor(T.PANEL))
                    painter.setPen(QColor(T.TEXT if bright else T.SUBTLE))
                    painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
            # Count back from the newest point so it always keeps its label.
            if (count - 1 - index) % every and not active:
                continue
            painter.setFont(self._mono if self._clickable else self._font)
            painter.setPen(QColor(T.TEXT if active else T.MUTED))
            painter.drawText(
                QRectF(x - 40, plot.bottom() + 4, 80, 14),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                self._labels[index],
            )

    # Interaction -----------------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self._index_at(event.position().x())
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event: object) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self._index_at(event.position().x())
        if self._clickable and index >= 0:
            self.set_selected(index)
            self.point_clicked.emit(index)
