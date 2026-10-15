"""Data shaping for the Projects, Activity, Languages, Contributions and Sources
views. No UI code, so every number can be tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from .models import DashboardState, Project
from .today import HeatmapDay, YearSummary, contribution_counts, year_summary

# Days before the year starts that only pad the first grid column to Sunday.
PADDING = -1


@dataclass(slots=True)
class YearView:
    year: int
    days: list[HeatmapDay]
    total: int
    summary: YearSummary


def contribution_years(state: DashboardState) -> list[int]:
    years = set(state.user.annual_totals)
    years.update(day.year for day in contribution_counts(state))
    return sorted(years)


def year_view(state: DashboardState, year: int, today: date) -> YearView:
    """One calendar year as a Sunday-aligned grid; padding days count -1."""
    counts = contribution_counts(state)
    first = date(year, 1, 1)
    last = min(date(year, 12, 31), today)
    lead = (first.weekday() + 1) % 7
    days = [HeatmapDay(first - timedelta(days=lead - i), PADDING) for i in range(lead)]
    cursor = first
    while cursor <= last:
        days.append(HeatmapDay(cursor, counts.get(cursor, 0)))
        cursor += timedelta(days=1)
    real = [day for day in days if day.count >= 0]
    return YearView(
        year=year,
        days=days,
        total=sum(day.count for day in real),
        summary=year_summary(real),
    )


@dataclass(slots=True)
class FingerprintRow:
    alias: str
    private: bool
    code_bytes: int
    shares: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Fingerprint:
    languages: list[str]
    rows: list[FingerprintRow]


def language_fingerprint(projects: list[Project], limit: int = 14) -> Fingerprint:
    """Each repo's language shares across the portfolio's top languages."""
    totals: dict[str, int] = {}
    for project in projects:
        for language, value in project.languages.items():
            totals[language] = totals.get(language, 0) + max(0, value)
    languages = [
        name for name, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ][:limit]
    rows = [
        FingerprintRow(
            alias=project.alias,
            private=project.private,
            code_bytes=project.language_bytes,
            shares={
                language: project.languages.get(language, 0) / project.language_bytes
                for language in languages
                if project.languages.get(language, 0) > 0
            },
        )
        for project in projects
        if project.language_bytes > 0
    ]
    rows.sort(key=lambda row: (-row.code_bytes, row.alias.lower()))
    return Fingerprint(languages, rows)


@dataclass(slots=True)
class ReleaseCoverage:
    alias: str
    private: bool
    latest_tag: str
    published_at: str
    releases: int
    tags: int


def release_coverage(projects: list[Project]) -> list[ReleaseCoverage]:
    rows = [
        ReleaseCoverage(
            alias=project.alias,
            private=project.private,
            latest_tag=project.latest_release.tag if project.latest_release else "",
            published_at=project.latest_release.published_at
            if project.latest_release
            else "",
            releases=len(project.releases),
            tags=len(project.tags),
        )
        for project in projects
    ]
    # Released repos first, newest release on top; the rest alphabetically.
    rows.sort(
        key=lambda row: (
            row.published_at == "",
            _desc(row.published_at),
            row.alias.lower(),
        )
    )
    return rows


def _desc(value: str) -> str:
    # Inverts ISO timestamps so an ascending sort puts the newest first.
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


@dataclass(slots=True)
class LedgerCommit:
    alias: str
    private: bool
    sha: str
    message: str
    author: str
    date: str
    additions: int
    deletions: int
    url: str
    automated: bool


def commit_ledger(projects: list[Project]) -> list[LedgerCommit]:
    """Every cached commit across repos, newest first."""
    rows = [
        LedgerCommit(
            alias=project.alias,
            private=project.private,
            sha=commit.sha[:7],
            message=commit.message,
            author=commit.author,
            date=commit.date,
            additions=commit.additions,
            deletions=commit.deletions,
            url=commit.url,
            automated=commit.automated,
        )
        for project in projects
        for commit in project.commits
    ]
    rows.sort(key=lambda row: row.date, reverse=True)
    return rows


_PERIODS = {"npm": "month", "crates": "90 days"}


@dataclass(slots=True)
class RegistryRow:
    registry: str
    name: str
    version: str
    downloads: int | None
    recent: int | None
    recent_period: str
    size: int | None
    updated: str
    license: str
    url: str


def registry_rows(state: DashboardState) -> list[RegistryRow]:
    rows = [
        RegistryRow(
            item.ecosystem,
            item.name,
            item.version,
            item.downloads,
            item.recent_downloads,
            _PERIODS.get(item.ecosystem, ""),
            item.size_bytes,
            item.updated_at,
            item.license_name,
            item.homepage or item.repository_url,
        )
        for item in (*state.npm, *state.crates, *state.pypi)
    ]
    rows += [
        RegistryRow(
            "docker",
            image.alias,
            image.latest_tag,
            None,
            None,
            "",
            image.latest_size_bytes,
            image.latest_updated_at,
            "",
            "",
        )
        for image in state.docker
    ]
    return rows


CADENCE_MONTHS = 12


def release_cadence(state: DashboardState, months: int) -> tuple[list[str], list[int]]:
    """Releases published per calendar month, oldest first, ending this month."""
    today = datetime.now(UTC).date()
    keys: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    keys.reverse()
    counts = dict.fromkeys(keys, 0)
    for project in state.projects:
        releases = project.releases or (
            [project.latest_release] if project.latest_release else []
        )
        for release in releases:
            stamp = release.published_at[:7]
            if len(stamp) == 7 and stamp[4] == "-":
                key = (int(stamp[:4]), int(stamp[5:7]))
                if key in counts:
                    counts[key] += 1
    labels = [date(y, m, 1).strftime("%b" if m != 1 else "%b %y") for y, m in keys]
    return labels, [counts[key] for key in keys]
