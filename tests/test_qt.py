import os
from collections.abc import Callable
from pathlib import Path

import pytest

# Render without a display (CI, headless); must be set before Qt starts.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtGui import QImage

from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine, ProgressUpdate
from echohub.renderers.qt.app import MainWindow, create_app, snapshot


def demo_engine(tmp_path: Path, token: str | None = None) -> EchopointEngine:
    config = DashboardConfig(cache_dir=tmp_path / "cache", refresh_token=token)
    engine = EchopointEngine(config)
    _ = engine.install_demo(demo_store())
    return engine


def test_today_page_renders_to_an_image(tmp_path: Path) -> None:
    out = snapshot(demo_engine(tmp_path), tmp_path / "today.png", size=(1200, 800))
    image = QImage(str(out))
    assert (image.width(), image.height()) == (1200, 800)


def test_busy_state_disables_actions_and_shows_progress(tmp_path: Path) -> None:
    app, fonts = create_app()
    window = MainWindow(demo_engine(tmp_path, token="test-token"), fonts)
    try:
        window._set_busy(True)  # pyright: ignore[reportPrivateUsage]
        assert not window.refresh_button.isEnabled()
        assert not window.progress.isHidden()
        window._on_failed("Can't reach Echopoint\nNothing is answering")  # pyright: ignore[reportPrivateUsage]
        assert window.refresh_button.isEnabled()
        assert window.progress.isHidden()
        assert window.status.text() == (
            "Can't reach Echopoint · showing the saved snapshot"
        )
        assert window.state_mark.state == "failed"
    finally:
        window.deleteLater()
        app.processEvents()


def test_window_uses_custom_chrome(tmp_path: Path) -> None:
    from PySide6.QtCore import QPoint, Qt

    app, fonts = create_app()
    window = MainWindow(demo_engine(tmp_path), fonts)
    try:
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        bar = window.title_bar
        assert window.minimumSize() == window.maximumSize(), "fixed size"
        size = window.size()
        assert size.width() * 9 == size.height() * 16, "16:9"
        assert size.width() <= 1600
        window.show()
        app.processEvents()
        assert bar.is_caption_point(QPoint(bar.width() // 2, bar.height() // 2))
        close = bar.close_button
        button = close.mapTo(bar, close.rect().center())
        assert not bar.is_caption_point(button), "caption buttons stay clickable"

        assert not hasattr(bar, "maximize"), "maximise is disabled"
        assert not window.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_first_run_shows_welcome_until_data_arrives(tmp_path: Path) -> None:
    app, fonts = create_app()
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path / "empty"))
    assert not engine.has_data
    window = MainWindow(engine, fonts)
    try:
        welcome = window.welcome
        assert welcome is not None
        assert window.pages.currentWidget() is welcome
        assert not window.nav_buttons["Projects"].isEnabled()
        window.show_page("Projects")  # ignored without data
        assert window.pages.currentWidget() is welcome

        window._on_failed("Can't reach Echopoint\nNothing is answering at x.")  # pyright: ignore[reportPrivateUsage]
        assert welcome.state == "failed"
        assert welcome.headline.text() == "Can't reach Echopoint"
        assert window.status.text() == "Can't reach Echopoint"

        _ = engine.install_demo(demo_store())
        window._on_done(None)  # pyright: ignore[reportPrivateUsage]
        assert window.welcome is None
        assert window.nav_buttons["Projects"].isEnabled()
        assert window.pages.currentWidget() is window.page("Today")
    finally:
        window.deleteLater()
        app.processEvents()


def test_refresh_without_a_token_explains_instead_of_failing(tmp_path: Path) -> None:
    app, fonts = create_app()
    window = MainWindow(demo_engine(tmp_path), fonts)
    try:
        assert not window.refresh_button.isEnabled()
        window.refresh()
        assert window._task is None  # pyright: ignore[reportPrivateUsage]
        assert window.status.text().startswith("Refresh needs a token")
        window._set_busy(False)  # pyright: ignore[reportPrivateUsage]
        assert not window.refresh_button.isEnabled(), "stays off without a token"
        assert window.check_button.isEnabled()
    finally:
        window.deleteLater()
        app.processEvents()


def test_task_finishes_quietly_after_the_window_is_gone() -> None:
    from shiboken6 import delete

    from echohub.renderers.qt.app import (
        _EngineTask,  # pyright: ignore[reportPrivateUsage]
    )

    def work(progress: Callable[[ProgressUpdate], None]) -> object:
        delete(task.signals)  # what closing the window mid-sync does
        progress(ProgressUpdate("fetch", 0.5, "Downloading"))
        raise OSError("connection reset")

    task = _EngineTask(work, lambda exc: ("Failed", str(exc)))
    task.run()  # neither the progress nor the failure may raise


def test_cancelled_task_stops_at_the_next_step() -> None:
    from echohub.renderers.qt.app import (
        _EngineTask,  # pyright: ignore[reportPrivateUsage]
    )

    steps: list[str] = []

    def work(progress: Callable[[ProgressUpdate], None]) -> object:
        progress(ProgressUpdate("health", 0.1, "Checking"))
        steps.append("health")
        task.cancel()  # the window closed
        progress(ProgressUpdate("fetch", 0.5, "Downloading"))
        steps.append("fetch")
        return None

    task = _EngineTask(work, lambda exc: ("Failed", str(exc)))
    finished: list[object] = []
    task.signals.done.connect(finished.append)
    task.run()
    assert steps == ["health"]
    assert finished == []
