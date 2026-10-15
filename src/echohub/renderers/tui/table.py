"""The list view every TUI page uses: sort, filter, select, scroll.

Columns carry a ``drop`` order: when the terminal is too narrow, the column
with the highest ``drop`` goes first, so the important ones stay instead of
the table scrolling sideways. Cell kinds match the desktop table's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from ... import palette as P
from .style import clean, fit, paint, surface, width
from .widgets import DIFF_WIDTH, age_tone, diff_bar, hbar, pill, private_mark, scrollbar

R = TypeVar("R")
SortKey = str | int | float | bool
GAP = 2
_BAR = 6
_RIGHT = frozenset({"number", "bar", "age"})


@dataclass(frozen=True, slots=True)
class Column(Generic[R]):
    title: str
    text: Callable[[R], str]
    # Cells for fixed columns; the minimum for a stretch column.
    width: int = 10
    stretch: bool = False
    kind: str = "plain"
    # 0 never drops; otherwise higher numbers drop first on narrow screens.
    drop: int = 0
    sort: Callable[[R], SortKey] | None = None
    # Sorting starts descending (newest, largest) unless this is False.
    descending: bool = True
    tone: Callable[[R], str | None] | None = None
    flag: Callable[[R], bool] | None = None
    # "bar": the magnitude; "age": the ISO timestamp; "diff": (added, removed).
    value: Callable[[R], float] | None = None
    stamp: Callable[[R], str] | None = None
    pair: Callable[[R], tuple[int, int]] | None = None

    def cells(self) -> int:
        if self.kind == "diff":
            return DIFF_WIDTH
        extra = 2 if self.flag is not None else 0
        if self.kind == "bar":
            extra += _BAR + 1
        if self.kind == "swatch":
            extra += 2
        # Room for the title and the sort arrow, so headers never clip.
        return max(self.width + extra, width(self.title) + 2)


class Table(Generic[R]):
    def __init__(
        self,
        columns: Sequence[Column[R]],
        rows: Sequence[R],
        *,
        sort: str = "",
        search: Callable[[R], str] | None = None,
        empty: str = "Nothing matches",
    ) -> None:
        self.columns = list(columns)
        self.rows = list(rows)
        self.search = search
        self.empty = empty
        self.filter = ""
        self.predicate: Callable[[R], bool] | None = None
        sortable = [column for column in self.columns if column.sort is not None]
        chosen = next((c for c in sortable if c.title == sort), None)
        self.sort_column = chosen or (sortable[0] if sortable else None)
        self.descending = self.sort_column.descending if self.sort_column else False
        self.index = 0
        self.offset = 0
        self.view: list[R] = []
        self._peaks: dict[str, float] = {}
        self._refresh()

    # Data ----------------------------------------------------------------------

    def set_rows(self, rows: Sequence[R]) -> None:
        """New data; keeps the selected row when it is still there."""
        current = self.selected
        self.rows = list(rows)
        self._refresh(current)

    def set_filter(self, text: str) -> None:
        current = self.selected
        self.filter = text
        self._refresh(current)

    def set_predicate(self, predicate: Callable[[R], bool] | None) -> None:
        current = self.selected
        self.predicate = predicate
        self._refresh(current)

    def cycle_sort(self, reverse: bool = False) -> None:
        """``s`` moves to the next sortable column; ``S`` flips the order."""
        if self.sort_column is None:
            return
        if reverse:
            self.descending = not self.descending
        else:
            sortable = [c for c in self.columns if c.sort is not None]
            index = sortable.index(self.sort_column)
            self.sort_column = sortable[(index + 1) % len(sortable)]
            self.descending = self.sort_column.descending
        self._refresh(self.selected)

    def _refresh(self, keep: R | None = None) -> None:
        rows = self.rows
        if self.predicate is not None:
            rows = [row for row in rows if self.predicate(row)]
        if self.filter and self.search is not None:
            needle = self.filter.casefold()
            rows = [row for row in rows if needle in self.search(row).casefold()]
        column = self.sort_column
        if column is not None and column.sort is not None:
            key = column.sort
            rows = sorted(rows, key=key, reverse=self.descending)
        self.view = rows
        self._peaks = {
            c.title: max((abs(c.value(r)) for r in rows), default=0.0)
            if c.value is not None
            else max((max(c.pair(r)) for r in rows), default=0)
            if c.pair is not None
            else 0.0
            for c in self.columns
        }
        if keep is not None and keep in rows:
            self.index = rows.index(keep)
        self.index = max(0, min(self.index, len(rows) - 1))

    # Selection -------------------------------------------------------------------

    @property
    def selected(self) -> R | None:
        return self.view[self.index] if self.view else None

    def move(self, delta: int) -> None:
        if self.view:
            self.index = max(0, min(len(self.view) - 1, self.index + delta))

    def home(self) -> None:
        self.index = 0

    def end(self) -> None:
        self.index = max(0, len(self.view) - 1)

    # Drawing -------------------------------------------------------------------

    def layout(self, cells: int) -> list[tuple[Column[R], int]]:
        """Visible columns and their widths for ``cells`` columns of room."""
        room = cells - 2  # selection bar and a space
        shown = list(self.columns)
        while True:
            fixed = sum(c.cells() for c in shown if not c.stretch)
            stretch = [c for c in shown if c.stretch]
            need = fixed + sum(c.cells() for c in stretch) + GAP * (len(shown) - 1)
            droppable = [c for c in shown if c.drop]
            if need <= room or not droppable:
                break
            shown.remove(max(droppable, key=lambda c: c.drop))
        spare = max(0, room - need)
        widths: list[tuple[Column[R], int]] = []
        stretch_count = sum(1 for c in shown if c.stretch)
        for column in shown:
            size = column.cells()
            if column.stretch and stretch_count:
                share = spare // stretch_count
                size += share
            widths.append((column, size))
        return widths

    def render(
        self, cells: int, rows: int, *, focused: bool = True, select: bool = True
    ) -> list[str]:
        """Header plus as many rows as fit; keeps the selection in view."""
        if rows <= 0:
            return []
        layout = self.layout(cells - 1)
        lines = [self._header(layout, cells - 1) + " "]
        body = rows - 1
        if not self.view:
            message = self.empty if not self.filter else "Nothing matches"
            lines.append(fit("  " + paint(message, P.MUTED), cells))
            return lines
        self.offset = min(self.offset, self.index)
        if self.index >= self.offset + body:
            self.offset = self.index - body + 1
        self.offset = max(0, min(self.offset, max(0, len(self.view) - body)))
        bar = scrollbar(len(self.view), self.offset, body)
        for line_index, row in enumerate(self.view[self.offset : self.offset + body]):
            index = self.offset + line_index
            chosen = select and index == self.index
            text = self._row(row, layout)
            if chosen:
                mark = paint("▌", P.ACCENT if focused else P.MUTED)
                text = surface(mark + " " + text, cells - 1, P.SELECTED)
            else:
                text = fit("  " + text, cells - 1)
            lines.append(text + bar[line_index])
        return lines

    def _header(self, layout: list[tuple[Column[R], int]], cells: int) -> str:
        parts: list[str] = []
        for column, size in layout:
            title = column.title
            colour = P.MUTED
            if column is self.sort_column:
                title += " ↓" if self.descending else " ↑"
                colour = P.TEXT
            align = "right" if column.kind in _RIGHT else "left"
            # Flagged columns start their text after the private mark.
            lead = "  " if column.flag is not None else ""
            parts.append(fit(lead + paint(title, colour), size, align))
        return fit("  " + (" " * GAP).join(parts), cells)

    def _row(self, row: R, layout: list[tuple[Column[R], int]]) -> str:
        return (" " * GAP).join(
            self._cell(column, row, size) for column, size in layout
        )

    def _cell(self, column: Column[R], row: R, size: int) -> str:
        text = clean(column.text(row))
        tone = column.tone(row) if column.tone is not None else None
        kind = column.kind
        if kind == "diff" and column.pair is not None:
            added, removed = column.pair(row)
            peak = int(self._peaks.get(column.title, 0))
            return fit(diff_bar(added, removed, peak), size)
        prefix = ""
        if column.flag is not None:
            prefix = private_mark(column.flag(row))
            size -= 2
        if kind == "strong":
            body = fit(paint(text, tone or P.TEXT), size)
        elif kind == "muted":
            body = fit(paint(text, tone or P.SUBTLE), size)
        elif kind == "code":
            body = fit(paint(text, tone or P.MUTED), size)
        elif kind == "number":
            body = fit(paint(text, tone or P.SUBTLE), size, "right")
        elif kind == "age":
            stamp = column.stamp(row) if column.stamp is not None else ""
            body = fit(paint(text, tone or age_tone(stamp)), size, "right")
        elif kind == "bar":
            value = abs(column.value(row)) if column.value is not None else 0.0
            peak = self._peaks.get(column.title, 0.0)
            share = (value / peak) ** 0.5 if peak > 0 else 0.0
            number = fit(paint(text, P.SUBTLE), size - _BAR - 1, "right")
            track = hbar(share, _BAR, tone or P.ACCENT) if value > 0 else " " * _BAR
            body = number + " " + track
        elif kind == "pill":
            body = fit(pill(text, tone or P.SUBTLE), size)
        elif kind == "swatch":
            body = fit(paint("■", tone or P.MUTED) + " " + paint(text, P.TEXT), size)
        elif kind == "dot":
            body = fit(paint("■", tone or P.MUTED), size)
        else:
            body = fit(paint(text, tone or P.SUBTLE), size)
        return prefix + body

    def status(self) -> str:
        """ "3 of 41" and the filter, for a page's meta line."""
        total = len(self.rows)
        shown = len(self.view)
        text = f"{self.index + 1 if self.view else 0} of {shown}"
        if shown != total:
            text += f" (of {total})"
        return text
