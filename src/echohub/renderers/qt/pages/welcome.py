"""First run: shown until Echohub has a snapshot to draw.

It says what is happening (connecting, downloading), and when that fails,
what went wrong and how to retry, plus where data comes from and whether
private repos are included. The token itself is never shown.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from ....config import DashboardConfig
from .. import theme as T
from ..widgets import button, label


class WelcomePage(QWidget):
    retry = Signal()

    def __init__(self, config: DashboardConfig, fonts: T.Fonts) -> None:
        super().__init__()
        self.state = "idle"
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setFixedWidth(520)
        column = QVBoxLayout(panel)
        column.setContentsMargins(28, 26, 28, 24)
        column.setSpacing(6)

        column.addWidget(label("Welcome to Echohub", "WelcomeTitle"))
        intro = label(
            "Your repos, commits, languages and packages, from your Echopoint "
            + "snapshot. The first download takes a few seconds; after that "
            + "Echohub opens instantly and checks for changes in the background.",
            "Subtle",
        )
        intro.setWordWrap(True)
        column.addWidget(intro)
        column.addSpacing(14)

        self.headline = label("", "WelcomeState")
        self.detail = label("", "Subtle")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.bar = QProgressBar()
        self.bar.setObjectName("WelcomeProgress")
        self.bar.setFixedHeight(3)
        self.bar.setTextVisible(False)
        self.retry_button = button("Try again", "Primary")
        self.retry_button.clicked.connect(self.retry.emit)
        actions = QHBoxLayout()
        actions.addWidget(self.retry_button)
        actions.addStretch(1)
        column.addWidget(self.headline)
        column.addWidget(self.detail)
        column.addSpacing(4)
        column.addWidget(self.bar)
        column.addLayout(actions)
        column.addSpacing(16)

        private = bool(config.refresh_token)
        for caption, value, hint in (
            (
                "Source",
                config.base_url,
                "Set ECHOHUB_SOURCE_URL to use another Echopoint",
            ),
            (
                "Token",
                "set · private repos included"
                if private
                else "not set · public repos only",
                "ECHOHUB_REFRESH_TOKEN adds private repos and enables Refresh",
            ),
            ("Saved to", str(config.cache_dir), "Set ECHOHUB_CACHE_DIR to move it"),
        ):
            row = QHBoxLayout()
            row.setSpacing(12)
            name = label(caption, "FactLabel")
            name.setFixedWidth(64)
            row.addWidget(name)
            value_label = label(value, "WelcomeValue")
            value_label.setToolTip(f"{caption}\n{hint}")
            row.addWidget(value_label, 1)
            column.addLayout(row)

        page = QVBoxLayout(self)
        page.addStretch(2)
        centred = QHBoxLayout()
        centred.addStretch(1)
        centred.addWidget(panel)
        centred.addStretch(1)
        page.addLayout(centred)
        page.addStretch(3)
        self.show_idle()

    def show_idle(self) -> None:
        self.state = "idle"
        self.headline.setText("No snapshot yet")
        self.detail.setText("Press Check (C) to download it.")
        self.bar.hide()
        self.retry_button.setText("Download snapshot")
        self.retry_button.show()

    def show_progress(self, message: str, fraction: float | None) -> None:
        self.state = "loading"
        self.headline.setText("Downloading your first snapshot")
        self.detail.setText(message)
        self.bar.show()
        if fraction is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(fraction * 100))
        self.retry_button.hide()

    def show_failure(self, title: str, detail: str) -> None:
        self.state = "failed"
        self.headline.setText(title)
        self.detail.setText(detail)
        self.bar.hide()
        self.retry_button.setText("Try again")
        self.retry_button.show()
