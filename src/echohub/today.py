"""What the Today page shows, derived from a DashboardState.

No UI code lives here, so the numbers can be tested directly and any renderer
can present them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from .models import DashboardState, PackageArtifact, Project
from .types import as_int, as_str

# How old the snapshot may get before it is worth pointing out. Echopoint's
# cron runs hourly, so a few hours means refreshes are not landing.
STALE_AFTER = timedelta(hours=3)
ACTIVITY_WINDOW = timedelta(days=7)
RELEASE_WINDOW = timedelta(days=30)
HEATMAP_WEEKS = 53


@dataclass(slots=True)
class Streak:
    current: int = 0
    longest: int = 0
    # False when the streak is still alive but today has no contribution yet.
    active_today: bool = False


@dataclass(slots=True)
class ProjectActivity:
    alias: str
    commits: int
    latest_message: str
    latest_date: str
    additions: int
    deletions: int
    private: bool = False


@dataclass(slots=True)
class AutomatedActivity:
    alias: str
    commits: int


@dataclass(slots=True)
class RecentRelease:
    alias: str
    tag: str
    published_at: str
    url: str = ""


@dataclass(slots=True)
class Attention:
    level: str  # "error" or "warning"
    title: str
    detail: str = ""


@dataclass(slots=True)
class PackageLine:
    ecosystem: str
    name: str
    version: str
    updated_at: str = ""
    recent_downloads: int | None = None
    # The window recent_downloads covers: npm reports a month, crates.io 90 days.
    downloads_period: str = ""


_DOWNLOAD_PERIODS = {"npm": "mo", "crates": "90d"}


@dataclass(slots=True)
class HeatmapDay:
    day: date
    count: int


@dataclass(slots=True)
class YearSummary:
    active_days: int = 0
    best_day: HeatmapDay | None = None
    # Mean over days with at least one contribution.
    average_active: float = 0.0


def year_summary(days: list[HeatmapDay]) -> YearSummary:
    active = [day for day in days if day.count > 0]
    if not active:
        return YearSummary()
    best = max(active, key=lambda day: (day.count, day.day))
    return YearSummary(
        active_days=len(active),
        best_day=best,
        average_active=sum(day.count for day in active) / len(active),
    )


@dataclass(slots=True)
class TodayView:
    today: date
    streak: Streak
    today_total: int
    week_total: int
    previous_week_total: int
    year_total: int
    active_repos: int
    heatmap: list[HeatmapDay] = field(default_factory=list)
    year: YearSummary = field(default_factory=YearSummary)
    activity: list[ProjectActivity] = field(default_factory=list)
    automated: list[AutomatedActivity] = field(default_factory=list)
    releases: list[RecentRelease] = field(default_factory=list)
    attention: list[Attention] = field(default_factory=list)
    packages: list[PackageLine] = field(default_factory=list)
    snapshot_updated: str = ""


def _parse_instant(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _streak(counts: dict[date, int], today: date) -> Streak:
    if not counts:
        return Streak()
    active_today = counts.get(today, 0) > 0
    # Before today's first contribution, yesterday still carries the streak.
    cursor = today if active_today else today - timedelta(days=1)
    current = 0
    while counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous: date | None = None
    for day in sorted(counts):
        if counts[day] <= 0:
            run = 0
        elif previous is not None and day - previous == timedelta(days=1) and run:
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        previous = day
    return Streak(
        current=current, longest=max(longest, current), active_today=active_today
    )


def _heatmap(counts: dict[date, int], today: date) -> list[HeatmapDay]:
    # Columns are Sunday-to-Saturday weeks, like GitHub, ending with today.
    days_since_sunday = (today.weekday() + 1) % 7
    start = today - timedelta(days=days_since_sunday + 7 * (HEATMAP_WEEKS - 1))
    span = (today - start).days + 1
    return [
        HeatmapDay(day, counts.get(day, 0))
        for day in (start + timedelta(days=offset) for offset in range(span))
    ]


def _activity(
    projects: list[Project], now: datetime
) -> tuple[list[ProjectActivity], list[AutomatedActivity]]:
    since = now - ACTIVITY_WINDOW
    human: list[ProjectActivity] = []
    automated: dict[str, int] = defaultdict(int)
    for project in projects:
        recent = [
            commit
            for commit in project.commits
            if (when := _parse_instant(commit.date)) is not None and when >= since
        ]
        for commit in recent:
            if commit.automated:
                automated[project.alias] += 1
        mine = [commit for commit in recent if not commit.automated]
        if not mine:
            continue
        latest = max(mine, key=lambda commit: commit.date)
        human.append(
            ProjectActivity(
                alias=project.alias,
                commits=len(mine),
                latest_message=latest.message,
                latest_date=latest.date,
                additions=sum(commit.additions for commit in mine),
                deletions=sum(commit.deletions for commit in mine),
                private=project.private,
            )
        )
    human.sort(key=lambda item: item.latest_date, reverse=True)
    folded = [
        AutomatedActivity(alias, count) for alias, count in sorted(automated.items())
    ]
    return human, folded


def _releases(projects: list[Project], now: datetime) -> list[RecentRelease]:
    since = now - RELEASE_WINDOW
    seen: set[tuple[str, str]] = set()
    result: list[RecentRelease] = []
    for project in projects:
        candidates = list(project.releases)
        if project.latest_release is not None:
            candidates.append(project.latest_release)
        for release in candidates:
            when = _parse_instant(release.published_at)
            key = (project.alias, release.tag)
            if when is None or when < since or release.draft or key in seen:
                continue
            seen.add(key)
            result.append(
                RecentRelease(
                    project.alias, release.tag, release.published_at, release.url
                )
            )
    result.sort(key=lambda item: item.published_at, reverse=True)
    return result


def _attention(state: DashboardState, now: datetime) -> list[Attention]:
    items: list[Attention] = []
    for check in state.statuses:
        if not check.ok:
            detail = check.error or (f"HTTP {check.status}" if check.status else "")
            items.append(
                Attention("error", f"{check.label or check.alias} is down", detail)
            )
    failures = state.meta.collector_failures
    if failures:
        keys = ", ".join(
            as_str(failure.get("key"))
            + (f" (HTTP {status})" if (status := as_int(failure.get("status"))) else "")
            for failure in failures[:3]
        )
        more = f" and {len(failures) - 3} more" if len(failures) > 3 else ""
        items.append(
            Attention(
                "warning",
                f"Echopoint could not refresh {len(failures)} "
                + ("source" if len(failures) == 1 else "sources"),
                keys + more,
            )
        )
    updated = _parse_instant(state.meta.last_updated)
    if updated is not None and now - updated > STALE_AFTER:
        hours = int((now - updated).total_seconds() // 3600)
        items.append(
            Attention("warning", f"Data is {hours}h old", "Refresh to catch up.")
        )
    queued = as_int(state.meta.last_run.get("budget_skipped"))
    if queued > 0:
        items.append(
            Attention(
                "warning",
                f"{queued} sources are waiting on Echopoint",
                "The last run ran out of fetch budget; refresh to drain the queue.",
            )
        )
    return items


def _package(item: PackageArtifact) -> PackageLine:
    return PackageLine(
        item.ecosystem,
        item.name,
        item.version,
        item.updated_at,
        item.recent_downloads,
        _DOWNLOAD_PERIODS.get(item.ecosystem, ""),
    )


def package_lines(state: DashboardState) -> list[PackageLine]:
    """Every published artifact, registries first, as display lines."""
    return [_package(item) for item in (*state.npm, *state.crates, *state.pypi)] + [
        PackageLine("docker", image.alias, image.latest_tag, image.latest_updated_at)
        for image in state.docker
    ]


def contribution_counts(state: DashboardState) -> dict[date, int]:
    counts: dict[date, int] = {}
    for entry in state.user.contribution_days:
        day = _parse_day(entry.date)
        if day is not None:
            counts[day] = max(0, entry.count)
    return counts


def build_today(state: DashboardState, now: datetime | None = None) -> TodayView:
    moment = now or datetime.now().astimezone()
    today = moment.date()
    counts = contribution_counts(state)

    def total(first: date, last: date) -> int:
        return sum(count for day, count in counts.items() if first <= day <= last)

    activity, automated = _activity(state.projects, moment)
    heatmap = _heatmap(counts, today)
    packages = package_lines(state)
    return TodayView(
        today=today,
        streak=_streak(counts, today),
        today_total=counts.get(today, 0),
        week_total=total(today - timedelta(days=6), today),
        previous_week_total=total(
            today - timedelta(days=13), today - timedelta(days=7)
        ),
        year_total=sum(day.count for day in heatmap),
        active_repos=len(activity),
        heatmap=heatmap,
        year=year_summary(heatmap),
        activity=activity,
        automated=automated,
        releases=_releases(state.projects, moment),
        attention=_attention(state, moment),
        packages=packages,
        snapshot_updated=state.meta.last_updated,
    )
