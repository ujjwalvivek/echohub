"""What every TUI page shares: the page contract, scrolling and filtering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from .... import palette as P
from ....engine import EchopointEngine
from ....models import DashboardState
from ..style import fit, paint
from ..widgets import scrollbar

PAGE_STEP = 10  # rows PgUp/PgDn move when a page has no better measure


def _today() -> date:
    return datetime.now().astimezone().date()


@dataclass(slots=True)
class Context:
    engine: EchopointEngine
    open_url: Callable[[str], None]
    today: Callable[[], date] = _today


class Page:
    """One view. ``render`` returns at most ``rows`` styled lines, each at
    most ``cells`` wide; the app pads them onto the screen."""

    name = ""
    # Page-specific keys for the ? help: (keys, what they do).
    keys: tuple[tuple[str, str], ...] = ()

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def set_state(self, state: DashboardState) -> None:
        """The snapshot changed; rebuild what the page derives from it."""

    def render(self, cells: int, rows: int) -> list[str]:
        raise NotImplementedError

    def key(self, key: str) -> bool:
        """Handle a key; False passes it on to the app."""
        return False

    @property
    def typing(self) -> bool:
        """True while a text field has the keys (the app then sends all)."""
        return False


class FilterField:
    """``/`` to type a filter, Enter to keep it, Esc to clear it."""

    def __init__(self, on_change: Callable[[str], None]) -> None:
        self.text = ""
        self.active = False
        self._on_change = on_change

    def key(self, key: str) -> bool:
        if not self.active:
            if key == "/":
                self.active = True
                return True
            if key == "esc" and self.text:
                self._set("")
                return True
            return False
        if key == "enter":
            self.active = False
        elif key == "esc":
            self.active = False
            self._set("")
        elif key == "backspace":
            self._set(self.text[:-1])
        elif len(key) == 1:
            self._set(self.text + key)
        elif key in ("up", "down", "pgup", "pgdn"):
            # Let the list move while the filter is open.
            self.active = False
            return False
        return True

    def _set(self, text: str) -> None:
        self.text = text
        self._on_change(text)

    def label(self) -> str:
        """The filter as shown at the right of a page title, or a hint."""
        if self.active:
            return (
                paint("/ ", P.ACCENT) + paint(self.text, P.TEXT) + paint("▏", P.ACCENT)
            )
        if self.text:
            return paint("/ ", P.MUTED) + paint(self.text, P.SUBTLE)
        return paint("/ filter", P.MUTED)


class ScrollPage(Page):
    """A page taller than the screen: ``content`` once, then j/k scroll it."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.offset = 0
        self._rows = 0

    def content(self, cells: int, rows: int) -> list[str]:
        """All of the page's lines at this width; ``rows`` is the visible
        height, for pages that stretch a chart to fill it."""
        raise NotImplementedError

    def render(self, cells: int, rows: int) -> list[str]:
        lines = self.content(cells - 1, rows)
        self._rows = rows
        self.offset = max(0, min(self.offset, max(0, len(lines) - rows)))
        bar = scrollbar(len(lines), self.offset, rows)
        shown = lines[self.offset : self.offset + rows]
        return [fit(line, cells - 1) + bar[index] for index, line in enumerate(shown)]

    def key(self, key: str) -> bool:
        step = max(1, self._rows - 2) if self._rows else PAGE_STEP
        moves = {
            "j": 1,
            "down": 1,
            "k": -1,
            "up": -1,
            "pgdn": step,
            " ": step,
            "pgup": -step,
            "g": -(10**9),
            "home": -(10**9),
            "G": 10**9,
            "end": 10**9,
        }
        if key not in moves:
            return False
        self.offset = max(0, self.offset + moves[key])
        return True


def list_moves(key: str, rows: int) -> int | None:
    """How far j/k/PgDn/g/G… move a selection, or None for other keys."""
    step = max(1, rows - 2)
    return {
        "j": 1,
        "down": 1,
        "k": -1,
        "up": -1,
        "pgdn": step,
        "pgup": -step,
        "g": -(10**9),
        "home": -(10**9),
        "G": 10**9,
        "end": 10**9,
    }.get(key)
