"""Contributions: every year at a glance, then any one year day by day."""

from __future__ import annotations

from .... import palette as P
from ....formatting import compact
from ....insights import YearView, contribution_years, year_view
from ....models import DashboardState
from ..style import hjoin, paint, width
from ..widgets import (
    Stat,
    column_chart,
    hbar,
    heat_legend,
    heatmap,
    page_title,
    section,
    stat_strip,
)
from .base import Context, ScrollPage

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # fmt: skip
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
SUMMARY = 16


class ContributionsPage(ScrollPage):
    name = "Contributions"
    keys = (("h l / ← →", "previous / next year"),)

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.state: DashboardState | None = None
        self.years: list[int] = []
        self.totals: dict[int, int] = {}
        self.year = 0

    def set_state(self, state: DashboardState) -> None:
        self.state = state
        self.years = contribution_years(state)
        self.totals = {
            year: state.user.annual_totals.get(year, 0) for year in self.years
        }
        today = self.ctx.today()
        if self.year not in self.years:
            self.year = (
                today.year
                if today.year in self.years
                else (self.years[-1] if self.years else today.year)
            )

    def key(self, key: str) -> bool:
        if key in ("h", "left", "l", "right") and self.years:
            step = -1 if key in ("h", "left") else 1
            index = self.years.index(self.year) if self.year in self.years else 0
            self.year = self.years[max(0, min(len(self.years) - 1, index + step))]
            return True
        return super().key(key)

    def content(self, cells: int, rows: int) -> list[str]:
        state = self.state
        if state is None:
            return []
        user = state.user
        today = self.ctx.today()
        best = (
            max(self.totals.items(), key=lambda item: item[1]) if self.totals else None
        )
        lines = [
            page_title(
                "Contributions",
                f"GitHub contribution calendar for {user.login or 'you'}",
                cells,
            ),
            "",
        ]
        lines += stat_strip(
            [
                Stat(
                    "All time",
                    compact(user.calendar_total),
                    f"since {self.years[0]}" if self.years else "",
                ),
                Stat("Commit contributions", compact(user.commits)),
                Stat("Pull requests", compact(user.pull_requests)),
                Stat(
                    "Best year",
                    str(best[0]) if best else "-",
                    f"{compact(best[1])} contributions" if best else "",
                ),
            ],
            cells,
        )
        lines.append("")
        view = year_view(state, self.year, today)
        lines += self._year(view, cells)
        lines.append("")
        spare = max(8, rows - len(lines))
        lines += self._charts(view, cells, spare)
        return lines

    def _year(self, view: YearView, cells: int) -> list[str]:
        earlier = self.year != (self.years[0] if self.years else self.year)
        later = self.year != (self.years[-1] if self.years else self.year)
        title = (
            paint("‹ ", P.ACCENT if earlier else P.BORDER_STRONG)
            + paint(str(view.year), P.TEXT, bold=True)
            + paint(" ›", P.ACCENT if later else P.BORDER_STRONG)
        )
        lines = [
            title
            + " "
            + section("", f"{view.total:,} contributions", cells - width(title) - 1)
        ]
        weeks = -(-len(view.days) // 7)
        wide = 4 + weeks * 2 + 3 + SUMMARY <= cells
        grid = heatmap(
            view.days, self.ctx.today(), 4 + weeks * (2 if wide else 1), wide=wide
        )
        grid_width = max(width(line) for line in grid)
        grid.append(" " * max(0, grid_width - width(heat_legend())) + heat_legend())
        room = cells - grid_width - 3
        panes = [(grid, grid_width)]
        if room >= SUMMARY:
            panes.append((self._summary(view), SUMMARY))
            room -= SUMMARY + 3
        if room >= 24:
            panes.insert(1, (self._weekdays(view, room), room))
        return lines + hjoin(*panes, gap=3)

    def _summary(self, view: YearView) -> list[str]:
        best = view.summary.best_day
        lines = [""]
        for caption, value in (
            ("Active days", f"{view.summary.active_days}"),
            (
                "Best day",
                f"{best.count} · {best.day.strftime('%d %b')}" if best else "-",
            ),
            ("Per active day", f"{view.summary.average_active:.1f}"),
        ):
            lines += [paint(caption, P.MUTED), paint(value, P.SUBTLE), ""]
        return lines

    def _weekdays(self, view: YearView, cells: int) -> list[str]:
        """Contributions per weekday, one line per heatmap row (Sunday on
        top), so the bars read as a continuation of the grid."""
        totals = [0] * 7
        for day in view.days:
            if day.count > 0 and day.day.year == view.year:
                totals[(day.day.weekday() + 1) % 7] += day.count
        peak = max(totals) or 1
        track = max(4, cells - 4 - 7)
        lines = [paint("By weekday", P.MUTED)]
        for index, total in enumerate(totals):
            level = min(len(P.HEAT) - 1, 1 + int(total / peak * (len(P.HEAT) - 1)))
            lines.append(
                paint(_WEEKDAYS[index], P.MUTED)
                + " "
                + hbar(total / peak, track, P.HEAT[level] if total else P.BORDER)
                + paint(compact(total).rjust(7), P.TEXT if total == peak else P.SUBTLE)
            )
        return lines

    def _charts(self, view: YearView, cells: int, rows: int) -> list[str]:
        totals = [0] * 12
        for day in view.days:
            if day.count > 0 and day.day.year == view.year:
                totals[day.day.month - 1] += day.count
        today = self.ctx.today()
        months: list[int | None] = [
            None if view.year == today.year and month + 1 > today.month else total
            for month, total in enumerate(totals)
        ]
        years = [self.totals[year] for year in self.years]
        if cells >= 100:
            half = (cells - 3) // 2
            left = [section("Years", f"{len(self.years)} years", half)] + column_chart(
                years, [str(year) for year in self.years], half, rows - 1, P.PINE
            )
            right = [section(f"{view.year} by month", "", half)] + column_chart(
                months, list(_MONTHS), half, rows - 1, P.FOAM
            )
            return hjoin((left, half), (right, half), gap=3)
        chart_rows = max(6, rows // 2 - 1)
        return (
            [section(f"{view.year} by month", "", cells)]
            + column_chart(months, list(_MONTHS), cells, chart_rows, P.FOAM)
            + ["", section("Years", f"{len(self.years)} years", cells)]
            + column_chart(
                years, [str(year) for year in self.years], cells, chart_rows, P.PINE
            )
        )
