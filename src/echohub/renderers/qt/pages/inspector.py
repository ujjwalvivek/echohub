"""Inspector: the raw snapshot, key by key. A developer view.

Keys are grouped by their ``:``-separated parts into a tree (github › repo ›
field), each group showing how many keys it holds and each key its size.
The selected value is shown as highlighted JSON with line numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....formatting import human_bytes, relative_time
from ....types import JsonObject
from .. import theme as T
from ..widgets import StatStrip, button, label, page_header

_KEY_ROLE = Qt.ItemDataRole.UserRole + 1  # full key, or "" for a pure group
_META_ROLE = Qt.ItemDataRole.UserRole + 2  # right-hand text: count or size
_ROW = 24
_INDENT = 14


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode())


def _describe(value: object) -> str:
    if isinstance(value, dict):
        return f"object · {len(value)} fields"  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(value, list):
        return f"array · {len(value)} items"  # pyright: ignore[reportUnknownArgumentType]
    if value is None:
        return "null"
    return type(value).__name__


# Key tree --------------------------------------------------------------------


@dataclass
class _Node:
    name: str
    key: str = ""  # set when this exact path is itself a key
    children: dict[str, _Node] = field(default_factory=dict)

    def leaves(self) -> int:
        return (1 if self.key else 0) + sum(c.leaves() for c in self.children.values())


def _build_tree(keys: list[str]) -> _Node:
    root = _Node("")
    for key in keys:
        node = root
        for part in key.split(":"):
            node = node.children.setdefault(part, _Node(part))
        node.key = key
    return root


class _TreeCells(QStyledItemDelegate):
    """Indent, chevron, name and a right-aligned count or size, in mono."""

    def __init__(self, tree: QTreeWidget, fonts: T.Fonts) -> None:
        super().__init__(tree)
        self._tree = tree
        self._font = T.font(fonts.mono, T.SMALL)
        self._group = T.font(fonts.mono, T.SMALL, weight=QFont.Weight.DemiBold)
        self._meta = T.font(fonts.mono, T.CAPTION)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(200, _ROW)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        rect = QRect(option.rect)  # pyright: ignore[reportAttributeAccessIssue]
        state = option.state  # pyright: ignore[reportAttributeAccessIssue]
        painter.save()
        if state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(T.SELECTED))
            painter.fillRect(
                QRect(rect.left(), rect.top(), 2, rect.height()), QColor(T.ACCENT)
            )
        elif state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(T.HOVER))
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        left = rect.left() + 8 + depth * _INDENT
        middle = rect.center().y()
        has_children = self._tree.model().hasChildren(index)
        if has_children:
            model = self._tree.model()
            open_ = self._tree.isExpanded(
                model.index(index.row(), index.column(), index.parent())
            )
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T.SUBTLE))
            if open_:
                points = [
                    QPointF(left, middle - 2),
                    QPointF(left + 7, middle - 2),
                    QPointF(left + 3.5, middle + 2),
                ]
            else:
                points = [
                    QPointF(left + 1.5, middle - 3.5),
                    QPointF(left + 5.5, middle),
                    QPointF(left + 1.5, middle + 3.5),
                ]
            painter.drawPolygon(points)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        text_left = left + 14
        meta = str(index.data(_META_ROLE) or "")
        painter.setFont(self._meta)
        meta_width = (
            QFontMetricsF(self._meta).horizontalAdvance(meta) + 4 if meta else 0
        )
        painter.setPen(QColor(T.MUTED))
        painter.drawText(
            QRect(
                rect.right() - 10 - int(meta_width),
                rect.top(),
                int(meta_width),
                rect.height(),
            ),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            meta,
        )
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        font = self._group if has_children else self._font
        painter.setFont(font)
        selected = bool(state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor(T.TEXT if selected or has_children else T.SUBTLE))
        room = rect.right() - 16 - int(meta_width) - text_left
        elided = QFontMetricsF(font).elidedText(
            name, Qt.TextElideMode.ElideMiddle, room
        )
        painter.drawText(
            QRect(text_left, rect.top(), room, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )
        painter.restore()


class KeyTree(QTreeWidget):
    def __init__(self, store: JsonObject, fonts: T.Fonts) -> None:
        super().__init__()
        self.setObjectName("KeyTree")
        self.setHeaderHidden(True)
        self.setIndentation(0)  # the delegate draws the indent and chevrons
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setMouseTracking(True)
        self.setExpandsOnDoubleClick(False)
        self.setItemDelegate(_TreeCells(self, fonts))
        self._store = store
        root = _build_tree(sorted(store))
        for name in sorted(root.children, key=_group_order):
            self._add(self.invisibleRootItem(), root.children[name])
        self.itemClicked.connect(self._toggle)

    def _add(self, parent: QTreeWidgetItem, node: _Node) -> None:
        item = QTreeWidgetItem(parent, [node.name])
        item.setData(0, _KEY_ROLE, node.key)
        if node.children:
            item.setData(0, _META_ROLE, str(node.leaves()))
            item.setToolTip(0, f"{node.name}\n{node.leaves()} keys")
            if node.key:
                # This path is also a key of its own: list it first in the group.
                own = QTreeWidgetItem(item, ["(value)"])
                own.setData(0, _KEY_ROLE, node.key)
                own.setData(
                    0, _META_ROLE, human_bytes(_size(self._store.get(node.key)))
                )
            for name in sorted(node.children):
                self._add(item, node.children[name])
        else:
            value = self._store.get(node.key)
            item.setData(0, _META_ROLE, human_bytes(_size(value)))
            item.setToolTip(
                0, f"{node.key}\n{_describe(value)} · {human_bytes(_size(value))}"
            )

    def drawBranches(
        self, painter: QPainter, rect: QRect, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        return  # no platform branch lines; see _TreeCells

    def _toggle(self, item: QTreeWidgetItem) -> None:
        if item.childCount():
            item.setExpanded(not item.isExpanded())

    def keys_in_order(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            for child in _children(item):
                if child.data(0, _KEY_ROLE) and not child.childCount():
                    found.append(child)
                walk(child)

        walk(self.invisibleRootItem())
        return found

    def apply_filter(self, text: str) -> None:
        """Show keys containing ``text`` and the groups above them."""
        needle = text.strip().casefold()

        def visit(item: QTreeWidgetItem) -> bool:
            key = str(item.data(0, _KEY_ROLE) or "")
            shown = False
            for child in _children(item):
                shown = visit(child) or shown
            own = not item.childCount() and (not needle or needle in key.casefold())
            visible = shown or own
            item.setHidden(not visible)
            if needle and item.childCount():
                item.setExpanded(shown)
            return visible

        for top in _children(self.invisibleRootItem()):
            _ = visit(top)
            if not needle:
                top.setExpanded(top.text(0) == "_meta")

    def visible_keys(self) -> list[str]:
        return [
            str(item.data(0, _KEY_ROLE))
            for item in self.keys_in_order()
            if not _hidden_up(item)
        ]


def _children(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    found = (item.child(index) for index in range(item.childCount()))
    return [child for child in found if child is not None]


def _hidden_up(item: QTreeWidgetItem | None) -> bool:
    while item is not None:
        if item.isHidden():
            return True
        item = item.parent()
    return False


def _group_order(name: str) -> tuple[int, str]:
    # Bookkeeping first, then sources alphabetically.
    return (0 if name.startswith("_") else 1, name)


# JSON view -------------------------------------------------------------------


class _JsonHighlighter(QSyntaxHighlighter):
    _TOKEN = re.compile(
        r'(?P<key>"(?:[^"\\]|\\.)*"(?=\s*:))'
        r'|(?P<string>"(?:[^"\\]|\\.)*")'
        r"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
        r"|(?P<literal>\btrue\b|\bfalse\b|\bnull\b)"
        r"|(?P<punct>[{}\[\],:])"
    )

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        for name, colour in (
            ("key", T.IRIS),
            ("string", T.FOAM),
            ("number", T.GOLD),
            ("literal", T.LOVE),
            ("punct", T.MUTED),
        ):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._formats[name] = fmt

    def highlightBlock(self, text: str) -> None:
        for match in self._TOKEN.finditer(text):
            kind = match.lastgroup
            if kind is not None:
                self.setFormat(
                    match.start(), match.end() - match.start(), self._formats[kind]
                )


class _Gutter(QWidget):
    def __init__(self, editor: JsonView) -> None:
        super().__init__(editor)
        self._editor = editor

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_gutter(self, event)


class JsonView(QPlainTextEdit):
    """Read-only, highlighted JSON with a line-number gutter."""

    def __init__(self, fonts: T.Fonts) -> None:
        super().__init__()
        self.setObjectName("JsonView")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(T.font(fonts.mono, T.BODY))
        self._gutter_font = T.font(fonts.mono, T.CAPTION)
        self._gutter = _Gutter(self)
        self._highlighter = _JsonHighlighter(self.document())
        self.document().setDocumentMargin(8)
        self.blockCountChanged.connect(lambda _count: self._update_margins())
        self.updateRequest.connect(self._scroll_gutter)
        self._update_margins()

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 18 + int(
            QFontMetricsF(self._gutter_font).horizontalAdvance("9") * digits
        )

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        area = self.contentsRect()
        self._gutter.setGeometry(
            QRect(area.left(), area.top(), self.gutter_width(), area.height())
        )

    def paint_gutter(self, gutter: QWidget, event: QPaintEvent) -> None:
        painter = QPainter(gutter)
        painter.fillRect(event.rect(), QColor(T.PANEL))
        painter.fillRect(
            QRect(gutter.width() - 1, 0, 1, gutter.height()), QColor(T.BORDER)
        )
        painter.setFont(self._gutter_font)
        painter.setPen(QColor(T.MUTED))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            height = self.blockBoundingRect(block).height()
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(
                    QRect(0, int(top), gutter.width() - 8, int(height)),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    str(number + 1),
                )
            block = block.next()
            top += height
            number += 1


# Page ------------------------------------------------------------------------


class InspectorPage(QWidget):
    def __init__(self, store: JsonObject, fonts: T.Fonts) -> None:
        super().__init__()
        self._store = store
        self.current_key = ""

        strip = StatStrip()
        sources = {key.split(":", 1)[0] for key in store if not key.startswith("_")}
        strip.add("Keys", f"{len(store):,}", f"{len(sources)} sources")
        strip.add("Snapshot size", human_bytes(_size(store)), "as JSON")
        run = store.get("_meta:last_run")
        if isinstance(run, dict):
            processed = run.get("processed", 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            total = run.get("total", 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            skipped = run.get("budget_skipped", 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            failures = run.get("failures", [])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            strip.add(
                "Last run",
                str(run.get("strategy", "-")),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                f"{processed} of {total} processed · {skipped} deferred",
            )
            failed = len(failures) if isinstance(failures, list) else 0  # pyright: ignore[reportUnknownArgumentType]
            strip.add(
                "Failures",
                str(failed),
                "none" if not failed else "see _meta:last_run",
                "Good" if not failed else "Warn",
            )
        updated = store.get("_meta:last_updated")
        if isinstance(updated, str):
            strip.add("Updated", relative_time(updated), updated[:19].replace("T", " "))

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter keys…")
        self.filter.setClearButtonEnabled(True)
        self.tree = KeyTree(store, fonts)
        self.tree.setFixedWidth(340)

        self.path = label("", "KeyPath")
        self.kind = label("", "KeyKind")
        self.copy_key = button("Copy key", tooltip="Copy the key name")
        self.copy = button("Copy JSON", tooltip="Copy the formatted value")
        self.text = JsonView(fonts)

        self.filter.textChanged.connect(self.tree.apply_filter)
        self.tree.currentItemChanged.connect(self._on_item)
        self.copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.text.toPlainText())
        )
        self.copy_key.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.current_key)
        )

        left = QVBoxLayout()
        left.setSpacing(T.GAP)
        left.addWidget(self.filter)
        left.addWidget(self.tree, 1)

        head = QFrame()
        head.setObjectName("ViewerHead")
        top = QHBoxLayout(head)
        top.setContentsMargins(10, 6, 6, 6)
        top.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(self.path)
        titles.addWidget(self.kind)
        top.addLayout(titles, 1)
        top.addWidget(self.copy_key)
        top.addWidget(self.copy)
        viewer = QVBoxLayout()
        viewer.setSpacing(0)
        viewer.addWidget(head)
        viewer.addWidget(self.text, 1)

        body = QHBoxLayout()
        body.setSpacing(T.GAP)
        body.addLayout(left)
        body.addLayout(viewer, 1)

        page = QVBoxLayout(self)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        page.setSpacing(T.GAP)
        page.addLayout(
            page_header("Inspector", "The raw Echopoint snapshot, key by key")
        )
        page.addWidget(strip)
        page.addLayout(body, 1)

        self.tree.apply_filter("")
        first = self.tree.keys_in_order()
        if first:
            self.tree.setCurrentItem(first[0])

    def _on_item(self, current: QTreeWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        key = str(current.data(0, _KEY_ROLE) or "")
        if key:
            self.show_key(key)

    def show_key(self, key: str) -> None:
        self.current_key = key
        value = self._store.get(key)
        parts = key.split(":")
        self.path.setText(
            f"<span style='color:{T.MUTED}'>"
            + " / ".join(parts[:-1])
            + (" / " if len(parts) > 1 else "")
            + f"</span><span style='color:{T.TEXT}'>{parts[-1]}</span>"
        )
        self.kind.setText(f"{_describe(value)} · {human_bytes(_size(value))}")
        self.text.setPlainText(
            json.dumps(value, indent=2, ensure_ascii=False) if key else ""
        )

    def visible_keys(self) -> list[str]:
        return self.tree.visible_keys()
