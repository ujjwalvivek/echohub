"""Custom window chrome: our own title bar, square corners, native behaviour.

On Windows the window keeps its resize-frame and caption styles, so side
snapping, Win+Left/Right, the system menu and the drop shadow still come from
the OS. Maximising is switched off: the layout is sized for a window, not a
whole 2560 px screen. We only tell Windows that the whole window is client
area (WM_NCCALCSIZE) and which parts act as caption or resize edges
(WM_NCHITTEST), and switch off Windows 11's rounded corners.

Elsewhere, Qt's startSystemMove/startSystemResize give drag and resize through
the platform.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from . import theme as T

TITLE_HEIGHT = 32
RESIZE_MARGIN = 6
ICON_SIZE = 18
LIGHT_SIZE = 12  # traffic-light diameter
LIGHT_SLOT = 20  # click target width; the gap between lights is SLOT - SIZE


def native_windows() -> bool:
    """True when running on the real Windows platform plugin (not offscreen)."""
    return sys.platform == "win32" and QGuiApplication.platformName() == "windows"


# The app icon's artwork sits in a padded 512 px tile; in the title bar we
# draw just the mark, cropped to its bounds and without the tile.
_MARK_BOX = QRectF(112, 112, 288, 288)
_TILE = re.compile(rb'<rect width="512" height="512"[^>]*/>')


def _mark_pixmap(svg: bytes, scale: float) -> QPixmap:
    renderer = QSvgRenderer(_TILE.sub(b"", svg))
    renderer.setViewBox(_MARK_BOX)
    side = round(ICON_SIZE * scale)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    _ = painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


class TrafficLight(QAbstractButton):
    """One macOS-style window control: a coloured dot that shows its glyph on hover."""

    def __init__(self, kind: str, color: str, tip: str) -> None:
        super().__init__()
        self.kind = kind  # "close", "min" or "max"
        self._color = QColor(color)
        self.reveal = False  # set by LightGroup while the pointer is over any light
        self.active = True  # dimmed while the window is in the background
        self.setToolTip(tip)
        self.setFixedSize(LIGHT_SLOT, TITLE_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        lit = self.active or self.reveal
        fill = QColor(self._color if lit else T.BORDER_STRONG)
        if self.isDown():
            fill = fill.darker(125)
        size = float(LIGHT_SIZE)
        dot = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(dot)
        if not self.reveal:
            return
        pen = QPen(QColor(T.BASE))
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = dot.center()
        arm = size * 0.25
        horizontal = (QPointF(-arm, 0), QPointF(arm, 0))
        vertical = (QPointF(0, -arm), QPointF(0, arm))
        if self.kind == "close":
            lines = (
                (QPointF(-arm, -arm), QPointF(arm, arm)),
                (QPointF(-arm, arm), QPointF(arm, -arm)),
            )
        elif self.kind == "min":
            lines = (horizontal,)
        else:
            lines = (horizontal, vertical)
        for start, stop in lines:
            painter.drawLine(center + start, center + stop)


class LightGroup(QWidget):
    """The window controls. Hovering any of them reveals all glyphs, as on macOS."""

    def __init__(self, lights: list[TrafficLight]) -> None:
        super().__init__()
        self.lights = lights
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for light in lights:
            row.addWidget(light)

    def _reveal(self, shown: bool) -> None:
        for light in self.lights:
            light.reveal = shown
            light.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._reveal(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._reveal(False)
        super().leaveEvent(event)

    def set_active(self, active: bool) -> None:
        for light in self.lights:
            light.active = active
            light.update()


class TitleBar(QFrame):
    """Zed-style strip: icon, title, actions, traffic lights. Square, no OS chrome."""

    def __init__(
        self, window: QWidget, title: str, icon: QIcon, mark_svg: bytes = b""
    ) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(TITLE_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(8)
        self.close_button = TrafficLight("close", T.LOVE, "Close")
        self.minimize = TrafficLight("min", T.GOLD, "Minimize")
        self.close_button.clicked.connect(window.close)
        self.minimize.clicked.connect(window.showMinimized)
        # Right edge, close outermost where Windows users expect it.
        # No maximise: the layout is built for a fixed-ish window, not 2560 px.
        self.lights = LightGroup([self.minimize, self.close_button])
        mark = QLabel()
        mark.setObjectName("TitleIcon")
        mark.setPixmap(
            _mark_pixmap(mark_svg, window.devicePixelRatioF())
            if mark_svg
            else icon.pixmap(ICON_SIZE, ICON_SIZE)
        )
        row.addWidget(mark)
        self.title = QLabel(title)
        self.title.setObjectName("TitleText")
        row.addWidget(self.title)
        self.page = QLabel("")
        self.page.setObjectName("TitlePage")
        row.addWidget(self.page)
        row.addStretch(1)
        row.addSpacing(4)
        row.addWidget(self.lights)
        self._row = row

    def add_action(self, widget: QWidget) -> None:
        """Put a control in the title bar, just left of the traffic lights."""
        self._row.insertWidget(
            self._row.indexOf(self.lights) - 1,
            widget,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

    def set_page(self, name: str) -> None:
        self.page.setText(f"/  {name}" if name else "")

    def sync_state(self) -> None:
        self.lights.set_active(self._window.isActiveWindow())

    def is_caption_point(self, point: QPoint) -> bool:
        """True where a press should drag the window (not on a button)."""
        child = self.childAt(point)
        return self.rect().contains(point) and not isinstance(child, QAbstractButton)

    # Non-Windows fallbacks; on Windows these presses never reach Qt because
    # the area reports itself as the native caption.
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            not native_windows()
            and event.button() == Qt.MouseButton.LeftButton
            and self.is_caption_point(event.position().toPoint())
        ):
            _ = self._window.windowHandle().startSystemMove()
            return
        super().mousePressEvent(event)


# Title-bar actions -------------------------------------------------------------

ACTION_SIZE = 26


def _check_icon(p: QPainter) -> None:
    """Arrow down into a tray: fetch the snapshot if it changed."""
    p.drawLine(QPointF(7, 1.5), QPointF(7, 8.5))
    p.drawPolyline([QPointF(4, 5.8), QPointF(7, 8.8), QPointF(10, 5.8)])
    p.drawPolyline(
        [QPointF(1.5, 8.5), QPointF(1.5, 12.5), QPointF(12.5, 12.5), QPointF(12.5, 8.5)]
    )


def _refresh_icon(p: QPainter) -> None:
    """Circular arrow: ask Echopoint to collect now."""
    p.drawArc(QRectF(2, 2, 10, 10), 100 * 16, 290 * 16)
    p.drawPolyline([QPointF(5.2, 0.6), QPointF(7.6, 2.2), QPointF(5.6, 4.6)])


class IconButton(QAbstractButton):
    """A square title-bar action drawn as a line icon, like the nav icons.

    ``spinning`` rotates the icon (Refresh while a refresh runs)."""

    def __init__(
        self, icon: Callable[[QPainter], None], tip: str, colour: str = T.SUBTLE
    ) -> None:
        super().__init__()
        self._icon = icon
        self._colour = colour
        self._hover = False
        self._angle = 0.0
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._turn)
        self.setToolTip(tip)
        self.setFixedSize(ACTION_SIZE, ACTION_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def spinning(self) -> bool:
        return self._spin.isActive()

    def set_spinning(self, spinning: bool) -> None:
        if spinning:
            self._spin.start()
        else:
            self._spin.stop()
            self._angle = 0.0
        self.update()

    def _turn(self) -> None:
        self._angle = (self._angle + 6.0) % 360.0
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, e: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()
        enabled = self.isEnabled()
        if self.isDown():
            painter.fillRect(rect, QColor(T.SELECTED))
        elif self._hover and enabled:
            painter.fillRect(rect, QColor(T.HOVER))
        if self.spinning:
            colour = self._colour
        elif not enabled:
            colour = T.MUTED
        elif self._hover and self._colour == T.SUBTLE:
            colour = T.TEXT
        else:
            colour = self._colour
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(rect.width() / 2, rect.height() / 2)
        painter.rotate(self._angle)
        painter.translate(-7, -7)
        pen = QPen(QColor(colour), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._icon(painter)


def check_button(tip: str) -> IconButton:
    return IconButton(_check_icon, tip)


def refresh_button(tip: str) -> IconButton:
    return IconButton(_refresh_icon, tip, T.ACCENT)


def sync_chrome(event: QEvent, title_bar: TitleBar) -> None:
    if event.type() in (
        QEvent.Type.WindowStateChange,
        QEvent.Type.ActivationChange,
    ):
        title_bar.sync_state()


def _edge_hit(window: QWidget, local: QPoint) -> tuple[bool, bool, bool, bool]:
    margin = RESIZE_MARGIN
    return (
        local.x() < margin,
        local.x() >= window.width() - margin,
        local.y() < margin,
        local.y() >= window.height() - margin,
    )


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _WM_NCCALCSIZE = 0x0083
    _WM_NCHITTEST = 0x0084
    _WM_SYSCOMMAND = 0x0112
    _SC_MAXIMIZE = 0xF030
    _SC_SIZE = 0xF000
    _GWL_STYLE = -16
    _WS_THICKFRAME = 0x00040000
    _WS_CAPTION = 0x00C00000
    _WS_MINIMIZEBOX = 0x00020000
    _WS_MAXIMIZEBOX = 0x00010000
    # SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
    _SWP_FLAGS = 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010
    _HTCAPTION = 2
    _HT_EDGES = {
        (True, False, False, False): 10,  # left
        (False, True, False, False): 11,  # right
        (False, False, True, False): 12,  # top
        (True, False, True, False): 13,  # top-left
        (False, True, True, False): 14,  # top-right
        (False, False, False, True): 15,  # bottom
        (True, False, False, True): 16,  # bottom-left
        (False, True, False, True): 17,  # bottom-right
    }
    _DWMWA_WINDOW_CORNER_PREFERENCE = 33
    _DWMWA_BORDER_COLOR = 34
    _DWMWCP_DONOTROUND = 1
    _SM_CXSIZEFRAME = 32
    _SM_CYSIZEFRAME = 33
    _SM_CXPADDEDBORDER = 92

    class _NCCalcSizeParams(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    def _colorref(hex_color: str) -> int:
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
        return red | (green << 8) | (blue << 16)

    def _set_dwm(
        hwnd: int, attribute: int, value: ctypes.c_int | ctypes.c_uint
    ) -> None:
        _ = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
        )

    def install_chrome(window: QWidget) -> None:
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        window.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        if not native_windows():
            return
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
        # Frameless windows lose these styles; put them back so the OS keeps
        # providing snap, resize, minimise animation and the shadow. Without
        # WS_MAXIMIZEBOX, Windows itself won't maximise on a caption
        # double-click.
        style |= _WS_THICKFRAME | _WS_CAPTION | _WS_MINIMIZEBOX
        _ = user32.SetWindowLongW(hwnd, _GWL_STYLE, style & ~_WS_MAXIMIZEBOX)
        # The system menu (Alt+Space, right-click on the title bar) would
        # still list Maximize, and Size for a fixed window; drop dead entries.
        menu = user32.GetSystemMenu(hwnd, False)
        _ = user32.DeleteMenu(menu, _SC_MAXIMIZE, 0)
        if window.minimumSize() == window.maximumSize():
            _ = user32.DeleteMenu(menu, _SC_SIZE, 0)
        _ = user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)
        _set_dwm(
            hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.c_int(_DWMWCP_DONOTROUND)
        )
        _set_dwm(hwnd, _DWMWA_BORDER_COLOR, ctypes.c_uint(_colorref(T.BORDER_STRONG)))

    def handle_native_event(
        window: QWidget, title_bar: TitleBar, event_type: bytes, message: int
    ) -> tuple[bool, int] | None:
        """Answer WM_NCCALCSIZE / WM_NCHITTEST; None means let Qt handle it."""
        if event_type != b"windows_generic_MSG" or not message:
            return None
        msg = wintypes.MSG.from_address(message)
        if msg.message == _WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == _SC_MAXIMIZE:
            return True, 0  # Win+Up, drag-to-top and anything else asking to maximise
        if msg.message == _WM_NCCALCSIZE:
            # Ask Windows, not Qt: on restore this arrives before Qt updates
            # isMaximized(), and a stale answer insets the restored window,
            # leaving an unpainted strip along the top and clipping the right.
            if msg.wParam and ctypes.windll.user32.IsZoomed(msg.hWnd):
                # A maximised window hangs its invisible frame off-screen; pull
                # the client area back in so nothing is clipped.
                user32 = ctypes.windll.user32
                params = _NCCalcSizeParams.from_address(msg.lParam)
                padded = user32.GetSystemMetrics(_SM_CXPADDEDBORDER)
                frame_x = user32.GetSystemMetrics(_SM_CXSIZEFRAME) + padded
                frame_y = user32.GetSystemMetrics(_SM_CYSIZEFRAME) + padded
                rect = params.rgrc[0]
                rect.left += frame_x
                rect.top += frame_y
                rect.right -= frame_x
                rect.bottom -= frame_y
            # Zero: the whole window is client area, so no OS title bar or frame.
            return True, 0
        if msg.message == _WM_NCHITTEST:
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            # Measure from the client origin, not the window rect: when
            # maximised the invisible frame sits off-screen, so the two differ.
            origin = wintypes.POINT(0, 0)
            _ = ctypes.windll.user32.ClientToScreen(
                int(window.winId()), ctypes.byref(origin)
            )
            scale = window.devicePixelRatioF() or 1.0
            local = QPoint(round((x - origin.x) / scale), round((y - origin.y) / scale))
            fixed = window.minimumSize() == window.maximumSize()
            if not fixed and not ctypes.windll.user32.IsZoomed(msg.hWnd):
                edges = _edge_hit(window, local)
                if any(edges):
                    return True, _HT_EDGES.get(edges, 1)
            if title_bar.is_caption_point(title_bar.mapFrom(window, local)):
                return True, _HTCAPTION
        return None

else:

    def install_chrome(window: QWidget) -> None:
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        window.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)

    def handle_native_event(
        window: QWidget, title_bar: TitleBar, event_type: bytes, message: int
    ) -> tuple[bool, int] | None:
        return None
