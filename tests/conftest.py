from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def close_qt_widgets() -> Iterator[None]:
    """Delete every Qt widget the tests left alive, while Qt still runs.

    Tests build pages and windows without tearing them down. Left for the
    interpreter's shutdown, they get destroyed in arbitrary order, sometimes
    after QApplication, which crashes the process after all tests passed.
    """
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
