"""Contributions: every year at a glance, then any one year day by day."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ....formatting import compact
from ....insights import YearView, contribution_years, year_view
from ....models import DashboardState
from .. import theme as T
from ..charts import AreaChart
from ..widgets import Card, Heatmap, Legend, StatStrip, divider, label, page_header

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # fmt: skip
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


class WeekdayBars(QWidget):
    """Contributions per weekday, one row per heatmap row (Sunday on top),
    so the bars read as a continuation of the grid beside them."""

    LABEL = 30
    VALUE = 44

    def __init__(self, view: YearView, ui_family: str, mono_family: str) -> None:
        super().__init__()
        self._totals = [0] * 7
        for day in view.days:
            if day.count > 0 and day.day.year == view.year:
                # date.weekday(): Monday is 0; the grid puts Sunday first.
                self._totals[(day.day.weekday() + 1) % 7] += day.count
        self._font = T.font(ui_family, T.CAPTION)
        self._mono = T.font(mono_family, T.CAPTION)
        step = Heatmap.CELL + Heatmap.GAP
        self.setFixedHeight(Heatmap.TOP + 7 * step - Heatmap.GAP)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        peak = max(self._totals) or 1
        step = Heatmap.CELL + Heatmap.GAP
        track = self.width() - self.LABEL - self.VALUE - 8
        painter.setFont(self._font)
        painter.setPen(QColor(T.MUTED))
        painter.drawText(
            QRectF(self.LABEL, 0, track, Heatmap.TOP - 2),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
            "By weekday",
        )
        for index, total in enumerate(self._totals):
            y = Heatmap.TOP + index * step
            row = QRectF(0, y, self.width(), Heatmap.CELL)
            share = total / peak
            painter.setFont(self._font)
            painter.setPen(QColor(T.MUTED))
            painter.drawText(
                QRectF(0, y - 2, self.LABEL - 6, Heatmap.CELL + 4),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                _WEEKDAYS[index],
            )
            painter.fillRect(
                QRectF(self.LABEL, row.top() + 3, track, 4), QColor(T.HEAT[0])
            )
            if total:
                colour = T.HEAT[
                    min(len(T.HEAT) - 1, 1 + int(share * (len(T.HEAT) - 1)))
                ]
                painter.fillRect(
                    QRectF(self.LABEL, row.top() + 3, max(2.0, track * share), 4),
                    QColor(colour),
                )
            painter.setFont(self._mono)
            painter.setPen(QColor(T.TEXT if total == peak else T.SUBTLE))
            painter.drawText(
                QRectF(self.width() - self.VALUE, y - 2, self.VALUE, Heatmap.CELL + 4),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                compact(total),
            )


class MonthChart(AreaChart):
    """Contributions per month of one year; months still ahead stay blank."""

    def __init__(
        self, view: YearView, today: date, ui_family: str, mono_family: str
    ) -> None:
        super().__init__(ui_family, mono_family, T.FOAM)
        self._today = today
        self.totals = [0] * 12
        self.set_view(view)

    def set_view(self, view: YearView) -> None:
        self.totals = [0] * 12
        for day in view.days:
            if day.count > 0 and day.day.year == view.year:
                self.totals[day.day.month - 1] += day.count
        values: list[int | None] = [
            None
            if view.year == self._today.year and month + 1 > self._today.month
            else total
            for month, total in enumerate(self.totals)
        ]
        self.set_points(list(_MONTHS), values)


class YearChart(AreaChart):
    """Contributions per year; click a year to show it above."""

    year_chosen = Signal(int)

    def __init__(
        self, totals: dict[int, int], selected: int, ui_family: str, mono_family: str
    ) -> None:
        super().__init__(ui_family, mono_family, T.PINE, clickable=True)
        self.years = sorted(totals)
        self.set_points(
            [str(year) for year in self.years],
            [totals[year] for year in self.years],
            self.years.index(selected) if selected in self.years else -1,
        )
        self.point_clicked.connect(
            lambda index: self.year_chosen.emit(self.years[index])
        )

    def select_year(self, year: int) -> None:
        if year in self.years:
            self.set_selected(self.years.index(year))


class ContributionsPage(QWidget):
    def __init__(
        self, state: DashboardState, fonts: T.Fonts, today: date | None = None
    ) -> None:
        super().__init__()
        self._state = state
        self._fonts = fonts
        self._today = today or datetime.now().astimezone().date()
        user = state.user
        years = contribution_years(state)
        totals = {year: user.annual_totals.get(year, 0) for year in years}
        best = max(totals.items(), key=lambda item: item[1]) if totals else None
        current = (
            self._today.year
            if self._today.year in totals
            else (years[-1] if years else self._today.year)
        )

        strip = StatStrip()
        strip.add(
            "All time",
            compact(user.calendar_total),
            f"since {years[0]}" if years else "",
        )
        strip.add("Commit contributions", compact(user.commits))
        strip.add("Pull requests", compact(user.pull_requests))
        strip.add(
            "Best year",
            str(best[0]) if best else "-",
            f"{compact(best[1])} contributions" if best else "",
        )

        years_card = Card("Years", "click a year to see it day by day", fill=True)
        self.years_chart = YearChart(totals, current, fonts.ui, fonts.mono)
        years_card.add(self.years_chart)
        self.months_card = Card("By month", "", fill=True)
        self.months = MonthChart(
            year_view(state, current, self._today), self._today, fonts.ui, fonts.mono
        )
        self.months_card.add(self.months)
        charts = QHBoxLayout()
        charts.setSpacing(T.GAP)
        charts.addWidget(years_card, 1)
        charts.addWidget(self.months_card, 1)

        self.year_card = Card("")
        self._year_body: QWidget | None = None
        self.years_chart.year_chosen.connect(self.show_year)

        page = QVBoxLayout(self)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        page.setSpacing(T.GAP)
        page.addLayout(
            page_header(
                "Contributions",
                f"GitHub contribution calendar for {user.login or 'you'}",
            )
        )
        page.addWidget(strip)
        page.addWidget(self.year_card)
        page.addLayout(charts, 1)
        self.show_year(current)

    def show_year(self, year: int) -> None:
        view = year_view(self._state, year, self._today)
        self.current_year = year
        self._render_year(view)

    def _render_year(self, view: YearView) -> None:
        self.year_card.title.setText(str(view.year))
        self.year_card.meta.setText(f"{view.total:,} contributions")
        self.months_card.title.setText(f"{view.year} by month")
        self.months.set_view(view)
        self.years_chart.select_year(view.year)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        if self._year_body is None:
            self.year_card.add(body)
        else:
            _ = self.year_card.body.replaceWidget(self._year_body, body)
            self._year_body.deleteLater()
        self._year_body = body
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        grid = QVBoxLayout()
        grid.setSpacing(6)
        grid.addWidget(Heatmap(view.days, self._fonts.ui, self._today))
        grid.addWidget(Legend(self._fonts.ui), 0, Qt.AlignmentFlag.AlignRight)
        row.addLayout(grid)
        weekdays = QVBoxLayout()
        weekdays.setSpacing(0)
        weekdays.addWidget(WeekdayBars(view, self._fonts.ui, self._fonts.mono))
        weekdays.addStretch(1)
        row.addLayout(weekdays, 1)
        row.addWidget(divider(vertical=True))
        summary = QVBoxLayout()
        summary.setSpacing(8)
        best = view.summary.best_day
        for caption, value in (
            ("Active days", f"{view.summary.active_days}"),
            (
                "Best day",
                f"{best.count} · {best.day.strftime('%d %b')}" if best else "-",
            ),
            ("Per active day", f"{view.summary.average_active:.1f}"),
        ):
            pair = QVBoxLayout()
            pair.setSpacing(0)
            pair.addWidget(label(caption, "StatLabel"))
            pair.addWidget(label(value, "Mono"))
            summary.addLayout(pair)
        summary.addStretch(1)
        row.addLayout(summary)
