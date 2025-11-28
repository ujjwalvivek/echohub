import inspect

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
