"""Data shaping for the Projects, Activity, Languages, Contributions and Sources
views. No UI code, so every number can be tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

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
