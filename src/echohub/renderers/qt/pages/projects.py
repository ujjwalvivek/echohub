"""Projects: every tracked repo in one table, details on the right."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ....formatting import compact, human_bytes, human_kb, relative_time
from ....models import DashboardState, Project
from .. import theme as T
from ..table import Column, RecordTable
from ..widgets import label, page_header
from .detail import ProjectDetail, open_url


def _language_tone(project: Project) -> str | None:
    return T.MUTED if not project.languages else None


COLUMNS: list[Column[Project]] = [
    Column(
        "Project",
        lambda p: p.alias.lower(),
        lambda p: p.alias,
        stretch=True,
        kind="strong",
        flag=lambda p: p.private,
        tooltip=lambda p: p.description,
        help="Repo name; the padlock marks a private repo",
    ),
    Column(
        "Language",
        lambda p: p.dominant_language,
        tone=_language_tone,
        width=120,
        kind="swatch",
        help="The language with the most code in the repo",
    ),
    Column(
        "Code",
        lambda p: p.language_bytes,
        lambda p: human_bytes(p.language_bytes) if p.language_bytes else "",
        numeric=True,
        kind="bar",
        help="GitHub language bytes, not lines of code",
    ),
    Column(
        "Size",
        lambda p: p.size_kb,
        lambda p: human_kb(p.size_kb),
        numeric=True,
        help="Repository size on GitHub, history included",
    ),
    Column(
        "Commits",
        lambda p: p.commit_count,
        lambda p: compact(p.commit_count),
        numeric=True,
        kind="bar",
        help="Commits on the default branch",
    ),
    Column(
        "Last push",
        lambda p: p.pushed_at,
        lambda p: relative_time(p.pushed_at) if p.pushed_at else "",
        numeric=True,
        kind="age",
        help="When the repo last received a push",
    ),
    Column(
        "Release",
        lambda p: p.latest_release.published_at if p.latest_release else "",
        lambda p: p.latest_release.tag if p.latest_release else "",
        width=120,
        kind="pill",
        help="Latest release tag",
    ),
    # Forks, issues and contributors are nearly always 0 or 1 here; they live
    # in the detail panel. Stars stay, blank when zero, so the few stand out.
    Column(
        "Stars",
        lambda p: p.stars,
        lambda p: str(p.stars) if p.stars else "",
        numeric=True,
        tone=lambda _p: T.GOLD,
        hide_if_empty=True,
        help="GitHub stars",
    ),
]


class ProjectsPage(QWidget):
    def __init__(self, state: DashboardState, fonts: T.Fonts) -> None:
        super().__init__()
        projects = state.projects
        private = sum(project.private for project in projects)
        subtitle = f"{len(projects)} repositories"
        if private:
            subtitle += f" · {private} private"

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name, language or release…")
        self.filter.setFixedWidth(260)
        self.filter.setClearButtonEnabled(True)
        self.table: RecordTable[Project] = RecordTable(COLUMNS, projects, fonts)
        self.table.sort_by("Last push")
        self.detail = ProjectDetail(fonts)
        self.table.selected.connect(self.detail.show_project)
        self.table.activated.connect(lambda project: open_url(project.html_url))
        self.filter.textChanged.connect(self.table.set_filter)

        content = QVBoxLayout()
        content.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        content.setSpacing(T.GAP)
        content.addLayout(page_header("Projects", subtitle, self.filter))
        content.addWidget(self.table, 1)
        content.addWidget(
            label(
                "Code is GitHub's language bytes, not lines of code · double-click opens GitHub",
                "Muted",
            )
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(content, 1)
        root.addWidget(self.detail)
        self.table.select_first()
