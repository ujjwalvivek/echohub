"""Activity: the commit ledger across every repo."""

from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

from ....formatting import compact, relative_time, short_date
from ....insights import LedgerCommit, commit_ledger
from ....models import DashboardState
from .. import theme as T
from ..table import Column, RecordTable
from ..widgets import StatStrip, label, page_header
from .detail import open_url


def _message_tone(row: LedgerCommit) -> str | None:
    return T.MUTED if row.automated else None


COLUMNS: list[Column[LedgerCommit]] = [
    Column(
        "Date",
        lambda c: c.date,
        lambda c: short_date(c.date),
        numeric=True,
        width=96,
        tone=lambda _c: T.MUTED,
        help="Commit date",
    ),
    Column(
        "When",
        lambda c: c.date,
        lambda c: relative_time(c.date),
        numeric=True,
        width=76,
        kind="age",
        help="How long ago, brighter when recent",
    ),
    Column(
        "Project",
        lambda c: c.alias.lower(),
        lambda c: c.alias,
        width=160,
        kind="strong",
        flag=lambda c: c.private,
        help="Repo the commit belongs to",
    ),
    Column(
        "Message",
        lambda c: c.message,
        stretch=True,
        tone=_message_tone,
        tooltip=lambda c: c.message,
        help="First line of the commit message",
    ),
    Column(
        "Changes",
        lambda c: c.additions + c.deletions,
        lambda c: f"+{compact(c.additions)} −{compact(c.deletions)}",
        numeric=True,
        width=200,
        kind="diff",
        pair=lambda c: (c.additions, c.deletions),
        tooltip=lambda c: f"{c.additions:,} added · {c.deletions:,} removed",
        help="Lines removed (left, red) and added (right, green); log scale",
    ),
    Column(
        "Commit",
        lambda c: c.sha,
        kind="code",
        help="Short SHA; double-click a row to open it on GitHub",
    ),
    Column("Author", lambda c: c.author, width=120, kind="muted", help="Commit author"),
]


class ActivityPage(QWidget):
    def __init__(self, state: DashboardState, fonts: T.Fonts) -> None:
        super().__init__()
        ledger = commit_ledger(state.projects)
        human = [row for row in ledger if not row.automated]
        automated = len(ledger) - len(human)

        strip = StatStrip()
        strip.add(
            "Commits sampled",
            str(len(human)),
            f"{automated} automated hidden" if automated else "",
        )
        strip.add("Added", f"+{compact(sum(r.additions for r in human))}", "", "Good")
        strip.add("Removed", f"−{compact(sum(r.deletions for r in human))}", "", "Bad")
        busiest = Counter(row.alias for row in human).most_common(1)
        strip.add(
            "Busiest repo",
            busiest[0][0] if busiest else "-",
            f"{busiest[0][1]} commits" if busiest else "",
        )

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter commits…")
        self.filter.setFixedWidth(260)
        self.filter.setClearButtonEnabled(True)
        self.show_automated = QCheckBox("Show automated")
        self.table: RecordTable[LedgerCommit] = RecordTable(COLUMNS, ledger, fonts)
        self.table.sort_by("Date")
        self.table.set_predicate(lambda row: not row.automated)
        self.filter.textChanged.connect(self.table.set_filter)
        self.show_automated.toggled.connect(
            lambda shown: self.table.set_predicate(
                None if shown else (lambda row: not row.automated)
            )
        )
        self.table.activated.connect(lambda row: open_url(row.url))

        page = QVBoxLayout(self)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        page.setSpacing(T.GAP)
        page.addLayout(
            page_header(
                "Activity",
                "Each repo's latest commits as cached by Echopoint",
                self.show_automated,
                self.filter,
            )
        )
        page.addWidget(strip)
        page.addWidget(self.table, 1)
        page.addWidget(label("Double-click a commit to open it on GitHub", "Muted"))
