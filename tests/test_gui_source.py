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
        bar = gui.progressbar
        # Check the layout arithmetic rather than on-screen size: CI desktops
        # can create Tk windows without ever mapping them.
        statusbar = bar.nametowidget(bar.winfo_parent())
        inner = int(statusbar.cget("height")) - 2 * int(
            statusbar.cget("highlightthickness")
        )
        pady = str(bar.pack_info().get("pady", 0)).split()
        padding = sum(int(float(part)) for part in pady) * (2 if len(pady) == 1 else 1)
        assert inner - padding >= bar.winfo_reqheight(), (
            "padding squeezes the bar below its height, hiding the fill"
        )
        assert float(bar.cget("value")) == 40.0
    finally:
        gui.root.destroy()
