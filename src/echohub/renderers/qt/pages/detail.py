"""Side panel describing one project; shared by Projects and Constellation.

Top to bottom: name and description, links, a strip of three headline numbers,
a facts list, then sections (languages, commits, releases, contributors,
topics) each under a hairline header with its count.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....formatting import compact, human_bytes, human_kb, relative_time, short_date
from ....models import Project
from .. import theme as T
from ..widgets import (
    Chips,
    ElidedLabel,
    PanelHeader,
    ShareBar,
    button,
    label,
    repo_name,
)

DETAIL_WIDTH = 330
_MAX_LANGUAGES = 6
_MAX_COMMITS = 6
_MAX_RELEASES = 5
_MAX_PEOPLE = 4


def open_url(url: str) -> None:
    if url:
        _ = QDesktopServices.openUrl(QUrl(url))


def _row(*widgets: QWidget, stretch_first: bool = True) -> QHBoxLayout:
    line = QHBoxLayout()
    line.setSpacing(8)
    line.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        line.addWidget(widget, 1 if index == 0 and stretch_first else 0)
    return line


def _stat_strip(cells: list[tuple[str, str]]) -> QFrame:
    """Three headline numbers in one bordered strip, like StatStrip but small."""
    strip = QFrame()
    strip.setObjectName("MiniStrip")
    row = QHBoxLayout(strip)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    for index, (caption, value) in enumerate(cells):
        if index:
            line = QFrame()
            line.setObjectName("MiniDivider")
            line.setFixedWidth(1)
            row.addWidget(line)
        cell = QVBoxLayout()
        cell.setContentsMargins(10, 6, 10, 7)
        cell.setSpacing(1)
        cell.addWidget(label(caption, "MiniCaption"))
        cell.addWidget(label(value, "MiniValue"))
        row.addLayout(cell, 1)
    return strip


def _swatch(colour: str) -> QLabel:
    mark = QLabel()
    mark.setFixedSize(8, 8)
    mark.setStyleSheet(f"background: {colour};")
    return mark


class ProjectDetail(QScrollArea):
    def __init__(self, fonts: T.Fonts) -> None:
        super().__init__()
        self._fonts = fonts
        self.setObjectName("Detail")
        self.setFixedWidth(DETAIL_WIDTH)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.show_project(None)

    def _header(self, column: QVBoxLayout, title: str, meta: str = "") -> None:
        column.addSpacing(10)
        column.addWidget(PanelHeader(title, meta, self._fonts))
        column.addSpacing(2)

    def show_project(self, project: Project | None) -> None:
        body = QWidget()
        body.setObjectName("Detail")
        column = QVBoxLayout(body)
        column.setContentsMargins(16, 14, 16, 16)
        column.setSpacing(4)
        if project is None:
            column.addStretch(1)
            hint = label("Select a project to see its details", "Muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(hint)
            column.addStretch(2)
            self.setWidget(body)
            return

        # Identity --------------------------------------------------------------
        column.addWidget(repo_name(project.alias, project.private, "DetailTitle"))
        if project.full_name and project.full_name != project.alias:
            column.addWidget(label(project.full_name, "DetailPath"))
        if project.description:
            text = label(project.description, "Subtle")
            text.setWordWrap(True)
            column.addSpacing(4)
            column.addWidget(text)

        links = QHBoxLayout()
        links.setSpacing(6)
        github = button("Open on GitHub", "Primary", project.html_url)
        github.clicked.connect(lambda: open_url(project.html_url))
        github.setEnabled(bool(project.html_url))
        links.addWidget(github)
        if project.homepage:
            home = button("Homepage", tooltip=project.homepage)
            home.clicked.connect(lambda: open_url(project.homepage))
            links.addWidget(home)
        links.addStretch(1)
        column.addSpacing(8)
        column.addLayout(links)

        # Headline numbers --------------------------------------------------------
        column.addSpacing(12)
        column.addWidget(
            _stat_strip(
                [
                    ("CODE", human_bytes(project.language_bytes)),
                    ("COMMITS", compact(project.commit_count)),
                    (
                        "LAST PUSH",
                        relative_time(project.pushed_at) if project.pushed_at else "-",
                    ),
                ]
            )
        )

        # Facts ---------------------------------------------------------------------
        self._header(column, "Details")
        facts: list[tuple[str, QWidget]] = []
        language = QWidget()
        language_row = QHBoxLayout(language)
        language_row.setContentsMargins(0, 0, 0, 0)
        language_row.setSpacing(6)
        language_row.addWidget(_swatch(T.series_color(project.dominant_language)))
        language_row.addWidget(label(project.dominant_language, "FactValue"))
        facts.append(("Language", language))
        for caption, value in (
            ("Repo size", human_kb(project.size_kb)),
            ("Created", short_date(project.created_at)),
            ("License", project.license_name or "-"),
            ("Branch", project.default_branch or "-"),
        ):
            facts.append((caption, label(value, "FactValue")))
        if project.stars or project.forks or project.open_issues:
            facts.append(
                (
                    "Stars · forks · issues",
                    label(
                        f"{project.stars} · {project.forks} · {project.open_issues}",
                        "FactValue",
                    ),
                )
            )
        for caption, value in facts:
            column.addLayout(_row(label(caption, "FactLabel"), value))

        # Languages -----------------------------------------------------------------
        if project.languages:
            ranked = sorted(project.languages.items(), key=lambda item: -item[1])
            self._header(column, "Languages", str(len(ranked)))
            total = project.language_bytes or 1
            for name, value in ranked[:_MAX_LANGUAGES]:
                share = value / total
                line = QHBoxLayout()
                line.setSpacing(8)
                line.addWidget(_swatch(T.series_color(name)))
                name_label = label(name, "Subtle")
                name_label.setFixedWidth(86)
                line.addWidget(name_label)
                line.addWidget(ShareBar(share, T.series_color(name)), 1)
                percent = label(f"{share:.0%}", "Mono")
                percent.setFixedWidth(32)
                percent.setAlignment(Qt.AlignmentFlag.AlignRight)
                line.addWidget(percent)
                column.addLayout(line)
            if len(ranked) > _MAX_LANGUAGES:
                column.addWidget(
                    label(f"+{len(ranked) - _MAX_LANGUAGES} more", "Muted")
                )

        # Commits -------------------------------------------------------------------
        if project.commits:
            self._header(column, "Recent commits", str(len(project.commits)))
            for commit in project.commits[:_MAX_COMMITS]:
                message = ElidedLabel(
                    commit.message, "Muted" if commit.automated else "Subtle"
                )
                message.setToolTip(commit.message)
                column.addLayout(
                    _row(message, label(relative_time(commit.date), "Mono"))
                )

        # Releases ------------------------------------------------------------------
        releases = project.releases or (
            [project.latest_release] if project.latest_release else []
        )
        if releases:
            self._header(column, "Releases", str(len(releases)))
            for release in releases[:_MAX_RELEASES]:
                line = QHBoxLayout()
                line.setSpacing(8)
                line.addWidget(label(release.tag, "Pill"))
                line.addStretch(1)
                line.addWidget(label(relative_time(release.published_at), "Mono"))
                column.addLayout(line)

        # People --------------------------------------------------------------------
        if project.contributors:
            self._header(column, "Contributors", str(len(project.contributors)))
            for person in project.contributors[:_MAX_PEOPLE]:
                column.addLayout(
                    _row(
                        label(person.login, "Subtle"),
                        label(compact(person.contributions), "Mono"),
                    )
                )

        # Topics --------------------------------------------------------------------
        if project.topics:
            self._header(column, "Topics", str(len(project.topics)))
            column.addSpacing(2)
            column.addWidget(Chips(project.topics, self._fonts))

        column.addStretch(1)
        self.setWidget(body)
