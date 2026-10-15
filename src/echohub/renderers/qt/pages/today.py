"""The Today page: what changed, how the streak is going, what needs you."""

from __future__ import annotations

from itertools import groupby

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....formatting import compact, relative_time
from ....today import Attention, PackageLine, TodayView
from .. import theme as T
from ..charts import AreaChart
from ..widgets import (
    Card,
    DiffBar,
    ElidedLabel,
    Heatmap,
    Legend,
    StatStrip,
    divider,
    hbox,
    label,
    repo_name,
)

PACKAGE_COLUMNS = 3
WEEKS = 26


def _row(*parts: QWidget | None, spacing: int = 10) -> QWidget:
    row = QWidget()
    row.setObjectName("Row")
    layout = hbox(*parts, spacing=spacing)
    layout.setContentsMargins(T.ROW_X, T.ROW_Y, T.ROW_X, T.ROW_Y)
    row.setLayout(layout)
    return row


def _empty(text: str) -> QWidget:
    return _row(label(text, "Muted"), None)


def _delta(current: int, previous: int) -> tuple[str, str]:
    if previous == 0:
        return (
            "first activity in two weeks" if current else "quiet two weeks",
            "StatNote",
        )
    change = (current - previous) / previous
    arrow = "▲" if change >= 0 else "▼"
    tone = "Good" if change >= 0 else "Warn"
    return (f"{arrow} {abs(change):.0%} vs last week ({previous})", tone)


def _banner(item: Attention) -> QFrame:
    """One line per problem, shown only when there is one."""
    frame = QFrame()
    frame.setObjectName("Banner")
    frame.setProperty("level", item.level)
    layout = hbox(
        label("●", "Bad" if item.level == "error" else "Warn"),
        label(item.title),
        ElidedLabel(item.detail, "Muted") if item.detail else None,
        spacing=8,
    )
    layout.setContentsMargins(10, 5, 10, 5)
    frame.setLayout(layout)
    return frame


class TodayPage(QScrollArea):
    def __init__(
        self,
        view: TodayView,
        fonts: T.Fonts,
    ) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fonts = fonts
        content = QWidget()
        page = QVBoxLayout(content)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_X)
        page.setSpacing(T.GAP)
        self.setWidget(content)

        page.addLayout(self._header(view))
        for item in view.attention:
            page.addWidget(_banner(item))
        page.addWidget(self._stats(view))
        page.addWidget(self._heatmap(view))

        pair = QHBoxLayout()
        pair.setSpacing(T.GAP)
        pair.addWidget(self._activity(view), 3)
        pair.addWidget(self._releases(view), 2)
        page.addLayout(pair)
        page.addWidget(self._packages(view))
        page.addWidget(self._weeks(view), 1)

    def _header(self, view: TodayView) -> QHBoxLayout:
        updated = (
            relative_time(view.snapshot_updated) if view.snapshot_updated else "never"
        )
        subtitle = hbox(
            label(
                f"{view.today.strftime('%A %d %B')} · data updated {updated}",
                "PageSubtitle",
            ),
            spacing=10,
        )
        if not view.attention:
            subtitle.addWidget(label("✓ All clear", "Good"))
        subtitle.addStretch(1)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("Today", "PageTitle"))
        titles.addLayout(subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, 1)
        return header

    def _stats(self, view: TodayView) -> StatStrip:
        strip = StatStrip()
        streak = view.streak
        if streak.current:
            note = (
                "extended today"
                if streak.active_today
                else "contribute today to extend it"
            )
            tone = "Good" if streak.active_today else "Warn"
        else:
            note, tone = "no streak running", "StatNote"
        strip.add("Current streak", f"{streak.current:,} days", note, tone)
        strip.add("Longest streak", f"{streak.longest:,} days", "since tracking began")
        delta, delta_tone = _delta(view.week_total, view.previous_week_total)
        strip.add("Last 7 days", f"{view.week_total:,}", delta, delta_tone)
        strip.add(
            "Active repos",
            str(view.active_repos),
            f"{view.today_total} contributions today",
        )
        return strip

    def _heatmap(self, view: TodayView) -> Card:
        card = Card("Contributions", f"{view.year_total:,} in the last year")
        grid = QVBoxLayout()
        grid.setSpacing(6)
        grid.addWidget(Heatmap(view.heatmap, self._fonts.ui, view.today))
        grid.addWidget(Legend(self._fonts.ui), 0, Qt.AlignmentFlag.AlignRight)

        year = view.year
        summary = QVBoxLayout()
        summary.setSpacing(8)
        best = (
            f"{year.best_day.count} · {year.best_day.day.strftime('%d %b')}"
            if year.best_day
            else "-"
        )
        for caption, value in (
            ("Active days", f"{year.active_days} of {len(view.heatmap)}"),
            ("Best day", best),
            ("Per active day", f"{year.average_active:.1f}"),
        ):
            pair = QVBoxLayout()
            pair.setSpacing(0)
            pair.addWidget(label(caption, "StatLabel"))
            pair.addWidget(label(value, "Mono"))
            summary.addLayout(pair)
        summary.addStretch(1)

        recent = QVBoxLayout()
        recent.setSpacing(2)
        recent.addWidget(label("Last 30 days", "StatLabel"))
        chart = AreaChart(self._fonts.ui, self._fonts.mono, T.FOAM)
        chart.setMinimumHeight(0)
        chart.setFixedHeight(Heatmap.TOP + 7 * (Heatmap.CELL + Heatmap.GAP) + 8)
        days = [day for day in view.heatmap if 0 <= day.count and day.day <= view.today]
        days = days[-30:]
        chart.set_points(
            [day.day.strftime("%d %b") for day in days],
            [day.count for day in days],
        )
        recent.addWidget(chart)
        recent.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(20)
        row.addLayout(grid)
        row.addWidget(divider(vertical=True))
        row.addLayout(summary)
        row.addWidget(divider(vertical=True))
        row.addLayout(recent, 1)
        card.body.addLayout(row)
        return card

    def _weeks(self, view: TodayView) -> Card:
        """Weekly totals for the last half year: the trend between the
        30-day chart and the year's grid. Stretches to fill the page."""
        days = [day for day in view.heatmap if day.count >= 0 and day.day <= view.today]
        weeks: list[tuple[str, int]] = []
        # Whole weeks ending today, newest last.
        for end in range(len(days), 0, -7):
            chunk = days[max(0, end - 7) : end]
            if len(chunk) < 7:
                break
            weeks.append((chunk[0].day.strftime("%d %b"), sum(d.count for d in chunk)))
        weeks = list(reversed(weeks[:WEEKS]))
        total = sum(count for _, count in weeks)
        card = Card(
            f"Last {len(weeks)} weeks",
            f"{total:,} contributions · {total / max(1, len(weeks)):.0f} a week",
            fill=True,
        )
        chart = AreaChart(self._fonts.ui, self._fonts.mono, T.PINE)
        chart.set_points([start for start, _ in weeks], [count for _, count in weeks])
        chart.setToolTip("")
        card.add(chart)
        return card

    def _activity(self, view: TodayView) -> Card:
        # Echopoint keeps each repo's latest few commits, so this is a sample of
        # recent work, not a full count (the contribution numbers are complete).
        card = Card("Recent commits", "last 7 days")
        if not view.activity:
            card.add(_empty("No commits in the last 7 days."))
        for item in view.activity:
            name = repo_name(item.alias, item.private)
            name.setFixedWidth(140)
            count = label(f"{item.commits}", "Pill", tooltip="commits in the sample")
            churn = DiffBar(item.additions, item.deletions, self._fonts)
            when = label(relative_time(item.latest_date), "Mono")
            when.setFixedWidth(52)
            when.setAlignment(Qt.AlignmentFlag.AlignRight)
            message = ElidedLabel(item.latest_message, "Subtle")
            message.setToolTip(item.latest_message)
            card.add(_row(name, count, message, churn, when))
        for folded in view.automated:
            noun = "commit" if folded.commits == 1 else "commits"
            card.add(
                _row(
                    label(
                        f"{folded.alias} · {folded.commits} automated {noun} hidden",
                        "Muted",
                    ),
                    None,
                )
            )
        return card

    def _releases(self, view: TodayView) -> Card:
        card = Card("Releases", "last 30 days")
        if not view.releases:
            card.add(_empty("No releases this month."))
        for alias, group in groupby(view.releases, key=lambda release: release.alias):
            releases = list(group)
            latest = releases[0]
            earlier = len(releases) - 1
            when = label(relative_time(latest.published_at), "Mono")
            when.setAlignment(Qt.AlignmentFlag.AlignRight)
            card.add(
                _row(
                    ElidedLabel(alias),
                    label(latest.tag, "Pill"),
                    label(f"+{earlier}" if earlier else "", "Muted"),
                    when,
                )
            )
        return card

    def _package(self, item: PackageLine) -> QWidget:
        if item.recent_downloads is not None:
            usage = f"{compact(item.recent_downloads)}/{item.downloads_period}"
        elif item.updated_at:
            usage = relative_time(item.updated_at)
        else:
            usage = ""
        ecosystem = label(item.ecosystem, "Pill")
        ecosystem.setFixedWidth(42)
        ecosystem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        usage_label = label(usage, "Muted")
        usage_label.setFixedWidth(52)
        usage_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        return _row(
            ecosystem,
            ElidedLabel(item.name),
            label(item.version, "Pill"),
            usage_label,
            spacing=8,
        )

    def _packages(self, view: TodayView) -> Card:
        card = Card("Packages", f"{len(view.packages)} published")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)
        # Fill down each column first so each registry's packages stay together.
        rows = -(-len(view.packages) // PACKAGE_COLUMNS) or 1
        for index, item in enumerate(view.packages):
            column, row = divmod(index, rows)
            grid.addWidget(self._package(item), row, column)
        for column in range(PACKAGE_COLUMNS):
            grid.setColumnStretch(column, 1)
        card.body.addLayout(grid)
        return card
