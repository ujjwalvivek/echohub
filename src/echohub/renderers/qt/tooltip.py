"""Echohub's own tooltip: square, themed, with a title, detail and keycap.

``install_tooltips(app)`` routes every tooltip in the app here: a widget's
``toolTip()``, item-view cells (``ToolTipRole``) and header sections. Custom
painted widgets call ``show_tip`` / ``hide_tip`` directly.

Text convention, so plain ``setToolTip`` strings stay readable anywhere:

    "Refresh  ·  R\\nAsk Echopoint to collect now"

The first line is the title; a trailing "  ·  X" on it becomes a keycap;
the remaining lines are detail.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QHelpEvent,
    QPainter,
    QPaintEvent,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QWidget,
)
from shiboken6 import isValid

from . import theme as T

KEY_SEPARATOR = "  ·  "
MAX_WIDTH = 320
PAD_X = 9
PAD_Y = 6
LINE_GAP = 3
OFFSET = QPoint(12, 20)  # below and right of the cursor
WAKE_MS = 450
FADE_MS = 110


def split_tip(text: str) -> tuple[str, str, str]:
    """``(title, key, detail)`` from the tooltip text convention."""
    lines = text.strip().split("\n")
    title, key = lines[0], ""
    if KEY_SEPARATOR in title:
        title, key = (part.strip() for part in title.rsplit(KEY_SEPARATOR, 1))
        if len(key) > 6:  # not a shortcut, just a middle dot in prose
            title, key = lines[0], ""
    return title, key, "\n".join(line for line in lines[1:]).strip()


class TipWindow(QWidget):
    """The floating panel itself; one instance is reused for every tooltip."""

    def __init__(self, fonts: T.Fonts) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._title_font = T.font(fonts.ui, T.SMALL, weight=QFont.Weight.DemiBold)
        self._detail_font = T.font(fonts.ui, T.SMALL)
        self._key_font = T.font(fonts.mono, T.CAPTION)
        self.title = ""
        self.key = ""
        self.detail = ""
        self.owner: QWidget | None = None
        self.anchor = QPoint()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)

    # Layout ----------------------------------------------------------------

    def _key_width(self) -> float:
        if not self.key:
            return 0.0
        return QFontMetricsF(self._key_font).horizontalAdvance(self.key) + 8

    def _detail_rect(self, width: float) -> QRectF:
        metrics = QFontMetricsF(self._detail_font)
        return metrics.boundingRect(
            QRectF(0, 0, width, 10_000),
            int(Qt.TextFlag.TextWordWrap),
            self.detail,
        )

    def _measure(self) -> QSize:
        title = QFontMetricsF(self._title_font)
        key = self._key_width()
        line = title.horizontalAdvance(self.title) + (key + 10 if key else 0)
        width = min(float(MAX_WIDTH), max(line, 60.0))
        height = title.height()
        if self.detail:
            detail = self._detail_rect(MAX_WIDTH - 2 * PAD_X)
            width = min(float(MAX_WIDTH), max(width, detail.width()))
            height += LINE_GAP + self._detail_rect(width).height()
        return QSize(int(width) + 2 * PAD_X + 1, int(height) + 2 * PAD_Y + 1)

    # Showing -----------------------------------------------------------------

    def show_text(self, position: QPoint, text: str, owner: QWidget | None) -> None:
        title, key, detail = split_tip(text)
        if not title:
            self.hide_now()
            return
        same = self.isVisible() and (title, key, detail) == (
            self.title,
            self.key,
            self.detail,
        )
        self.title, self.key, self.detail = title, key, detail
        self.owner = owner
        self.anchor = QPoint(position)
        size = self._measure()
        self.resize(size)
        self.move(self._place(position, size))
        if same:
            return
        self.update()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()

    def _place(self, position: QPoint, size: QSize) -> QPoint:
        target = position + OFFSET
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if target.x() + size.width() > area.right():
            target.setX(max(area.left(), position.x() - size.width() - 4))
        if target.y() + size.height() > area.bottom():
            target.setY(max(area.top(), position.y() - size.height() - 8))
        return target

    def hide_now(self) -> None:
        self._fade.stop()
        self.owner = None
        self.hide()

    # Painting ----------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor(T.SURFACE))
        painter.setPen(QColor(T.BORDER_STRONG))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        title_metrics = QFontMetricsF(self._title_font)
        inner = QRectF(rect).adjusted(PAD_X, PAD_Y, -PAD_X, -PAD_Y)
        key_width = self._key_width()
        title_box = QRectF(
            inner.left(),
            inner.top(),
            inner.width() - (key_width + 10 if key_width else 0),
            title_metrics.height(),
        )
        painter.setFont(self._title_font)
        painter.setPen(QColor(T.TEXT))
        painter.drawText(
            title_box,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title_metrics.elidedText(
                self.title, Qt.TextElideMode.ElideRight, title_box.width()
            ),
        )
        if key_width:
            cap = QRectF(
                inner.right() - key_width,
                inner.top() + (title_metrics.height() - 14) / 2,
                key_width,
                14,
            )
            painter.fillRect(cap, QColor(T.BASE))
            painter.setPen(QColor(T.BORDER_STRONG))
            painter.drawRect(cap.adjusted(0, 0, -1, -1))
            painter.setFont(self._key_font)
            painter.setPen(QColor(T.SUBTLE))
            painter.drawText(cap, int(Qt.AlignmentFlag.AlignCenter), self.key)
        if self.detail:
            top = inner.top() + title_metrics.height() + LINE_GAP
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WordWrap)
            painter.setFont(self._detail_font)
            painter.setPen(QColor(T.SUBTLE))
            painter.drawText(
                QRectF(inner.left(), top, inner.width(), inner.bottom() - top),
                self.detail,
                option,
            )


class _TipStyle(QProxyStyle):
    """Fusion, with a quicker tooltip wake-up."""

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return WAKE_MS
        return super().styleHint(hint, option, widget, returnData)


class _Router(QObject):
    """Turns every ToolTip event into our tip, and hides it on movement."""

    _HIDE = frozenset(
        {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.FocusOut,
        }
    )

    def __init__(self, tip: TipWindow) -> None:
        super().__init__()
        self.tip = tip

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isValid(self.tip):
            return False  # shutting down: the tip window is already gone
        kind = event.type()
        if kind == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            if not isinstance(event, QHelpEvent):
                return False
            text = _text_at(watched, event.pos())
            if not text:
                return False  # let the event travel up to a parent's tooltip
            self.tip.show_text(event.globalPos(), text, watched)
            event.accept()
            return True
        if not self.tip.isVisible():
            return False
        if (
            kind in self._HIDE
            or kind == QEvent.Type.Leave
            and watched is self.tip.owner
        ):
            self.tip.hide_now()
        elif kind == QEvent.Type.MouseMove:
            moved = QCursor.pos() - self.tip.anchor
            if abs(moved.x()) + abs(moved.y()) > 6:
                self.tip.hide_now()
        return False


def _text_at(widget: QWidget, position: QPoint) -> str:
    """The tooltip under ``position``: an item view cell, a header section,
    or the widget's own ``toolTip()``."""
    parent = widget.parentWidget()
    if isinstance(widget, QHeaderView):
        section = widget.logicalIndexAt(position)
        if section >= 0:
            value = widget.model().headerData(
                section, widget.orientation(), Qt.ItemDataRole.ToolTipRole
            )
            return str(value or "")
        return ""
    if isinstance(parent, QAbstractItemView) and widget is parent.viewport():
        index = parent.indexAt(position)
        if index.isValid():
            return str(index.data(Qt.ItemDataRole.ToolTipRole) or "")
        return ""
    return widget.toolTip()


_tip: TipWindow | None = None
_router: _Router | None = None
_style: QProxyStyle | None = None


def install_tooltips(app: QApplication, fonts: T.Fonts) -> None:
    global _tip, _router, _style
    if _router is not None:
        return
    _tip = TipWindow(fonts)
    router = _Router(_tip)
    _router = router
    app.installEventFilter(router)
    app.aboutToQuit.connect(lambda: app.removeEventFilter(router))
    # Keep a Python reference: Qt does not own a style passed to setStyle,
    # and a collected proxy style crashes the next stylesheet change.
    _style = _TipStyle("Fusion")
    app.setStyle(_style)


def show_tip(position: QPoint, text: str, owner: QWidget | None = None) -> None:
    """For painted widgets that compute their own tooltip text."""
    if _tip is not None:
        _tip.show_text(position, text, owner)


def hide_tip() -> None:
    if _tip is not None:
        _tip.hide_now()


def current_tip() -> TipWindow | None:
    return _tip
