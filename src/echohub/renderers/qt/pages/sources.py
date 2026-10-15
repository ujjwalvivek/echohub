"""Sources: package registries, uptime checks and release coverage."""

from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

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
from .. import theme as T
from ..charts import AreaChart
from ..table import Column, RecordTable
from ..widgets import Card, ShareBar, StatStrip, label, page_header
from .detail import open_url


def _count(value: int | None) -> str:
    return compact(value) if value is not None else ""


REGISTRY_COLUMNS: list[Column[RegistryRow]] = [
    Column(
        "Registry",
        lambda r: r.registry,
        width=84,
        kind="pill",
        help="Where the package is published",
    ),
    Column(
        "Package",
        lambda r: r.name.lower(),
        lambda r: r.name,
        stretch=True,
        kind="strong",
        help="Package name",
    ),
    Column(
        "Version",
        lambda r: r.version,
        kind="pill",
        width=90,
        help="Latest published version",
    ),
    Column(
        "Downloads",
        lambda r: r.downloads or 0,
        lambda r: _count(r.downloads),
        numeric=True,
        help="All-time downloads",
    ),
    Column(
        "Recent",
        lambda r: r.recent or 0,
        lambda r: (
            f"{_count(r.recent)} / {r.recent_period}" if r.recent is not None else ""
        ),
        numeric=True,
        help="Downloads in the registry's recent window",
    ),
    Column(
        "Size",
        lambda r: r.size or 0,
        lambda r: human_bytes(r.size) if r.size else "",
        numeric=True,
    ),
    Column(
        "Updated",
        lambda r: r.updated,
        lambda r: relative_time(r.updated) if r.updated else "",
        numeric=True,
        kind="age",
        help="When the latest version was published",
    ),
    Column(
        "License",
        lambda r: r.license,
        width=80,
        kind="muted",
        help="License declared by the package",
    ),
]


def _state_tone(check: StatusCheck) -> str:
    return T.SUCCESS if check.ok else T.ERROR


def _check_tip(check: StatusCheck) -> str:
    lines = [check.label or check.alias, check.url]
    if check.status:
        lines.append(f"HTTP {check.status}")
    if check.error:
        lines.append(check.error)
    return "\n".join(line for line in lines if line)


STATUS_COLUMNS: list[Column[StatusCheck]] = [
    Column(
        "",
        lambda c: c.ok,
        lambda _c: "",
        tone=_state_tone,
        width=28,
        kind="dot",
        help="Up or down at the last check",
    ),
    Column(
        "Check",
        lambda c: c.label or c.alias,
        stretch=True,
        kind="strong",
        tooltip=_check_tip,
        help="Status check name; hover for the address",
    ),
    Column(
        "State",
        lambda c: c.state,
        tone=_state_tone,
        width=70,
        help="Result of the last check",
    ),
    Column(
        "Latency",
        lambda c: c.latency_ms or 0,
        lambda c: f"{c.latency_ms:.0f} ms" if c.latency_ms is not None else "",
        numeric=True,
        help="Response time of the last check",
    ),
    Column(
        "Checked",
        lambda c: c.checked_at,
        lambda c: relative_time(c.checked_at) if c.checked_at else "",
        numeric=True,
        kind="age",
        help="When Echopoint last ran the check",
    ),
]


RELEASE_COLUMNS: list[Column[ReleaseCoverage]] = [
    Column(
        "Project",
        lambda r: r.alias.lower(),
        lambda r: r.alias,
        stretch=True,
        kind="strong",
        flag=lambda r: r.private,
    ),
    Column(
        "Latest release",
        lambda r: r.latest_tag,
        width=150,
        kind="pill",
        help="Most recent GitHub release",
    ),
    Column(
        "Published",
        lambda r: r.published_at,
        lambda r: relative_time(r.published_at) if r.published_at else "",
        numeric=True,
        kind="age",
        help="When that release went out",
    ),
    Column(
        "Releases",
        lambda r: r.releases,
        numeric=True,
        kind="bar",
        help="Number of GitHub releases",
    ),
    Column("Tags", lambda r: r.tags, numeric=True, help="Number of git tags"),
]


class SourcesPage(QWidget):
    def __init__(self, state: DashboardState, fonts: T.Fonts) -> None:
        super().__init__()
        rows = registry_rows(state)
        self.registries: RecordTable[RegistryRow] = RecordTable(
            REGISTRY_COLUMNS, rows, fonts
        )
        self.registries.activated.connect(lambda row: open_url(row.url))
        self.status: RecordTable[StatusCheck] = RecordTable(
            STATUS_COLUMNS, state.statuses, fonts, empty="No status checks"
        )
        self.status.activated.connect(lambda check: open_url(check.url))
        coverage = release_coverage(state.projects)
        self.releases: RecordTable[ReleaseCoverage] = RecordTable(
            RELEASE_COLUMNS, coverage, fonts
        )
        self.releases.sort_by("Published")

        # Headline numbers.
        by_registry = Counter(row.registry for row in rows)
        mix = " · ".join(f"{name} {count}" for name, count in by_registry.most_common())
        downloads = sum(row.downloads or 0 for row in rows)
        counted = sum(1 for row in rows if row.downloads is not None)
        up = sum(1 for check in state.statuses if check.ok)
        latencies = [c.latency_ms for c in state.statuses if c.latency_ms is not None]
        released = [row for row in coverage if row.latest_tag]
        newest = max((row.published_at for row in released), default="")
        strip = StatStrip()
        strip.add("Packages", str(len(rows)), mix or "none published")
        strip.add(
            "Downloads",
            compact(downloads) if counted else "-",
            f"all time · {counted} packages report them" if counted else "not reported",
        )
        strip.add(
            "Status",
            f"{up} of {len(state.statuses)} up" if state.statuses else "-",
            f"{sum(latencies) / len(latencies):.0f} ms average"
            if latencies
            else "no checks configured",
            "Good" if state.statuses and up == len(state.statuses) else "Warn",
        )
        strip.add(
            "Release coverage",
            f"{len(released)} of {len(coverage)}",
            f"latest {relative_time(newest)}" if newest else "no releases yet",
        )

        registries_card = Card("Registries", "double-click opens the package page")
        # Exactly as tall as its rows; the cadence chart takes the rest.
        self.registries.setFixedHeight(28 + 26 * max(1, len(rows)) + 2)
        registries_card.add(self.registries)

        labels, counts = release_cadence(state, months=CADENCE_MONTHS)
        cadence_card = Card(
            "Release cadence",
            f"{sum(counts)} releases in {CADENCE_MONTHS} months, all repos",
            fill=True,
        )
        self.cadence = AreaChart(fonts.ui, fonts.mono, T.IRIS)
        values: list[int | None] = list(counts)
        self.cadence.set_points(labels, values)
        cadence_card.add(self.cadence)

        status_card = Card("Status checks", "double-click opens the address")
        status_rows = max(1, len(state.statuses))
        self.status.setFixedHeight(28 + 26 * status_rows + 2)
        status_card.add(self.status)

        coverage_card = Card(
            "Release coverage",
            f"{len(released)} of {len(coverage)} repos have a release",
            fill=True,
        )
        share = len(released) / len(coverage) if coverage else 0.0
        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        bar_row.addWidget(ShareBar(share, T.FOAM), 1)
        bar_row.addWidget(label(f"{share:.0%}", "Mono"))
        coverage_card.body.addLayout(bar_row)
        coverage_card.body.addSpacing(6)
        coverage_card.add(self.releases)

        side = QVBoxLayout()
        side.setSpacing(T.GAP)
        side.addWidget(status_card)
        side.addWidget(coverage_card, 1)
        body = QHBoxLayout()
        body.setSpacing(T.GAP)
        main = QVBoxLayout()
        main.setSpacing(T.GAP)
        main.addWidget(registries_card)
        main.addWidget(cadence_card, 1)
        body.addLayout(main, 3)
        body.addLayout(side, 2)

        page = QVBoxLayout(self)
        page.setContentsMargins(T.PAGE_X, T.PAGE_Y, T.PAGE_X, T.PAGE_Y)
        page.setSpacing(T.GAP)
        page.addLayout(
            page_header(
                "Sources", "Where your packages live, what's up, what's released"
            )
        )
        page.addWidget(strip)
        page.addLayout(body, 1)
