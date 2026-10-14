import inspect
from pathlib import Path

import pytest

from echohub.renderers.gui import DashboardGui


def test_gui_has_no_visible_scrollbar_widgets():
    source = inspect.getsource(DashboardGui)
    assert "tk.Scrollbar(" not in source
    assert "ttk.Scrollbar(" not in source
    assert "_bind_scroll" in source


def test_gui_is_rebranded_and_native_dark_chrome_hook_exists():
    source = inspect.getsource(DashboardGui)
    assert 'self.root.title("Echohub")' in source
    assert 'text="ECHOHUB"' in source
    assert "_apply_native_window_theme" in source


def test_progress_bar_has_room_to_show_its_fill(tmp_path: Path) -> None:
    import tkinter as tk

    from echohub.config import DashboardConfig
    from echohub.demo import demo_store
    from echohub.engine import EchopointEngine, ProgressUpdate

    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(demo_store())
    try:
        gui = DashboardGui(engine)
    except tk.TclError:
        pytest.skip("no display available")
    try:
        gui._set_progress(ProgressUpdate("refresh", 0.4, "pass"))  # pyright: ignore[reportPrivateUsage]
        gui.root.update()
        gui.root.update()
        assert gui.progressbar.winfo_ismapped()
        assert gui.progressbar.winfo_height() >= 10, "fill is invisible when squashed"
        assert float(gui.progressbar.cget("value")) == 40.0
    finally:
        gui.root.destroy()
