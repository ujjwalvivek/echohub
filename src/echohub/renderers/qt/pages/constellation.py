"""Constellation: an Obsidian-style graph of repos and the languages they use.

Repos are filled circles in their main language's colour; languages are ringed
hubs. A live force layout settles the graph, hovering lights up a node and its
neighbours, labels fade in as you zoom, and nodes can be dragged around.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ....formatting import human_bytes
from ....graph import ForceLayout, GraphNode, RepoGraph, build_graph
from ....models import DashboardState, Project
from .. import theme as T
from ..tooltip import hide_tip, show_tip
from ..widgets import button, label, page_header
from .detail import ProjectDetail, open_url

_FRAME_MS = 16
_TICKS_PER_FRAME = 2
_WARM_TICKS = 60  # settle a little before the first paint so it opens as a shape
_DRAG_THRESHOLD = 4
_FIT_PADDING = 36
_ZOOM_RANGE = (0.25, 4.0)
_DIM = 0.12  # opacity of nodes outside the highlighted set
_FADE_RATE = 0.22  # per frame, towards the target opacity
_GRID_PITCH = 24.0  # world units between background dots
_GRID_MIN_PX = 14.0  # never closer than this on screen
_LABEL_ZOOM = 0.55  # repo labels start fading in above this zoom


def _alpha(color: str, alpha: float) -> QColor:
    value = QColor(color)
    value.setAlphaF(max(0.0, min(1.0, alpha)))
    return value


class ConstellationView(QWidget):
    """The graph canvas. Click selects, double-click opens the repo, drag a
    node to move it, drag empty space to pan, wheel zooms around the cursor."""

    selected = Signal(str)
    activated = Signal(str)

    def __init__(self, graph: RepoGraph, ui_family: str) -> None:
        super().__init__()
        self.graph = graph
        self.layout_ = ForceLayout(graph)
        self.layout_.run(_WARM_TICKS)
        self._repo_font = T.font(ui_family, T.SMALL)
        self._hub_font = T.font(ui_family, T.SMALL, weight=QFont.Weight.DemiBold)
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._auto_fit = True  # follow the layout until the user zooms or pans
        self._press: QPointF | None = None
        self._press_node: GraphNode | None = None
        self._dragging = False
        self._hover = ""
        self.selected_alias = ""
        self._query = ""
        self._fade: dict[str, float] = {node.id: 1.0 for node in graph.nodes}
        self._circles: dict[str, QRectF] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._frame)
        self.setMouseTracking(True)
        self.setMinimumSize(420, 320)

    # Public ------------------------------------------------------------------

    def select(self, alias: str) -> None:
        self.selected_alias = alias
        self._wake()

    def set_query(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._wake()

    def fit(self) -> None:
        """Zoom and pan so the whole graph fills the canvas."""
        self._auto_fit = True
        self._fit_now()
        self._wake()

    def settle(self) -> None:
        """Finish the layout at once (tests and snapshots)."""
        while not self.layout_.settled:
            self.layout_.step()
        self._fit_now()
        self._fade = {node.id: self._target_fade(node) for node in self.graph.nodes}
        self.update()

    # Animation ---------------------------------------------------------------

    def _wake(self) -> None:
        if self.isVisible() and not self._timer.isActive():
            self._timer.start()
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_now()
        self._wake()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self._fit_now()

    def hideEvent(self, event: QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _frame(self) -> None:
        moving = not self.layout_.settled
        if moving:
            self.layout_.run(_TICKS_PER_FRAME)
            if self._auto_fit:
                self._fit_now()
        fading = False
        for node in self.graph.nodes:
            target = self._target_fade(node)
            current = self._fade.get(node.id, 1.0)
            if abs(target - current) > 0.01:
                self._fade[node.id] = current + (target - current) * _FADE_RATE * 2
                fading = True
            else:
                self._fade[node.id] = target
        self.update()
        if not moving and not fading and not self._dragging:
            self._timer.stop()

    # Highlight -----------------------------------------------------------------

    def _focus(self) -> str:
        return self._hover or self.selected_alias

    def _lit(self) -> set[str] | None:
        """Ids drawn at full strength, or None when nothing is highlighted."""
        focus = self._focus()
        if focus:
            return {focus} | self.graph.neighbours(focus)
        if self._query:
            return {
                node.id
                for node in self.graph.nodes
                if self._query in node.label.casefold()
            }
        return None

    def _target_fade(self, node: GraphNode) -> float:
        lit = self._lit()
        return 1.0 if lit is None or node.id in lit else _DIM

    # Geometry ----------------------------------------------------------------

    def _to_screen(self, x: float, y: float) -> QPointF:
        centre = QPointF(self.width() / 2, self.height() / 2)
        return centre + QPointF(x, y) * self._zoom + self._pan

    def _to_world(self, point: QPointF) -> tuple[float, float]:
        centre = QPointF(self.width() / 2, self.height() / 2)
        world = (point - centre - self._pan) / self._zoom
        return world.x(), world.y()

    def _radius(self, node: GraphNode) -> float:
        return max(2.5, node.radius * self._zoom)

    def _fit_now(self) -> None:
        nodes = self.graph.nodes
        if not nodes or self.width() < 10:
            return
        left = min(node.x - node.radius for node in nodes)
        right = max(node.x + node.radius for node in nodes)
        top = min(node.y - node.radius for node in nodes)
        bottom = max(node.y + node.radius + 14 for node in nodes)  # labels
        span_x = max(1.0, right - left)
        span_y = max(1.0, bottom - top)
        zoom = min(
            (self.width() - 2 * _FIT_PADDING) / span_x,
            (self.height() - 2 * _FIT_PADDING) / span_y,
        )
        self._zoom = max(_ZOOM_RANGE[0], min(_ZOOM_RANGE[1], zoom))
        middle = QPointF((left + right) / 2, (top + bottom) / 2)
        self._pan = -middle * self._zoom

    def _node_at(self, point: QPointF) -> GraphNode | None:
        best: tuple[float, GraphNode] | None = None
        for node in self.graph.nodes:
            centre = self._to_screen(node.x, node.y)
            distance = math.hypot(centre.x() - point.x(), centre.y() - point.y())
            if distance <= self._radius(node) + 4 and (
                best is None or distance < best[0]
            ):
                best = (distance, node)
        return best[1] if best else None

    # Painting ----------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        self._paint_grid(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        nodes = {node.id: node for node in self.graph.nodes}
        points = {node.id: self._to_screen(node.x, node.y) for node in self.graph.nodes}
        focus = self._focus()

        # Links: faint by default, accent when they touch the focused node.
        for link in self.graph.links:
            start, end = points.get(link.source), points.get(link.target)
            if start is None or end is None:
                continue
            if focus and focus in (link.source, link.target):
                pen = QPen(_alpha(T.ACCENT, 0.85), 1.3)
            else:
                strength = min(self._fade[link.source], self._fade[link.target])
                pen = QPen(_alpha(T.BORDER_STRONG, 0.75 * strength), 1.0)
            painter.setPen(pen)
            painter.drawLine(start, end)

        # Dim nodes first so highlighted ones sit on top.
        order = sorted(nodes.values(), key=lambda node: self._fade[node.id])
        for node in order:
            self._paint_node(painter, node, points[node.id])
        # Labels by priority: the focused node, hubs, highlighted repos, then
        # bigger repos. One that would overlap a placed label is skipped;
        # zooming in spreads the graph out and brings it back.
        lit = self._lit() or set()
        ranked = sorted(
            nodes.values(),
            key=lambda node: (
                node.id != focus,
                node.kind != "language",
                node.id not in lit,
                -node.weight,
            ),
        )
        placed: list[QRectF] = []
        circles = {
            node.id: QRectF(
                points[node.id].x() - self._radius(node),
                points[node.id].y() - self._radius(node),
                2 * self._radius(node),
                2 * self._radius(node),
            )
            for node in nodes.values()
        }
        self._circles = circles
        for node in ranked:
            self._paint_label(painter, node, points[node.id], focus, placed)

    def _paint_grid(self, painter: QPainter) -> None:
        """Faint dot matrix fixed to the graph, so it pans and zooms with it.
        The pitch doubles when zoomed out so dots never crowd together."""
        pitch = _GRID_PITCH * self._zoom
        while pitch < _GRID_MIN_PX:
            pitch *= 2
        origin = self._to_screen(0, 0)
        start_x = origin.x() % pitch
        start_y = origin.y() % pitch
        dots: list[QPointF] = []
        y = start_y
        while y < self.height():
            x = start_x
            while x < self.width():
                dots.append(QPointF(round(x), round(y)))
                x += pitch
            y += pitch
        painter.setPen(QPen(_alpha(T.BORDER_STRONG, 0.7), 1.0))
        painter.drawPoints(dots)

    def _paint_node(self, painter: QPainter, node: GraphNode, at: QPointF) -> None:
        fade = self._fade[node.id]
        radius = self._radius(node)
        colour = T.series_color(node.language)
        if node.kind == "language":
            painter.setPen(
                QPen(_alpha(colour, fade), max(1.5, 2.0 * min(1.0, self._zoom)))
            )
            painter.setBrush(_alpha(T.PANEL, 1.0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_alpha(colour, 0.9 * fade))
        painter.drawEllipse(at, radius, radius)
        if node.id == self.selected_alias:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_alpha(T.ACCENT, 1.0), 1.5))
            painter.drawEllipse(at, radius + 3.5, radius + 3.5)
        elif node.id == self._hover:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_alpha(T.TEXT, 0.8), 1.0))
            painter.drawEllipse(at, radius + 3, radius + 3)

    def _label_alpha(self, node: GraphNode) -> float:
        fade = self._fade[node.id]
        if node.kind == "language":
            return fade
        lit = self._lit()
        if lit is not None and node.id in lit:
            return fade
        # Repo labels fade in with zoom, as in Obsidian.
        return fade * max(0.0, min(1.0, (self._zoom - _LABEL_ZOOM) / 0.35))

    def _paint_label(
        self,
        painter: QPainter,
        node: GraphNode,
        at: QPointF,
        focus: str,
        placed: list[QRectF],
    ) -> None:
        alpha = self._label_alpha(node)
        if alpha < 0.04:
            return
        hub = node.kind == "language"
        font = self._hub_font if hub else self._repo_font
        width = QFontMetricsF(font).horizontalAdvance(node.label)
        top = at.y() + self._radius(node) + 3
        box = QRectF(at.x() - width / 2, top, width, 13)
        padded = box.adjusted(-3, -1, 3, 1)
        blocked = any(padded.intersects(other) for other in placed) or any(
            box.intersects(circle)
            for other, circle in self._circles.items()
            if other != node.id
        )
        if node.id != focus and blocked:
            return
        placed.append(padded)
        painter.setFont(font)
        if hub:
            colour = T.series_color(node.language)
        elif node.id == focus:
            colour = T.TEXT
        else:
            colour = T.SUBTLE
        painter.setPen(_alpha(colour, alpha))
        painter.drawText(
            box.adjusted(-2, 0, 2, 2),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            node.label,
        )

    # Interaction -------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        zoom = max(_ZOOM_RANGE[0], min(_ZOOM_RANGE[1], self._zoom * factor))
        point = event.position()
        world_x, world_y = self._to_world(point)
        centre = QPointF(self.width() / 2, self.height() / 2)
        self._zoom = zoom
        self._pan = point - centre - QPointF(world_x, world_y) * zoom
        self._auto_fit = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
            self._press_node = self._node_at(event.position())
            self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = event.position()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = point - self._press
            if self._dragging or abs(delta.x()) + abs(delta.y()) > _DRAG_THRESHOLD:
                self._dragging = True
                self._auto_fit = False
                if self._press_node is not None:
                    # Pin the node under the cursor; the rest flows around it.
                    self._press_node.pinned = self._to_world(point)
                    self.layout_.reheat(0.3)
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self._wake()
                else:
                    self._pan += delta
                    self._press = point
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self.update()
            return
        node = self._node_at(point)
        hover = node.id if node else ""
        if node is not None:
            show_tip(event.globalPosition().toPoint(), self._tip(node), self)
        else:
            hide_tip()
        if hover != self._hover:
            self._hover = hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if node
                else Qt.CursorShape.ArrowCursor
            )
            self._wake()

    def _tip(self, node: GraphNode) -> str:
        links = len(self.graph.neighbours(node.id))
        if node.kind == "language":
            return f"{node.label}\n{human_bytes(node.code)} across {links} repos"
        parts = [node.language, human_bytes(node.code) if node.code else "no code"]
        if node.private:
            parts.append("private")
        hint = "click for details · double-click opens GitHub"
        return f"{node.label}\n{' · '.join(parts)}\n{hint}"

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._press_node is not None:
            self._press_node.pinned = None
        if not self._dragging:
            node = self._node_at(event.position())
            alias = node.id if node else ""
            self.select(alias)
            if node is not None and node.kind == "repo":
                self.selected.emit(node.id)
            else:
                self.selected.emit("")
        self._press = None
        self._press_node = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._wake()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        node = self._node_at(event.position())
        if node is not None and node.kind == "repo":
            self.activated.emit(node.id)

    def leaveEvent(self, event: object) -> None:
        if self._hover:
            self._hover = ""
            self._wake()


class ConstellationPage(QWidget):
    def __init__(self, state: DashboardState, fonts: T.Fonts) -> None:
        super().__init__()
        projects: dict[str, Project] = {
            project.alias: project for project in state.projects
        }
        self.view = ConstellationView(build_graph(state.projects), fonts.ui)
        self.detail = ProjectDetail(fonts)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Highlight repos or languages…")
        self.filter.setFixedWidth(240)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.view.set_query)
        fit = button("Fit", tooltip="Zoom to show the whole graph")
        fit.clicked.connect(self.view.fit)
        self.view.selected.connect(
            lambda alias: self.detail.show_project(projects.get(alias))
        )
        self.view.activated.connect(
            lambda alias: (
                open_url(projects[alias].html_url) if alias in projects else None
            )
        )

        frame = QFrame()
        frame.setObjectName("Card")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.view)

        content = QVBoxLayout()
        content.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        content.setSpacing(T.GAP)
        content.addLayout(
            page_header(
                "Constellation",
                "Repos linked to the languages they're written in",
                self.filter,
                fit,
            )
        )
        content.addWidget(frame, 1)
        content.addWidget(
            label(
                "Circles are repos, sized by code · rings are languages · "
                "drag nodes, drag to pan, scroll to zoom, double-click opens GitHub",
                "Muted",
            )
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(content, 1)
        root.addWidget(self.detail)

    def settle(self) -> None:
        self.view.settle()
