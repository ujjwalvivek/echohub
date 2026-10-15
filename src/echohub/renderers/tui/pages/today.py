"""Today: the streak, what changed this week, and what needs a look."""

from __future__ import annotations

from datetime import datetime
from itertools import groupby

from .... import palette as P
from ....formatting import compact, relative_time
from ....models import DashboardState
from ....today import PackageLine, TodayView, build_today
from ..style import fit, hjoin, paint, spread, width
from ..widgets import (
    DIFF_WIDTH,
    Stat,
    banner,
    column_chart,
    diff_bar,
    heat_legend,
    heatmap,
    page_title,
    pill,
    private_mark,
    section,
    stat_strip,
)
from .base import Context, ScrollPage

WEEKS = 26
SUMMARY = 18


def _delta(current: int, previous: int) -> tuple[str, str]:
    if previous == 0:
        return (
            "first activity in two weeks" if current else "quiet two weeks",
            P.SUBTLE,
        )
    change = (current - previous) / previous
    arrow = "▲" if change >= 0 else "▼"
    return (
        f"{arrow} {abs(change):.0%} vs last week ({previous})",
        P.FOAM if change >= 0 else P.GOLD,
    )


class TodayPage(ScrollPage):
    name = "Today"

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.view: TodayView | None = None

    def set_state(self, state: DashboardState) -> None:
        self.view = build_today(state, datetime.now().astimezone())

    def content(self, cells: int, rows: int) -> list[str]:
        view = self.view
        if view is None:
            return []
        lines = [self._title(view, cells)]
        lines += [banner(item, cells) for item in view.attention]
        lines.append("")
        lines += self._stats(view, cells)
        lines.append("")
        lines += self._contributions(view, cells)
        lines.append("")
        lines += self._recent(view, cells)
        lines.append("")
        lines += self._packages(view, cells)
        lines.append("")
        # The weekly chart takes whatever height is left, at least 7 lines.
        spare = rows - len(lines) - 1
        lines += self._weeks(view, cells, max(7, spare))
        return lines

    def _title(self, view: TodayView, cells: int) -> str:
        updated = (
            relative_time(view.snapshot_updated) if view.snapshot_updated else "never"
        )
        subtitle = f"{view.today.strftime('%A %d %B')} · data updated {updated}"
        clear = paint("✓ All clear", P.FOAM) if not view.attention else ""
        return page_title("Today", subtitle, cells, clear)

    def _stats(self, view: TodayView, cells: int) -> list[str]:
        streak = view.streak
        if streak.current:
            note = (
                "extended today"
                if streak.active_today
                else "contribute today to extend it"
            )
            tone = P.FOAM if streak.active_today else P.GOLD
        else:
            note, tone = "no streak running", P.SUBTLE
        delta, delta_tone = _delta(view.week_total, view.previous_week_total)
        return stat_strip(
            [
                Stat("Current streak", f"{streak.current:,} days", note, tone),
                Stat(
                    "Longest streak", f"{streak.longest:,} days", "since tracking began"
                ),
                Stat("Last 7 days", f"{view.week_total:,}", delta, delta_tone),
                Stat(
                    "Active repos",
                    str(view.active_repos),
                    f"{view.today_total} contributions today",
                ),
            ],
            cells,
        )

    def _contributions(self, view: TodayView, cells: int) -> list[str]:
        lines = [
            section("Contributions", f"{view.year_total:,} in the last year", cells)
        ]
        weeks = -(-len(view.heatmap) // 7)
        wide = 4 + weeks * 2 + 2 + SUMMARY <= cells
        grid = heatmap(
            view.heatmap,
            view.today,
            min(cells, 4 + weeks * (2 if wide else 1)),
            wide=wide,
        )
        grid.append(fit(heat_legend(), width(grid[1]), "right"))
        grid_width = max(width(line) for line in grid)
        room = cells - grid_width - 3
        if room < SUMMARY:
            return lines + grid
        year = view.year
        best = (
            f"{year.best_day.count} · {year.best_day.day.strftime('%d %b')}"
            if year.best_day
            else "-"
        )
        summary = [""]
        for caption, value in (
            ("Active days", f"{year.active_days} of {len(view.heatmap)}"),
            ("Best day", best),
            ("Per active day", f"{year.average_active:.1f}"),
        ):
            summary += [paint(caption, P.MUTED), paint(value, P.SUBTLE), ""]
        panes = [(grid, grid_width), (summary, SUMMARY)]
        chart_room = room - SUMMARY - 3
        if chart_room >= 24:
            days = [d for d in view.heatmap if d.count >= 0 and d.day <= view.today][
                -30:
            ]
            chart = [paint("Last 30 days", P.MUTED)] + column_chart(
                [d.count for d in days],
                [d.day.strftime("%d %b") for d in days],
                chart_room,
                len(grid) - 1,
                P.FOAM,
            )
            panes.append((chart, chart_room))
        return lines + hjoin(*panes, gap=3)

    def _recent(self, view: TodayView, cells: int) -> list[str]:
        if cells >= 110:
            left = cells * 3 // 5
            right = cells - left - 3
            return hjoin(
                (self._commits(view, left), left),
                (self._releases(view, right), right),
                gap=3,
            )
        return self._commits(view, cells) + [""] + self._releases(view, cells)

    def _commits(self, view: TodayView, cells: int) -> list[str]:
        # Echopoint keeps each repo's latest few commits: a sample of recent
        # work, not a full count (the contribution numbers are complete).
        lines = [section("Recent commits", "last 7 days", cells)]
        if not view.activity:
            lines.append(paint("No commits in the last 7 days.", P.MUTED))
        show_diff = cells >= 100
        peak = max((max(a.additions, a.deletions) for a in view.activity), default=0)
        for item in view.activity:
            name = private_mark(item.private) + fit(paint(item.alias, P.TEXT), 16)
            count = fit(pill(str(item.commits)), 5)
            when = fit(paint(relative_time(item.latest_date), P.SUBTLE), 8, "right")
            fixed = width(name) + 5 + 8 + 3 + (DIFF_WIDTH + 1 if show_diff else 0)
            message = fit(paint(item.latest_message, P.SUBTLE), max(4, cells - fixed))
            parts = [name, count, message]
            if show_diff:
                parts.append(diff_bar(item.additions, item.deletions, peak))
            parts.append(when)
            lines.append(" ".join(parts))
        for folded in view.automated:
            noun = "commit" if folded.commits == 1 else "commits"
            lines.append(
                paint(
                    f"{folded.alias} · {folded.commits} automated {noun} hidden",
                    P.MUTED,
                )
            )
        return lines

    def _releases(self, view: TodayView, cells: int) -> list[str]:
        lines = [section("Releases", "last 30 days", cells)]
        if not view.releases:
            lines.append(paint("No releases this month.", P.MUTED))
        for alias, group in groupby(view.releases, key=lambda release: release.alias):
            releases = list(group)
            latest = releases[0]
            earlier = len(releases) - 1
            right = (
                pill(latest.tag)
                + " "
                + fit(paint(f"+{earlier}" if earlier else "", P.MUTED), 3)
                + fit(paint(relative_time(latest.published_at), P.SUBTLE), 9, "right")
            )
            lines.append(spread(paint(alias, P.TEXT), right, cells))
        return lines

    def _packages(self, view: TodayView, cells: int) -> list[str]:
        lines = [section("Packages", f"{len(view.packages)} published", cells)]
        if not view.packages:
            return lines + [paint("Nothing published yet.", P.MUTED)]
        columns = max(1, min(3, (cells + 3) // 40))
        each = (cells - 3 * (columns - 1)) // columns
        per = -(-len(view.packages) // columns)
        # Fill down each column first so each registry's packages stay together.
        stacks = [
            [self._package(item, each) for item in view.packages[i : i + per]]
            for i in range(0, len(view.packages), per)
        ]
        return lines + hjoin(*((stack, each) for stack in stacks), gap=3)

    def _package(self, item: PackageLine, cells: int) -> str:
        if item.recent_downloads is not None:
            usage = f"{compact(item.recent_downloads)}/{item.downloads_period}"
        elif item.updated_at:
            usage = relative_time(item.updated_at)
        else:
            usage = ""
        left = fit(pill(item.ecosystem), 9) + paint(item.name, P.TEXT)
        right = pill(item.version) + fit(paint(usage, P.MUTED), 9, "right")
        return spread(left, right, cells)

    def _weeks(self, view: TodayView, cells: int, rows: int) -> list[str]:
        """Weekly totals for the last half year, newest last."""
        days = [day for day in view.heatmap if day.count >= 0 and day.day <= view.today]
        weeks: list[tuple[str, int]] = []
        for end in range(len(days), 0, -7):
            chunk = days[max(0, end - 7) : end]
            if len(chunk) < 7:
                break
            weeks.append((chunk[0].day.strftime("%d %b"), sum(d.count for d in chunk)))
        weeks = list(reversed(weeks[:WEEKS]))
        total = sum(count for _, count in weeks)
        lines = [
            section(
                f"Last {len(weeks)} weeks",
                f"{total:,} contributions · {total / max(1, len(weeks)):.0f} a week",
                cells,
            )
        ]
        return lines + column_chart(
            [count for _, count in weeks],
            [start for start, _ in weeks],
            cells,
            rows - 1,
            P.PINE,
        )
