"""The terminal app: chrome, page switching, keys and background work.

``frame`` builds the whole screen as lines from the current state and has no
I/O, so tests render it at any size. ``run`` owns the terminal: it draws
changed lines, reads keys, and drains the worker's events between frames.
"""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass

from ... import __version__
from ... import palette as P
from ...client import explain_error
from ...engine import EchopointEngine, ProgressCallback, ProgressUpdate
from ...formatting import relative_time
from .pages.activity import ActivityPage
from .pages.base import Context, Page
from .pages.constellation import ConstellationPage
from .pages.contributions import ContributionsPage
from .pages.inspector import InspectorPage
from .pages.languages import LanguagesPage
from .pages.projects import ProjectsPage
from .pages.sources import SourcesPage
from .pages.today import TodayPage
from .pages.welcome import Welcome
from .style import fit, paint, spread, surface, width
from .term import Terminal
from .widgets import keycap
from .worker import Done, Progress, Task

MIN_COLUMNS = 80
MIN_ROWS = 24
SIDEBAR = 20
SIDEBAR_FROM = 100
PAD = 2  # page margin left of the body; one cell on the right
# Relative times ("5m ago") go stale; redraw at least this often.
IDLE_REDRAW = 30.0

PAGE_TYPES: tuple[type[Page], ...] = (
    TodayPage,
    ProjectsPage,
    ActivityPage,
    LanguagesPage,
    ContributionsPage,
    SourcesPage,
    ConstellationPage,
    InspectorPage,
)
# Developer views sit apart at the bottom of the sidebar, as in the desktop app.
DEVELOPER = frozenset({"Inspector"})

GLOBAL_KEYS = (
    ("1–8", "switch page"),
    ("j k / ↓ ↑", "move or scroll"),
    ("PgDn PgUp  g G", "page down / up, top / bottom"),
    ("c", "check: download the snapshot if it changed"),
    ("r", "refresh: ask Echopoint to collect now, then sync"),
    ("?", "this help"),
    ("q", "quit"),
)

_STATE_COLOURS = {
    "ready": P.FOAM,
    "busy": P.ACCENT,
    "failed": P.LOVE,
    "idle": P.MUTED,
}


@dataclass(slots=True)
class Status:
    state: str = "ready"
    message: str = "Ready"
    progress: float | None = None


def _open_url(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001 > no browser is not an error worth a crash
        return False


class TuiApp:
    def __init__(
        self,
        engine: EchopointEngine,
        *,
        open_url: Callable[[str], bool] = _open_url,
    ) -> None:
        self.engine = engine
        self._open_url = open_url
        self.ctx = Context(engine, self.open_url)
        self.pages: list[Page] = [page_type(self.ctx) for page_type in PAGE_TYPES]
        self.current = 0
        self.status = Status()
        self.task: Task | None = None
        self.help_open = False
        self.running = True
        self.dirty = True
        self.welcome: Welcome | None = None
        self.sweep = 0
        self._stale = set(range(len(self.pages)))
        self._can_refresh = bool(engine.config.refresh_token)
        self._counts: dict[str, int] = {}
        self._source = ""
        if engine.has_data:
            self._load_state()
        else:
            self.welcome = Welcome(engine.config)
            self.status = Status("idle", "No snapshot yet")

    # Data --------------------------------------------------------------------------

    def _load_state(self) -> None:
        """The snapshot changed: pages rebuild when next shown."""
        state = self.engine.state
        P.rank_series(item.language for item in state.analytics.languages)
        self._stale = set(range(len(self.pages)))
        commits = sum(
            not commit.automated
            for project in state.projects
            for commit in project.commits
        )
        packages = len(state.npm) + len(state.crates) + len(state.pypi)
        self._counts = {
            "Projects": len(state.projects),
            "Activity": commits,
            "Languages": len(state.analytics.languages),
            "Sources": packages + len(state.docker),
        }
        parts = ["Echopoint"]
        if state.meta.remote_sources is not None:
            parts.append(f"{state.meta.remote_sources} sources")
        parts.append(
            "private snapshot" if self.engine.wants_private else "public snapshot"
        )
        if state.meta.last_updated:
            parts.append(f"updated {relative_time(state.meta.last_updated)}")
        self._source = " · ".join(parts)

    @property
    def page(self) -> Page:
        index = self.current
        if index in self._stale:
            self._stale.discard(index)
            self.pages[index].set_state(self.engine.state)
        return self.pages[index]

    # Background work -----------------------------------------------------------------

    def check(self) -> None:
        self._run(lambda progress: self.engine.sync(progress=progress), "Checking")

    def refresh(self) -> None:
        if not self._can_refresh:
            self._fail(
                "Refresh needs a token",
                "Set ECHOHUB_REFRESH_TOKEN to refresh. Check still works.",
            )
            return
        self._run(self.engine.refresh, "Refreshing")

    def _run(self, work: Callable[[ProgressCallback], object], verb: str) -> None:
        if self.task is not None:
            return
        config = self.engine.config
        self.task = Task(
            work,
            lambda exc: explain_error(
                exc, base_url=config.base_url, has_token=bool(config.refresh_token)
            ),
        )
        self.status = Status("busy", f"{verb}…")
        if self.welcome is not None:
            self.welcome.show_progress("Connecting to Echopoint", None)
        self.dirty = True
        self.task.start()

    def poll(self) -> None:
        """Apply what the worker reported since the last frame."""
        task = self.task
        if task is None:
            return
        for event in task.drain():
            self.dirty = True
            if isinstance(event, Progress):
                self._progress(event.update)
            elif isinstance(event, Done):
                self.task = None
                changed = getattr(event.result, "changed", True)
                self.status = Status("ready", "Updated" if changed else "Up to date")
                if changed or self.welcome is not None:
                    self.welcome = None
                    self._load_state()
            else:
                self.task = None
                self._fail(event.title, event.detail)

    def _progress(self, update: ProgressUpdate) -> None:
        self.status = Status("busy", update.message, update.progress)
        if self.welcome is not None:
            self.welcome.show_progress(update.message, update.progress)

    def _fail(self, title: str, detail: str) -> None:
        if self.engine.has_data and self.welcome is None:
            # Keep showing the last snapshot; say why it may be stale.
            message = f"{title} · showing the saved snapshot"
        else:
            message = title
        self.status = Status("failed", message)
        if self.welcome is not None:
            self.welcome.show_failure(title, detail)
        self.dirty = True

    def cancel_work(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.task = None

    def open_url(self, url: str) -> None:
        shown = url.split("://", 1)[-1]
        if self._open_url(url):
            self.status = Status(self.status.state, f"Opened {shown}")
        else:
            self.status = Status(self.status.state, f"No browser here · {url}")
        self.dirty = True

    # Keys ------------------------------------------------------------------------------

    def handle(self, key: str) -> None:
        self.dirty = True
        if self.help_open:
            if key in ("?", "esc", "q", "enter"):
                self.help_open = False
            return
        if self.welcome is None and self.page.typing:
            self.page.key(key)
            return
        if key in ("q", "ctrl-c"):
            self.running = False
        elif key == "?":
            self.help_open = True
        elif key == "c":
            self.check()
        elif key == "r":
            self.refresh()
        elif key.isdigit() and 1 <= int(key) <= len(self.pages):
            if self.welcome is None:
                self.current = int(key) - 1
        elif self.welcome is None:
            self.page.key(key)

    # Drawing -----------------------------------------------------------------------------

    def frame(self, cells: int, rows: int) -> list[str]:
        """The whole screen: exactly ``rows`` lines of ``cells`` columns."""
        if cells < MIN_COLUMNS or rows < MIN_ROWS:
            return self._too_small(cells, rows)
        sidebar = cells >= SIDEBAR_FROM and self.welcome is None
        body_cells = cells - (SIDEBAR if sidebar else 0)
        body_rows = rows - 3
        inner = body_cells - PAD - 1
        if self.help_open:
            body = self._help(inner, body_rows)
        elif self.welcome is not None:
            body = self.welcome.render(inner, body_rows)
        else:
            body = self.page.render(inner, body_rows)
        body = body[:body_rows] + [""] * max(0, body_rows - len(body))
        body = [surface(" " * PAD + line, body_cells) for line in body]
        if sidebar:
            nav = self._sidebar(body_rows)
            body = [left + right for left, right in zip(nav, body)]
        return [
            self._title(cells),
            self._progress_line(cells),
            *body,
            self._statusbar(cells),
        ]

    def _too_small(self, cells: int, rows: int) -> list[str]:
        message = paint(
            f"Make the terminal at least {MIN_COLUMNS} × {MIN_ROWS}", P.SUBTLE
        )
        now = paint(f"now {cells} × {rows} · q quits", P.MUTED)
        lines = [""] * rows
        middle = max(0, rows // 2 - 1)
        if rows:
            lines[middle] = fit(message, cells, "center")
        if middle + 1 < rows:
            lines[middle + 1] = fit(now, cells, "center")
        return [surface(line, cells) for line in lines]

    def _title(self, cells: int) -> str:
        name = "Welcome" if self.welcome is not None else self.pages[self.current].name
        if self.help_open:
            name = "Help"
        left = (
            " "
            + paint("◆", P.ACCENT)
            + " "
            + paint("Echohub", P.SUBTLE, bold=True)
            + paint(f" / {name}", P.MUTED)
        )
        right = ""
        if cells < SIDEBAR_FROM and self.welcome is None:
            right = "".join(
                paint(str(i + 1), P.ACCENT if i == self.current else P.MUTED) + " "
                for i in range(len(self.pages))
            )
        return surface(spread(left, right, cells), cells, P.PANEL)

    def _progress_line(self, cells: int) -> str:
        if self.status.state != "busy":
            return surface(paint("─" * cells, P.BORDER), cells)
        fraction = self.status.progress
        if fraction is None:
            self.sweep = (self.sweep + 2) % cells
            track = ["─"] * cells
            colours = [P.BORDER_STRONG] * cells
            for offset in range(min(16, cells)):
                index = (self.sweep + offset) % cells
                track[index] = "━"
                colours[index] = P.ACCENT
            line = "".join(paint(char, colour) for char, colour in zip(track, colours))
        else:
            filled = round(max(0.0, min(1.0, fraction)) * cells)
            line = paint("━" * filled, P.ACCENT) + paint(
                "─" * (cells - filled), P.BORDER_STRONG
            )
        return surface(line, cells)

    def _sidebar(self, rows: int) -> list[str]:
        def item(index: int, page: Page) -> str:
            chosen = index == self.current
            count = self._counts.get(page.name)
            number = paint(str(index + 1), P.ACCENT if chosen else P.MUTED)
            name = paint(page.name, P.TEXT if chosen else P.SUBTLE, bold=chosen)
            meta = paint(str(count), P.MUTED) if count else ""
            mark = paint("▌", P.ACCENT) if chosen else " "
            text = spread(mark + " " + number + "  " + name, meta + " ", SIDEBAR - 1)
            return surface(text, SIDEBAR - 1, P.SELECTED if chosen else P.PANEL)

        top = [surface(" " + paint("Views", P.MUTED), SIDEBAR - 1, P.PANEL)]
        bottom: list[str] = []
        for index, page in enumerate(self.pages):
            if page.name in DEVELOPER:
                bottom += [
                    surface(" " + paint("Developer", P.MUTED), SIDEBAR - 1, P.PANEL),
                    item(index, page),
                ]
            else:
                top.append(item(index, page))
        filler = [surface("", SIDEBAR - 1, P.PANEL)] * max(
            0, rows - len(top) - len(bottom) - 1
        )
        column = (top + filler + bottom)[: rows - 1] + [
            surface("", SIDEBAR - 1, P.PANEL)
        ]
        edge = surface(paint("│", P.BORDER), 1, P.PANEL)
        return [line + edge for line in column[:rows]]

    def _statusbar(self, cells: int) -> str:
        status = self.status
        mark = paint("■", _STATE_COLOURS.get(status.state, P.MUTED))
        divider = paint(" │ ", P.BORDER_STRONG)
        message = paint(status.message, P.SUBTLE)
        source = paint(self._source, P.MUTED) if self._source else ""
        keys = [("1–8", "views"), ("r", "refresh"), ("c", "check"), ("?", "help")]
        version = paint(f"Echohub {__version__}", P.MUTED)

        def caps(pairs: list[tuple[str, str]]) -> str:
            return "  ".join(
                keycap(key) + " " + paint(action, P.MUTED) for key, action in pairs
            )

        lefts = [
            " " + mark + " " + message + (divider + source if source else ""),
            " " + mark + " " + message,
        ]
        rights = [
            caps(keys) + divider + version + " ",
            caps(keys) + " ",
            caps(keys[-1:]) + " ",
            "",
        ]
        for left in lefts:
            for right in rights:
                if width(left) + 2 + width(right) <= cells:
                    return surface(spread(left, right, cells), cells, P.PANEL)
        return surface(lefts[-1], cells, P.PANEL)

    def _help(self, cells: int, rows: int) -> list[str]:
        page = self.pages[self.current]
        inner = min(72, cells - 4)
        lines = [paint("Keys", P.TEXT, bold=True), ""]
        lines.append(paint("Everywhere", P.SUBTLE, bold=True))
        for keys, does in GLOBAL_KEYS:
            lines.append(fit(paint(keys, P.ACCENT), 18) + paint(does, P.SUBTLE))
        if page.keys and self.welcome is None:
            lines += ["", paint(page.name, P.SUBTLE, bold=True)]
            for keys, does in page.keys:
                lines.append(fit(paint(keys, P.ACCENT), 18) + paint(does, P.SUBTLE))
        lines += ["", paint("? or Esc closes this", P.MUTED)]
        border = P.BORDER_STRONG
        box = [paint("┌" + "─" * (inner + 2) + "┐", border)]
        box += [
            paint("│ ", border) + fit(line, inner) + paint(" │", border)
            for line in lines
        ]
        box.append(paint("└" + "─" * (inner + 2) + "┘", border))
        top = max(0, (rows - len(box)) // 3)
        left = " " * max(0, (cells - inner - 4) // 2)
        return [""] * top + [left + line for line in box]

    # Loop ------------------------------------------------------------------------------

    def run(self, *, auto_check: bool = False) -> None:
        with Terminal() as term:
            last_draw = 0.0
            size = (0, 0)
            if auto_check:
                self.check()
            while self.running:
                self.poll()
                now = time.monotonic()
                current = term.size()
                busy = self.status.state == "busy"
                if current != size:
                    size = current
                    self.dirty = True
                if (
                    self.dirty
                    or (busy and now - last_draw >= 0.08)
                    or now - last_draw >= IDLE_REDRAW
                ):
                    term.draw(self.frame(*size), size)
                    self.dirty = False
                    last_draw = now
                for key in term.read_keys(0.05 if busy else 0.25):
                    self.handle(key)
                    if key == "o":
                        # A browser launcher may have written to the terminal.
                        term.redraw_all()
        # Quit mid-sync: stop at the next step; the worker is a daemon, so a
        # request still in flight doesn't hold the process open.
        self.cancel_work()


def run_tui(engine: EchopointEngine, *, auto_check: bool = False) -> None:
    try:
        TuiApp(engine).run(auto_check=auto_check)
    except KeyboardInterrupt:
        pass
