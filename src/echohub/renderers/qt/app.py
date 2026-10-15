"""Qt desktop renderer (Rose Pine, custom chrome)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...client import explain_error
from ...engine import EchopointEngine, ProgressUpdate
from ...formatting import relative_time
from ...models import DashboardState
from ...today import build_today
from . import theme as T
from .chrome import (
    TitleBar,
    check_button,
    handle_native_event,
    install_chrome,
    refresh_button,
    sync_chrome,
)
from .nav import NavButton, NavHeader
from .pages.activity import ActivityPage
from .pages.constellation import ConstellationPage
from .pages.contributions import ContributionsPage
from .pages.inspector import InspectorPage
from .pages.languages import LanguagesPage
from .pages.projects import ProjectsPage
from .pages.sources import SourcesPage
from .pages.today import TodayPage
from .pages.welcome import WelcomePage
from .tooltip import install_tooltips
from .widgets import label


@dataclass(frozen=True, slots=True)
class PageSpec:
    name: str
    build: Callable[[EchopointEngine, DashboardState, T.Fonts], QWidget]
    # Developer views sit apart at the bottom of the sidebar.
    developer: bool = False


PAGE_HELP = {
    "Today": "Streaks, this week, recent commits, releases and packages",
    "Projects": "Every tracked repo, sortable, with details on the right",
    "Activity": "The latest commits across all repos",
    "Languages": "What your code is written in, overall and per repo",
    "Contributions": "Your GitHub contribution calendar, year by year",
    "Sources": "Package registries, status checks and release coverage",
    "Constellation": "Repos linked to the languages they use",
    "Inspector": "The raw Echopoint snapshot, key by key",
}

PAGES: tuple[PageSpec, ...] = (
    PageSpec("Today", lambda _e, state, fonts: TodayPage(build_today(state), fonts)),
    PageSpec("Projects", lambda _e, state, fonts: ProjectsPage(state, fonts)),
    PageSpec("Activity", lambda _e, state, fonts: ActivityPage(state, fonts)),
    PageSpec("Languages", lambda _e, state, fonts: LanguagesPage(state, fonts)),
    PageSpec("Contributions", lambda _e, state, fonts: ContributionsPage(state, fonts)),
    PageSpec("Sources", lambda _e, state, fonts: SourcesPage(state, fonts)),
    PageSpec("Constellation", lambda _e, state, fonts: ConstellationPage(state, fonts)),
    PageSpec(
        "Inspector",
        lambda engine, _state, fonts: InspectorPage(engine.raw_store, fonts),
        developer=True,
    ),
)
PAGE_NAMES = tuple(spec.name for spec in PAGES)


class _TaskSignals(QObject):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(str)


class _EngineTask(QRunnable):
    """Runs a blocking engine call off the UI thread.

    Signals are delivered to the window on the UI thread, so widgets are never
    touched from the worker.
    """

    def __init__(
        self,
        work: Callable[[Callable[[ProgressUpdate], None]], object],
        explain: Callable[[BaseException], tuple[str, str]],
    ) -> None:
        super().__init__()
        self.signals = _TaskSignals()
        self._work = work
        self._explain = explain

    def run(self) -> None:
        try:
            result = self._work(self.signals.progress.emit)
        except Exception as exc:  # noqa: BLE001 > background task boundary
            title, detail = self._explain(exc)
            self.signals.failed.emit(f"{title}\n{detail}")
        else:
            self.signals.done.emit(result)


class MainWindow(QWidget):
    def __init__(
        self, engine: EchopointEngine, fonts: T.Fonts, *, auto_check: bool = False
    ) -> None:
        super().__init__()
        # First: Qt sends change/native events while the window is still being
        # built, and their handlers need the title bar.
        icon = _icon()
        mark = resources.files("echohub").joinpath("assets/echohub.svg")
        self.title_bar = TitleBar(self, "Echohub", icon, mark.read_bytes())
        self.setWindowIcon(icon)
        self.engine = engine
        self.fonts = fonts
        self._task: _EngineTask | None = None
        self._auto_check = auto_check
        self._can_refresh = bool(engine.config.refresh_token)
        self.welcome: WelcomePage | None = None
        self._built: dict[str, QWidget] = {}
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: dict[str, NavButton] = {}
        self.current_page = PAGES[0].name
        self.status = QLabel("Ready")
        self.state_mark = StateMark()
        self.source = QLabel("")
        self.check_button = check_button(
            "Check  ·  C\nDownload the snapshot if it changed"
        )
        self.refresh_button = refresh_button(
            "Refresh  ·  R\nAsk Echopoint to collect now, then sync"
            if self._can_refresh
            else "Refresh  ·  R\nNeeds ECHOHUB_REFRESH_TOKEN. Check still downloads "
            + "the public snapshot."
        )
        self.refresh_button.setEnabled(self._can_refresh)
        self.check_button.clicked.connect(self.check)
        self.refresh_button.clicked.connect(self.refresh)
        self.title_bar.add_action(self.check_button)
        self.title_bar.add_action(self.refresh_button)
        self.setWindowTitle("Echohub")
        # One fixed size: no maximise, no edge resizing, and snapping to a
        # screen edge moves the window without stretching it.
        self.setFixedSize(window_size())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.title_bar)
        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        outer.addLayout(root, 1)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        main.addWidget(self.progress)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        main.addWidget(self._statusbar())
        root.addLayout(main, 1)

        if engine.has_data:
            self._render()
        else:
            self._show_welcome()
        for keys, action in (
            ("R", self.refresh),
            ("C", self.check),
            ("Ctrl+R", self.refresh),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(action)
        for index, spec in enumerate(PAGES, start=1):
            QShortcut(QKeySequence(str(index)), self).activated.connect(
                lambda name=spec.name: self.show_page(name)
            )
        install_chrome(self)

    # Window chrome -------------------------------------------------------------

    def nativeEvent(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, eventType: QByteArray | bytes, message: int
    ) -> tuple[bool, int]:
        raw = eventType.data() if isinstance(eventType, QByteArray) else eventType
        handled = handle_native_event(self, self.title_bar, bytes(raw), int(message))
        if handled is not None:
            return handled
        return cast(tuple[bool, int], super().nativeEvent(eventType, message))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._auto_check:
            self._auto_check = False
            # After the first paint, so the window is up before any network.
            QTimer.singleShot(200, self.check)

    def changeEvent(self, event: QEvent) -> None:
        sync_chrome(event, self.title_bar)
        super().changeEvent(event)

    # Layout ------------------------------------------------------------------

    def _sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(184)
        column = QVBoxLayout(bar)
        column.setContentsMargins(0, 4, 0, 8)
        column.setSpacing(1)
        column.addWidget(NavHeader("Views", self.fonts))
        for index, spec in enumerate(PAGES, start=1):
            if spec.developer:
                column.addStretch(1)
                column.addWidget(NavHeader("Developer", self.fonts))
            item = NavButton(spec.name, self.fonts)
            item.setToolTip(f"{spec.name}  ·  {index}\n{PAGE_HELP.get(spec.name, '')}")
            item.clicked.connect(
                lambda _checked=False, name=spec.name: self.show_page(name)
            )
            self.nav.addButton(item)
            self.nav_buttons[spec.name] = item
            column.addWidget(item)
        if not any(spec.developer for spec in PAGES):
            column.addStretch(1)
        return bar

    def _statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Statusbar")
        bar.setFixedHeight(26)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)
        row.addWidget(self.state_mark)
        row.addWidget(self.status)
        row.addWidget(_status_divider())
        row.addWidget(self.source)
        row.addStretch(1)
        for keys, action in (("1–8", "views"), ("R", "refresh"), ("C", "check")):
            cap = label(keys, "Key")
            cap.setFixedHeight(16)
            cap.setToolTip(f"{action.capitalize()}  ·  {keys}\n{_KEY_HELP[action]}")
            row.addWidget(cap, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(label(action, "KeyHint"))
            row.addSpacing(4)
        row.addWidget(_status_divider())
        row.addWidget(label(f"Echohub {__version__}", "StatusMono"))
        return bar

    # Pages -------------------------------------------------------------------

    def show_page(self, name: str) -> None:
        """Switch views, building a page the first time it is opened."""
        if not self.engine.has_data:
            return
        spec = next(spec for spec in PAGES if spec.name == name)
        widget = self._built.get(name)
        if widget is None:
            widget = spec.build(self.engine, self.engine.state, self.fonts)
            self._built[name] = widget
            _ = self.pages.addWidget(widget)
        self.pages.setCurrentWidget(widget)
        self.current_page = name
        self.nav_buttons[name].setChecked(True)
        self.title_bar.set_page(name)

    def page(self, name: str) -> QWidget:
        self.show_page(name)
        return self._built[name]

    def _show_welcome(self) -> None:
        self.welcome = WelcomePage(self.engine.config, self.fonts)
        self.welcome.retry.connect(self.check)
        _ = self.pages.addWidget(self.welcome)
        self.pages.setCurrentWidget(self.welcome)
        for item in self.nav_buttons.values():
            item.setEnabled(False)
        self.title_bar.set_page("Welcome")
        self.source.setText(self.engine.config.base_url)
        self.status.setText("No snapshot yet")
        self.state_mark.set_state("idle")

    def _leave_welcome(self) -> None:
        if self.welcome is None:
            return
        self.pages.removeWidget(self.welcome)
        self.welcome.deleteLater()
        self.welcome = None
        for item in self.nav_buttons.values():
            item.setEnabled(True)

    def _render(self) -> None:
        """Drop every built page (the data changed) and rebuild the open one."""
        self._leave_welcome()
        for widget in self._built.values():
            self.pages.removeWidget(widget)
            widget.deleteLater()
        self._built.clear()
        state = self.engine.state
        T.rank_series(item.language for item in state.analytics.languages)
        self.show_page(self.current_page)
        commits = sum(
            not commit.automated
            for project in state.projects
            for commit in project.commits
        )
        packages = len(state.npm) + len(state.crates) + len(state.pypi)
        counts = {
            "Projects": len(state.projects),
            "Activity": commits,
            "Languages": len(state.analytics.languages),
            "Sources": packages + len(state.docker),
        }
        for name, item in self.nav_buttons.items():
            count = counts.get(name)
            item.set_count(str(count) if count else "")
        sources = state.meta.remote_sources
        parts = ["Echopoint"]
        if sources is not None:
            parts.append(f"{sources} sources")
        parts.append(
            "private snapshot" if self.engine.wants_private else "public snapshot"
        )
        if state.meta.last_updated:
            parts.append(f"updated {relative_time(state.meta.last_updated)}")
        self.source.setText(" · ".join(parts))
        self.source.setToolTip(
            "Snapshot\n"
            + (
                f"Last updated {state.meta.last_updated.replace('T', ' ')[:19]}"
                if state.meta.last_updated
                else "Never updated"
            )
            + (
                "\nPrivate repos included (token set)"
                if self.engine.wants_private
                else "\nPublic repos only"
            )
        )

    # Background work ---------------------------------------------------------

    def refresh(self) -> None:
        if not self._can_refresh:
            self._show_failure(
                "Refresh needs a token",
                "Set ECHOHUB_REFRESH_TOKEN to refresh. Check still works.",
            )
            return
        self._run(lambda progress: self.engine.refresh(progress), "Refreshing")

    def check(self) -> None:
        self._run(lambda progress: self.engine.sync(progress=progress), "Checking")

    def _run(
        self, work: Callable[[Callable[[ProgressUpdate], None]], object], verb: str
    ) -> None:
        if self._task is not None:
            return
        config = self.engine.config
        task = _EngineTask(
            work,
            lambda exc: explain_error(
                exc, base_url=config.base_url, has_token=bool(config.refresh_token)
            ),
        )
        task.signals.progress.connect(self._on_progress)
        task.signals.done.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        self._set_busy(True)
        self.status.setText(f"{verb}…")
        self.status.setToolTip("")
        self.state_mark.set_state("busy")
        if self.welcome is not None:
            self.welcome.show_progress("Connecting to Echopoint", None)
        QThreadPool.globalInstance().start(task)

    def _set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy and self._can_refresh)
        self.refresh_button.set_spinning(busy)
        self.check_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)

    def _on_progress(self, update: object) -> None:
        if not isinstance(update, ProgressUpdate):
            return
        self.status.setText(update.message)
        if self.welcome is not None:
            self.welcome.show_progress(update.message, update.progress)
        if update.progress is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(update.progress * 100))

    def _on_done(self, result: object) -> None:
        self._task = None
        self._set_busy(False)
        changed = getattr(result, "changed", True)
        self.status.setText("Updated" if changed else "Up to date")
        self.status.setToolTip("")
        self.state_mark.set_state("ready")
        # Rebuilding resets scroll and selection, so only do it for new data.
        if changed or self.welcome is not None or not self._built:
            self._render()

    def _on_failed(self, message: str) -> None:
        self._task = None
        self._set_busy(False)
        title, _, detail = message.partition("\n")
        self._show_failure(title, detail)

    def _show_failure(self, title: str, detail: str) -> None:
        if self.engine.has_data:
            # Keep showing the last snapshot; say why it may be stale.
            self.status.setText(f"{title} · showing the saved snapshot")
        else:
            self.status.setText(title)
        self.status.setToolTip(f"{title}\n{detail}")
        self.state_mark.set_state("failed")
        if self.welcome is not None:
            self.welcome.show_failure(title, detail)


WINDOW_SIZE = QSize(1600, 900)  # 16:9
_SCREEN_MARGIN = 48


def window_size() -> QSize:
    """1600 x 900, shrunk at 16:9 when the screen is too small to fit it."""
    room = QGuiApplication.primaryScreen().availableGeometry().size()
    fits = min(
        WINDOW_SIZE.width(),
        room.width() - _SCREEN_MARGIN,
        (room.height() - _SCREEN_MARGIN) * 16 // 9,
    )
    width = fits - fits % 16  # a multiple of 16 keeps 16:9 exact
    return QSize(width, width * 9 // 16)


_KEY_HELP = {
    "views": "Switch views with the number keys",
    "refresh": "Ask Echopoint to collect now, then sync",
    "check": "Download the snapshot if it changed",
}
_STATE_HELP = {
    "ready": "Ready\nThe last sync finished without errors",
    "busy": "Working\nSyncing with Echopoint",
    "failed": "Failed\nThe last sync did not finish; see the message",
    "idle": "No snapshot yet\nPress Check (C) to download one",
}
_STATE_COLOURS = {
    "ready": T.FOAM,
    "busy": T.ACCENT,
    "failed": T.LOVE,
    "idle": T.MUTED,
}


class StateMark(QWidget):
    """The status bar's square: foam when idle, accent while working, love on failure."""

    def __init__(self) -> None:
        super().__init__()
        self.state = "ready"
        self.setToolTip(_STATE_HELP["ready"])
        self.setFixedSize(6, 6)

    def set_state(self, state: str) -> None:
        self.state = state
        self.setToolTip(_STATE_HELP.get(state, state))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_STATE_COLOURS.get(self.state, T.MUTED)))


def _status_divider() -> QFrame:
    line = QFrame()
    line.setObjectName("StatusDivider")
    line.setFixedSize(1, 12)
    return line


def _icon() -> QIcon:
    # The .ico carries 16-256 px frames, so the taskbar, Alt+Tab and the
    # title bar each get a sharp size; the PNG is the large fallback.
    assets = resources.files("echohub").joinpath("assets")
    icon = QIcon(str(assets.joinpath("echohub.ico")))
    icon.addFile(str(assets.joinpath("echohub.png")))
    return icon


def _set_app_id() -> None:
    """Give Windows our own taskbar identity, so it shows Echohub's icon.

    Without it the window is grouped under python.exe and takes its icon.
    """
    if sys.platform == "win32":
        import ctypes

        _ = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ujjwalvivek.echohub"
        )


_ready: tuple[QApplication, T.Fonts] | None = None


def create_app() -> tuple[QApplication, T.Fonts]:
    """Set up the application once; later calls return the same pair.

    Re-applying the app stylesheet re-polishes every live widget, so doing it
    again (tests build many windows) is both wasted work and a crash risk.
    """
    global _ready
    if _ready is not None and QApplication.instance() is _ready[0]:
        return _ready
    existing = QApplication.instance()
    _set_app_id()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName("Echohub")
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Dark)
    fonts = T.resolve_fonts()
    app.setStyleSheet(T.stylesheet(fonts))
    install_tooltips(app, fonts)
    app.setWindowIcon(_icon())
    _ready = (app, fonts)
    return _ready


def run_qt(engine: EchopointEngine, *, auto_check: bool = False) -> None:
    app, fonts = create_app()
    window = MainWindow(engine, fonts, auto_check=auto_check)
    window.show()
    # Release smoke tests launch the packaged app headless and need it to
    # prove it starts, then leave on its own.
    exit_after = os.environ.get("ECHOHUB_EXIT_AFTER_MS", "")
    if exit_after.isdigit():
        QTimer.singleShot(int(exit_after), app.quit)
    app.exec()


def snapshot(
    engine: EchopointEngine,
    path: Path,
    size: tuple[int, int] | None = None,
    page: str = "Today",
) -> Path:
    """Render the window to a PNG without showing it (screenshots, tests)."""
    app, fonts = create_app()
    window = MainWindow(engine, fonts)
    if size is not None:
        window.setFixedSize(*size)
    widget = window.page(page)
    window.ensurePolished()
    layout = window.layout()
    if layout is not None:
        _ = layout.activate()
    app.processEvents()
    # Animated pages (Constellation) jump to their finished state.
    settle = getattr(widget, "settle", None)
    if callable(settle):
        settle()
    window.grab().save(str(path))
    window.deleteLater()
    return path
