"""Activity: the commit ledger across every repo."""

from __future__ import annotations

from collections import Counter

from .... import palette as P
from ....formatting import compact, relative_time, short_date
from ....insights import LedgerCommit, commit_ledger
from ....models import DashboardState
from ..style import fit, paint
from ..table import Column, Table
from ..widgets import Stat, page_title, stat_strip
from .base import Context, FilterField, Page, list_moves

COLUMNS: list[Column[LedgerCommit]] = [
    Column(
        "Date",
        lambda c: short_date(c.date),
        width=10,
        kind="code",
        sort=lambda c: c.date,
        drop=4,
    ),
    Column(
        "When",
        lambda c: relative_time(c.date),
        width=8,
        kind="age",
        stamp=lambda c: c.date,
        sort=lambda c: c.date,
    ),
    Column(
        "Project",
        lambda c: c.alias,
        width=16,
        kind="strong",
        flag=lambda c: c.private,
        sort=lambda c: c.alias.lower(),
        descending=False,
    ),
    Column(
        "Message",
        lambda c: c.message,
        width=20,
        stretch=True,
        tone=lambda c: P.MUTED if c.automated else P.SUBTLE,
        sort=lambda c: c.message.lower(),
        descending=False,
    ),
    Column(
        "Changes",
        lambda c: "",
        kind="diff",
        pair=lambda c: (c.additions, c.deletions),
        sort=lambda c: c.additions + c.deletions,
        drop=2,
    ),
    Column("Commit", lambda c: c.sha, width=7, kind="code", drop=3),
    Column(
        "Author",
        lambda c: c.author,
        width=12,
        kind="muted",
        sort=lambda c: c.author.lower(),
        descending=False,
        drop=5,
    ),
]


def _search(row: LedgerCommit) -> str:
    return f"{row.alias} {row.message} {row.author} {row.sha}"


def _human(row: LedgerCommit) -> bool:
    return not row.automated


class ActivityPage(Page):
    name = "Activity"
    keys = (
        ("/", "filter commits"),
        ("a", "show or hide automated commits"),
        ("s / S", "next sort column / reverse the order"),
        ("o", "open the commit on GitHub"),
    )

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.table: Table[LedgerCommit] = Table(
            COLUMNS, [], sort="Date", search=_search
        )
        self.table.set_predicate(_human)
        self.filter = FilterField(self.table.set_filter)
        self.show_automated = False
        self.stats: list[Stat] = []
        self._rows = 0

    def set_state(self, state: DashboardState) -> None:
        ledger = commit_ledger(state.projects)
        self.table.set_rows(ledger)
        human = [row for row in ledger if not row.automated]
        automated = len(ledger) - len(human)
        busiest = Counter(row.alias for row in human).most_common(1)
        self.stats = [
            Stat(
                "Commits sampled",
                str(len(human)),
                f"{automated} automated hidden" if automated else "",
            ),
            Stat("Added", f"+{compact(sum(r.additions for r in human))}", "", P.FOAM),
            Stat("Removed", f"−{compact(sum(r.deletions for r in human))}", "", P.LOVE),
            Stat(
                "Busiest repo",
                busiest[0][0] if busiest else "-",
                f"{busiest[0][1]} commits" if busiest else "",
            ),
        ]

    @property
    def typing(self) -> bool:
        return self.filter.active

    def render(self, cells: int, rows: int) -> list[str]:
        self._rows = rows
        lines = [
            page_title(
                "Activity",
                "Each repo's latest commits as cached by Echopoint",
                cells,
                self.filter.label(),
            ),
            "",
        ]
        lines += stat_strip(self.stats, cells)
        lines.append("")
        body = rows - len(lines) - 1
        lines += self.table.render(cells, body)
        lines += [""] * (rows - 1 - len(lines))
        automated = "a hide automated" if self.show_automated else "a show automated"
        lines.append(fit(paint(f"{automated} · o open on GitHub", P.MUTED), cells))
        return lines

    def key(self, key: str) -> bool:
        if self.filter.key(key):
            return True
        move = list_moves(key, self._rows - 8)
        if move is not None:
            self.table.move(move)
            return True
        if key == "a":
            self.show_automated = not self.show_automated
            self.table.set_predicate(None if self.show_automated else _human)
            return True
        if key in ("s", "S"):
            self.table.cycle_sort(reverse=key == "S")
            return True
        if key == "o":
            row = self.table.selected
            if row is not None and row.url:
                self.ctx.open_url(row.url)
            return True
        return False
