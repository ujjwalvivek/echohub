"""Sources: package registries, status checks and release coverage.

One dashboard with no tabs, like the desktop page: a strip, then registries
and the release cadence beside status checks and release coverage. The
tables are short, so they show every row and the page scrolls.
"""

from __future__ import annotations

from collections import Counter

from .... import palette as P
from ....formatting import compact, human_bytes, relative_time
from ....insights import (
    CADENCE_MONTHS,
    RegistryRow,
    ReleaseCoverage,
    registry_rows,
    release_cadence,
    release_coverage,
)
from ....models import DashboardState, StatusCheck
from ..style import hjoin, paint
from ..table import Column, Table
from ..widgets import Stat, column_chart, hbar, page_title, section, stat_strip
from .base import Context, ScrollPage

SIDE_FROM = 130


def _count(value: int | None) -> str:
    return compact(value) if value is not None else ""


REGISTRY_COLUMNS: list[Column[RegistryRow]] = [
    Column("Registry", lambda r: r.registry, width=8, kind="pill"),
    Column("Package", lambda r: r.name, width=14, stretch=True, kind="strong"),
    Column("Version", lambda r: r.version, width=10, kind="pill"),
    Column("Downloads", lambda r: _count(r.downloads), width=9, kind="number", drop=3),
    Column(
        "Recent",
        lambda r: (
            f"{_count(r.recent)} / {r.recent_period}" if r.recent is not None else ""
        ),
        width=14,
        kind="number",
        drop=2,
    ),
    Column(
        "Size",
        lambda r: human_bytes(r.size) if r.size else "",
        width=8,
        kind="number",
        drop=4,
    ),
    Column(
        "Updated",
        lambda r: relative_time(r.updated) if r.updated else "",
        width=8,
        kind="age",
        stamp=lambda r: r.updated,
        drop=1,
    ),
    Column("License", lambda r: r.license, width=8, kind="muted", drop=5),
]


def _state_tone(check: StatusCheck) -> str:
    return P.SUCCESS if check.ok else P.ERROR


STATUS_COLUMNS: list[Column[StatusCheck]] = [
    Column("", lambda _c: "", width=1, kind="dot", tone=_state_tone),
    Column(
        "Check", lambda c: c.label or c.alias, width=14, stretch=True, kind="strong"
    ),
    Column("State", lambda c: c.state, width=7, tone=_state_tone),
    Column(
        "Latency",
        lambda c: f"{c.latency_ms:.0f} ms" if c.latency_ms is not None else "",
        width=8,
        kind="number",
        drop=2,
    ),
    Column(
        "Checked",
        lambda c: relative_time(c.checked_at) if c.checked_at else "",
        width=8,
        kind="age",
        stamp=lambda c: c.checked_at,
        drop=1,
    ),
]

RELEASE_COLUMNS: list[Column[ReleaseCoverage]] = [
    Column(
        "Project",
        lambda r: r.alias,
        width=14,
        stretch=True,
        kind="strong",
        flag=lambda r: r.private,
    ),
    Column("Latest release", lambda r: r.latest_tag, width=14, kind="pill"),
    Column(
        "Published",
        lambda r: relative_time(r.published_at) if r.published_at else "",
        width=9,
        kind="age",
        stamp=lambda r: r.published_at,
    ),
    Column(
        "Releases",
        lambda r: str(r.releases),
        width=3,
        kind="bar",
        value=lambda r: r.releases,
        drop=2,
    ),
    Column("Tags", lambda r: str(r.tags), width=4, kind="number", drop=1),
]


class SourcesPage(ScrollPage):
    name = "Sources"

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.registries: Table[RegistryRow] = Table(REGISTRY_COLUMNS, [])
        self.status: Table[StatusCheck] = Table(
            STATUS_COLUMNS, [], empty="No status checks"
        )
        self.releases: Table[ReleaseCoverage] = Table(RELEASE_COLUMNS, [])
        self.stats: list[Stat] = []
        self.cadence: tuple[list[str], list[int]] = ([], [])
        self.coverage: list[ReleaseCoverage] = []

    def set_state(self, state: DashboardState) -> None:
        rows = registry_rows(state)
        self.registries.set_rows(rows)
        self.status.set_rows(state.statuses)
        self.coverage = release_coverage(state.projects)
        self.releases.set_rows(self.coverage)
        self.cadence = release_cadence(state, months=CADENCE_MONTHS)

        by_registry = Counter(row.registry for row in rows)
        mix = " · ".join(f"{name} {count}" for name, count in by_registry.most_common())
        downloads = sum(row.downloads or 0 for row in rows)
        counted = sum(1 for row in rows if row.downloads is not None)
        up = sum(1 for check in state.statuses if check.ok)
        latencies = [c.latency_ms for c in state.statuses if c.latency_ms is not None]
        released = [row for row in self.coverage if row.latest_tag]
        newest = max((row.published_at for row in released), default="")
        self.stats = [
            Stat("Packages", str(len(rows)), mix or "none published"),
            Stat(
                "Downloads",
                compact(downloads) if counted else "-",
                f"all time · {counted} report them" if counted else "not reported",
            ),
            Stat(
                "Status",
                f"{up} of {len(state.statuses)} up" if state.statuses else "-",
                f"{sum(latencies) / len(latencies):.0f} ms average"
                if latencies
                else "no checks configured",
                P.FOAM if state.statuses and up == len(state.statuses) else P.GOLD,
            ),
            Stat(
                "Release coverage",
                f"{len(released)} of {len(self.coverage)}",
                f"latest {relative_time(newest)}" if newest else "no releases yet",
            ),
        ]

    def content(self, cells: int, rows: int) -> list[str]:
        lines = [
            page_title(
                "Sources", "Where your packages live, what's up, what's released", cells
            ),
            "",
        ]
        lines += stat_strip(self.stats, cells)
        lines.append("")
        if cells >= SIDE_FROM:
            main = cells * 3 // 5
            side = cells - main - 3
            right = self._status(side) + [""] + self._coverage(side)
            left = self._registries(main) + [""]
            chart_rows = max(8, len(right) - len(left), rows - len(lines) - len(left))
            left += self._cadence(main, chart_rows)
            return lines + hjoin((left, main), (right, side), gap=3)
        return (
            lines
            + self._registries(cells)
            + [""]
            + self._status(cells)
            + [""]
            + self._coverage(cells)
            + [""]
            + self._cadence(cells, 10)
        )

    def _registries(self, cells: int) -> list[str]:
        table = self.registries
        return [
            section("Registries", f"{len(table.rows)} packages", cells)
        ] + table.render(cells, max(2, len(table.view) + 1), select=False)

    def _status(self, cells: int) -> list[str]:
        table = self.status
        return [
            section("Status checks", f"{len(table.rows)} checks", cells)
        ] + table.render(cells, max(2, len(table.view) + 1), select=False)

    def _coverage(self, cells: int) -> list[str]:
        released = sum(1 for row in self.coverage if row.latest_tag)
        total = len(self.coverage)
        share = released / total if total else 0.0
        lines = [
            section(
                "Release coverage", f"{released} of {total} repos have a release", cells
            ),
            hbar(share, cells - 6, P.FOAM) + paint(f"{share:.0%}".rjust(6), P.SUBTLE),
        ]
        table = self.releases
        return lines + table.render(cells, max(2, len(table.view) + 1), select=False)

    def _cadence(self, cells: int, rows: int) -> list[str]:
        labels, counts = self.cadence
        values: list[int | None] = list(counts)
        return [
            section(
                "Release cadence",
                f"{sum(counts)} releases in {CADENCE_MONTHS} months, all repos",
                cells,
            )
        ] + column_chart(values, labels, cells, rows - 1, P.IRIS)
