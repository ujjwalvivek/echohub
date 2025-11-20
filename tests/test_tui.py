import os
from pathlib import Path

import pytest

from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine
from echohub.renderers.tui import TuiApp


def _terminal_size(_fallback: tuple[int, int]) -> os.terminal_size:
    return os.terminal_size((132, 38))


def _small_terminal_size(_fallback: tuple[int, int]) -> os.terminal_size:
    return os.terminal_size((96, 30))


def test_tui_frame_renders_polished_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(demo_store())
    monkeypatch.setattr("shutil.get_terminal_size", _terminal_size)
    app = TuiApp(engine)
    frame = app.frame()
    assert "ECHOHUB" in frame
    assert "RECENTLY ACTIVE PROJECTS" in frame
    assert "CODE" in frame


def test_tui_projects_supports_semantic_horizontal_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(demo_store())
    monkeypatch.setattr("shutil.get_terminal_size", _small_terminal_size)
    app = TuiApp(engine)
    app.view = 1
    before = app.frame()
    app._horizontal(1)  # pyright: ignore[reportPrivateUsage]
    after = app.frame()
    assert "PROJECT MATRIX" in before
    assert before != after
