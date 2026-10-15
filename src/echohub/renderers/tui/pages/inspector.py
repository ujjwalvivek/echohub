"""Inspector: the raw Echopoint snapshot, key by key.

A key tree on the left (keys split on ":", bookkeeping first), the selected
value as coloured JSON on the right. Narrow terminals show one at a time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .... import palette as P
from ....formatting import human_bytes, relative_time
from ....types import JsonObject
from ..style import fit, hjoin, paint, surface, width
from ..widgets import Stat, page_title, scrollbar, stat_strip
from .base import Context, FilterField, Page, list_moves

TREE = 40
SIDE_FROM = 100
_TOKEN = re.compile(
    r'(?P<key>"(?:[^"\\]|\\.)*"(?=\s*:))'
    r'|(?P<string>"(?:[^"\\]|\\.)*")'
    r"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<literal>\btrue\b|\bfalse\b|\bnull\b)"
    r"|(?P<punct>[{}\[\],:])"
)
_TOKEN_COLOURS = {
    "key": P.IRIS,
    "string": P.FOAM,
    "number": P.GOLD,
    "literal": P.LOVE,
    "punct": P.MUTED,
}


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


def highlight(line: str) -> str:
    """One line of indented JSON in the viewer's colours."""
    out: list[str] = []
    last = 0
    for match in _TOKEN.finditer(line):
        out.append(line[last : match.start()])
        kind = match.lastgroup or "punct"
        out.append(paint(match.group(), _TOKEN_COLOURS[kind]))
        last = match.end()
    out.append(line[last:])
    return "".join(out)


@dataclass
class _Node:
    name: str
    path: str
    key: str = ""  # set when this exact path is itself a key
    children: dict[str, _Node] = field(default_factory=dict)

    def leaves(self) -> int:
        return (1 if self.key else 0) + sum(c.leaves() for c in self.children.values())


@dataclass(frozen=True, slots=True)
class TreeRow:
    path: str
    name: str
    depth: int
    key: str
    group: bool
    open: bool
    meta: str


def _group_order(name: str) -> tuple[int, str]:
    # Bookkeeping first, then sources alphabetically.
    return (0 if name.startswith("_") else 1, name)


def _build_tree(keys: list[str]) -> _Node:
    root = _Node("", "")
    for key in keys:
        node = root
        for part in key.split(":"):
            path = f"{node.path}:{part}" if node.path else part
            node = node.children.setdefault(part, _Node(part, path))
        node.key = key
    return root


class InspectorPage(Page):
    name = "Inspector"
    keys = (
        ("Tab", "switch between the key tree and the value"),
        ("Enter / l", "open a group, or show a key's value"),
        ("h", "close the group, or go to its parent"),
        ("/", "filter keys"),
    )

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.store: JsonObject = {}
        self.root = _Node("", "")
        self.expanded: set[str] = set()
        self.rows: list[TreeRow] = []
        self.index = 0
        self.offset = 0
        self.pane = 0  # 0 tree, 1 value
        self.value_offset = 0
        self.stats: list[Stat] = []
        self.filter = FilterField(lambda _text: self._rebuild())
        self._value_key = ""
        self._value_lines: list[str] = []
        self._body = 0

    @property
    def typing(self) -> bool:
        return self.filter.active

    def set_state(self, state: object) -> None:
        del state
        self.store = self.ctx.engine.raw_store
        self.root = _build_tree(list(self.store))
        self._value_key = ""
        self.stats = self._stats()
        first = not self.rows
        if first and self.root.children:
            # Open on the first group's first key, so the value shows at once.
            name = min(self.root.children, key=_group_order)
            self.expanded.add(self.root.children[name].path)
        self._rebuild()
        if first:
            self.index = next((i for i, row in enumerate(self.rows) if row.key), 0)

    def _stats(self) -> list[Stat]:
        store = self.store
        sources = {key.split(":", 1)[0] for key in store if not key.startswith("_")}
        stats = [
            Stat("Keys", f"{len(store):,}", f"{len(sources)} sources"),
            Stat("Snapshot size", human_bytes(_size(store)), "as JSON"),
        ]
        run = store.get("_meta:last_run")
        if isinstance(run, dict):
            failures = run.get("failures", [])
            failed = len(failures) if isinstance(failures, list) else 0
            stats.append(
                Stat(
                    "Last run",
                    str(run.get("strategy", "-")),
                    f"{run.get('processed', 0)} of {run.get('total', 0)} processed · "
                    + f"{run.get('budget_skipped', 0)} deferred",
                )
            )
            stats.append(
                Stat(
                    "Failures",
                    str(failed),
                    "none" if not failed else "see _meta:last_run",
                    P.FOAM if not failed else P.GOLD,
                )
            )
        updated = store.get("_meta:last_updated")
        if isinstance(updated, str):
            stats.append(
                Stat("Updated", relative_time(updated), updated[:19].replace("T", " "))
            )
        return stats

    # Tree ------------------------------------------------------------------------

    def _rebuild(self) -> None:
        current = self.rows[self.index].path if self.rows else ""
        needle = self.filter.text.casefold()
        rows: list[TreeRow] = []

        def matches(node: _Node) -> bool:
            if needle in node.path.casefold():
                return True
            return any(matches(child) for child in node.children.values())

        def walk(node: _Node, depth: int) -> None:
            for name in sorted(node.children, key=_group_order):
                child = node.children[name]
                if needle and not matches(child):
                    continue
                group = bool(child.children)
                is_open = group and (bool(needle) or child.path in self.expanded)
                meta = (
                    str(child.leaves())
                    if group
                    else human_bytes(_size(self.store.get(child.key)))
                )
                rows.append(
                    TreeRow(child.path, name, depth, child.key, group, is_open, meta)
                )
                if is_open:
                    walk(child, depth + 1)

        walk(self.root, 0)
        self.rows = rows
        paths = [row.path for row in rows]
        self.index = paths.index(current) if current in paths else 0
        self.index = max(0, min(self.index, len(rows) - 1))

    @property
    def selected(self) -> TreeRow | None:
        return self.rows[self.index] if self.rows else None

    def _toggle(self, row: TreeRow, open_it: bool) -> None:
        if open_it:
            self.expanded.add(row.path)
        else:
            self.expanded.discard(row.path)
        self._rebuild()

    # Drawing ---------------------------------------------------------------------

    def render(self, cells: int, rows: int) -> list[str]:
        lines = [
            page_title(
                "Inspector",
                "The raw Echopoint snapshot, key by key",
                cells,
                self.filter.label(),
            ),
            "",
        ]
        lines += stat_strip(self.stats, cells)
        lines.append("")
        body = rows - len(lines)
        self._body = body
        if cells >= SIDE_FROM:
            right = cells - TREE - 3
            tree = self._tree(TREE, body, focused=self.pane == 0)
            value = self._value(right, body, focused=self.pane == 1)
            return lines + hjoin((tree, TREE), (value, right), gap=3)
        if self.pane == 1:
            # Narrow: the value replaces the tree until Esc.
            return lines + self._value(cells, body, focused=True, back=True)
        return lines + self._tree(cells, body, focused=True)

    def _tree(self, cells: int, rows: int, *, focused: bool) -> list[str]:
        if not self.rows:
            return [paint("Nothing matches", P.MUTED)]
        self.offset = min(self.offset, self.index)
        if self.index >= self.offset + rows:
            self.offset = self.index - rows + 1
        self.offset = max(0, min(self.offset, max(0, len(self.rows) - rows)))
        bar = scrollbar(len(self.rows), self.offset, rows)
        lines: list[str] = []
        for line_index, row in enumerate(self.rows[self.offset : self.offset + rows]):
            index = self.offset + line_index
            chosen = index == self.index
            chevron = ("▾ " if row.open else "▸ ") if row.group else "  "
            name_colour = P.TEXT if row.group else P.SUBTLE
            left = (
                "  " * row.depth
                + paint(chevron, P.MUTED)
                + paint(row.name, name_colour, bold=row.group)
            )
            meta = paint(row.meta, P.MUTED)
            room = cells - 3
            text = fit(left, room - width(meta) - 1) + " " + meta
            if chosen:
                mark = paint("▌", P.ACCENT if focused else P.MUTED)
                text = surface(mark + " " + text, cells - 1, P.SELECTED)
            else:
                text = fit("  " + text, cells - 1)
            lines.append(text + bar[line_index])
        return lines

    def _value(
        self, cells: int, rows: int, *, focused: bool, back: bool = False
    ) -> list[str]:
        row = self.selected
        key = row.key if row is not None else ""
        if key != self._value_key:
            self._value_key = key
            self.value_offset = 0
            value = self.store.get(key)
            self._value_lines = (
                json.dumps(value, indent=2, ensure_ascii=False).splitlines()
                if key
                else []
            )
        if not key:
            hint = "Pick a key to see its value" if row is None or row.group else ""
            return [paint(hint, P.MUTED)]
        value = self.store.get(key)
        parts = key.split(":")
        path = paint(
            " / ".join(parts[:-1]) + (" / " if len(parts) > 1 else ""), P.MUTED
        ) + paint(parts[-1], P.TEXT, bold=True)
        head = [
            (paint("Esc ", P.ACCENT) if back else "") + path,
            paint(f"{_describe(value)} · {human_bytes(_size(value))}", P.MUTED),
        ]
        body = max(1, rows - len(head))
        total = len(self._value_lines)
        self.value_offset = max(0, min(self.value_offset, max(0, total - body)))
        gutter = len(str(total))
        bar = scrollbar(total, self.value_offset, body)
        lines = head[:]
        shown = self._value_lines[self.value_offset : self.value_offset + body]
        for offset, text in enumerate(shown):
            number = self.value_offset + offset + 1
            line = paint(
                str(number).rjust(gutter), P.BORDER_STRONG if not focused else P.MUTED
            )
            lines.append(fit(line + "  " + highlight(text), cells - 1) + bar[offset])
        return lines

    # Keys ------------------------------------------------------------------------

    def key(self, key: str) -> bool:
        if self.filter.key(key):
            return True
        if key in ("tab", "backtab"):
            self.pane = 1 - self.pane
            return True
        if self.pane == 1:
            if key in ("esc", "h", "left", "backspace"):
                self.pane = 0
                return True
            move = list_moves(key, self._body - 2)
            if move is not None:
                self.value_offset = max(0, self.value_offset + move)
                return True
            return False
        move = list_moves(key, self._body)
        row = self.selected
        if move is not None:
            if self.rows:
                self.index = max(0, min(len(self.rows) - 1, self.index + move))
            return True
        if row is None:
            return False
        if key in ("enter", "l", "right", " "):
            if row.group and not row.open:
                self._toggle(row, True)
            elif row.key and key in ("enter", "l", "right"):
                self.pane = 1
            elif row.group and key in ("enter", " "):
                self._toggle(row, False)
            return True
        if key in ("h", "left"):
            if row.group and row.open:
                self._toggle(row, False)
            elif ":" in row.path:
                parent = row.path.rsplit(":", 1)[0]
                paths = [r.path for r in self.rows]
                if parent in paths:
                    self.index = paths.index(parent)
            return True
        return False
