import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPoint

from echohub.renderers.qt.app import create_app
from echohub.renderers.qt.table import Column, RecordTable
from echohub.renderers.qt.tooltip import current_tip, hide_tip, show_tip, split_tip


def test_split_tip_reads_title_key_and_detail() -> None:
    assert split_tip("Refresh  ·  R\nAsk Echopoint") == (
        "Refresh",
        "R",
        "Ask Echopoint",
    )
    assert split_tip("Projects  ·  2") == ("Projects", "2", "")
    # A middle dot in prose is not a shortcut.
    title, key, _ = split_tip("echohub  ·  223 KB of Python code")
    assert key == ""
    assert title == "echohub  ·  223 KB of Python code"


def test_tip_window_shows_and_hides() -> None:
    app, _ = create_app()
    show_tip(QPoint(200, 200), "Check  ·  C\nDownload the snapshot")
    tip = current_tip()
    assert tip is not None
    assert tip.isVisible()
    assert (tip.title, tip.key, tip.detail) == ("Check", "C", "Download the snapshot")
    assert tip.width() <= 320 + 20
    hide_tip()
    app.processEvents()
    assert not tip.isVisible()


def test_column_help_becomes_the_header_tooltip() -> None:
    from PySide6.QtCore import Qt

    _, fonts = create_app()
    columns: list[Column[int]] = [
        Column("Code", lambda n: n, help="GitHub language bytes")
    ]
    table: RecordTable[int] = RecordTable(columns, [1, 2], fonts)
    tip = table.model().headerData(
        0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole
    )
    assert tip == "Code\nGitHub language bytes"
