"""Projects: every tracked repo in one table, details beside it or on Enter."""

from __future__ import annotations

from .... import palette as P
from ....formatting import compact, human_bytes, human_kb, relative_time
from ....models import DashboardState, Project
from ..style import fit, hjoin, paint
from ..table import Column, Table
from ..widgets import page_title, scrollbar
from .base import Context, FilterField, Page, list_moves
from .detail import project_detail

DETAIL = 42  # side pane width
SIDE_FROM = 120  # terminal width that has room for the side pane

COLUMNS: list[Column[Project]] = [
    Column(
        "Project",
        lambda p: p.alias,
        width=16,
        stretch=True,
        kind="strong",
        flag=lambda p: p.private,
        sort=lambda p: p.alias.lower(),
        descending=False,
    ),
    Column(
        "Language",
        lambda p: p.dominant_language,
        width=12,
        kind="swatch",
        tone=lambda p: P.series_color(p.dominant_language),
        sort=lambda p: p.dominant_language.lower(),
        descending=False,
        drop=3,
    ),
    Column(
        "Code",
        lambda p: human_bytes(p.language_bytes) if p.language_bytes else "",
        width=8,
        kind="bar",
        value=lambda p: p.language_bytes,
        sort=lambda p: p.language_bytes,
        drop=4,
    ),
    Column(
        "Size",
        lambda p: human_kb(p.size_kb),
        width=8,
        kind="number",
        sort=lambda p: p.size_kb,
        drop=7,
    ),
    Column(
        "Commits",
        lambda p: compact(p.commit_count),
        width=7,
        kind="bar",
        value=lambda p: p.commit_count,
        sort=lambda p: p.commit_count,
        drop=5,
    ),
    Column(
        "Last push",
        lambda p: relative_time(p.pushed_at) if p.pushed_at else "",
        width=9,
        kind="age",
        stamp=lambda p: p.pushed_at,
        sort=lambda p: p.pushed_at,
    ),
    Column(
        "Release",
        lambda p: p.latest_release.tag if p.latest_release else "",
        width=12,
        kind="pill",
        sort=lambda p: p.latest_release.published_at if p.latest_release else "",
        drop=2,
    ),
    Column(
        "Stars",
        lambda p: str(p.stars) if p.stars else "",
        width=5,
        kind="number",
        tone=lambda _p: P.GOLD,
        sort=lambda p: p.stars,
        drop=6,
    ),
]


def _search(project: Project) -> str:
    release = project.latest_release.tag if project.latest_release else ""
    return " ".join(
        (project.alias, project.dominant_language, release, " ".join(project.topics))
    )


class ProjectsPage(Page):
    name = "Projects"
    keys = (
        ("Enter", "open the project's details"),
        ("Esc", "back to the list"),
        ("/", "filter by name, language, release or topic"),
        ("s / S", "next sort column / reverse the order"),
        ("o", "open the repo on GitHub"),
    )

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.table: Table[Project] = Table(
            COLUMNS, [], sort="Last push", search=_search
        )
        self.filter = FilterField(self.table.set_filter)
        self.detail_open = False
        self.detail_offset = 0
        self._rows = 0
        self._private = 0

    def set_state(self, state: DashboardState) -> None:
        self.table.set_rows(state.projects)
        self._private = sum(project.private for project in state.projects)

    @property
    def typing(self) -> bool:
        return self.filter.active

    def render(self, cells: int, rows: int) -> list[str]:
        self._rows = rows
        if self.detail_open:
            return self._full_detail(cells, rows)
        total = len(self.table.rows)
        subtitle = f"{total} repositories"
        if self._private:
            subtitle += f" · {self._private} private"
        lines = [page_title("Projects", subtitle, cells, self.filter.label()), ""]
        body = rows - 3
        hint = paint(
            "Code is GitHub's language bytes, not lines of code · Enter details · o GitHub",
            P.MUTED,
        )
        if cells >= SIDE_FROM:
            left = cells - DETAIL - 3
            table = self.table.render(left, body)
            detail = project_detail(self.table.selected, DETAIL)[:body]
            divider = [paint("│", P.BORDER_STRONG)] * body
            lines += hjoin((table, left), (divider, 1), (detail, DETAIL), gap=1)
        else:
            lines += self.table.render(cells, body)
        lines += [""] * (rows - 1 - len(lines))
        lines.append(fit(hint, cells))
        return lines

    def _full_detail(self, cells: int, rows: int) -> list[str]:
        project = self.table.selected
        back = paint("Esc", P.ACCENT) + paint(" back to Projects", P.MUTED)
        content = project_detail(project, min(cells - 1, 100))
        body = rows - 2
        self.detail_offset = max(
            0, min(self.detail_offset, max(0, len(content) - body))
        )
        shown = content[self.detail_offset : self.detail_offset + body]
        bar = scrollbar(len(content), self.detail_offset, body)
        lines = [back, ""]
        lines += [fit(line, cells - 1) + bar[index] for index, line in enumerate(shown)]
        return lines

    def key(self, key: str) -> bool:
        # Details first: there, Esc means back, not "clear the filter".
        if self.detail_open:
            if key in ("esc", "backspace", "h", "left"):
                self.detail_open = False
                return True
            move = list_moves(key, self._rows)
            if move is not None:
                self.detail_offset = max(0, self.detail_offset + move)
                return True
            if key == "o":
                return self._open()
            return False
        if self.filter.key(key):
            return True
        move = list_moves(key, self._rows - 3)
        if move is not None:
            self.table.move(move)
            return True
        if key in ("enter", "l", "right"):
            if self.table.selected is not None:
                self.detail_open = True
                self.detail_offset = 0
            return True
        if key in ("s", "S"):
            self.table.cycle_sort(reverse=key == "S")
            return True
        if key == "o":
            return self._open()
        return False

    def _open(self) -> bool:
        project = self.table.selected
        if project is not None and project.html_url:
            self.ctx.open_url(project.html_url)
        return True
