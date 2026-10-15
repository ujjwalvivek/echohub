from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine
from echohub.models import (
    Commit,
    ContributionDay,
    DashboardState,
    Project,
    Release,
    StatusCheck,
)
from echohub.today import HEATMAP_WEEKS, build_today

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # a Thursday
TODAY = NOW.date()


def demo_state(tmp_path: Path) -> DashboardState:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    return engine.install_demo(demo_store())


def days(*counts: int, end: date = TODAY) -> list[ContributionDay]:
    start = end - timedelta(days=len(counts) - 1)
    return [
        ContributionDay((start + timedelta(days=i)).isoformat(), count)
        for i, count in enumerate(counts)
    ]


def test_streak_survives_until_today_ends(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.user.contribution_days = days(1, 0, 2, 3, 4, 0)  # nothing yet today
    view = build_today(state, NOW)
    assert view.streak.current == 3
    assert not view.streak.active_today
    assert view.streak.longest == 3

    state.user.contribution_days = days(1, 0, 2, 3, 4, 5)
    view = build_today(state, NOW)
    assert view.streak.current == 4
    assert view.streak.active_today
    assert view.today_total == 5


def test_week_totals_and_heatmap_shape(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.user.contribution_days = days(*([2] * 7 + [1] * 7))
    view = build_today(state, NOW)
    assert view.week_total == 7
    assert view.previous_week_total == 14
    assert view.heatmap[0].day.weekday() == 6, "columns start on Sunday"
    assert view.heatmap[-1].day == NOW.date()
    assert len(view.heatmap) == 7 * (HEATMAP_WEEKS - 1) + 5  # Sun..Thu of this week


def test_activity_folds_automation_and_windows_by_week(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    recent = (NOW - timedelta(days=1)).isoformat()
    old = (NOW - timedelta(days=30)).isoformat()
    bot = Project(
        alias="rnd", commits=[Commit(message="log", date=recent, automated=True)] * 3
    )
    mine = Project(
        alias="app",
        private=True,
        commits=[
            Commit(message="feat: new", date=recent, additions=10, deletions=2),
            Commit(message="feat: old", date=old),
        ],
    )
    state.projects = [bot, mine]
    view = build_today(state, NOW)
    assert [(a.alias, a.commits, a.private) for a in view.activity] == [
        ("app", 1, True)
    ]
    assert [(a.alias, a.commits) for a in view.automated] == [("rnd", 3)]


def test_releases_and_attention(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    fresh = Release(tag="v2", published_at=(NOW - timedelta(days=2)).isoformat())
    stale = Release(tag="v1", published_at=(NOW - timedelta(days=90)).isoformat())
    state.projects = [
        Project(alias="app", latest_release=fresh, releases=[fresh, stale])
    ]
    state.statuses = [StatusCheck(alias="site", label="website", ok=False, status=503)]
    state.meta.last_updated = (NOW - timedelta(hours=5)).isoformat()
    state.meta.last_run = {
        "budget_skipped": 4,
        "failures": [
            {"key": "github:x:release", "status": 404},
            {"key": "docker:y:tags", "status": 429},
        ],
    }
    view = build_today(state, NOW)
    assert [(r.alias, r.tag) for r in view.releases] == [("app", "v2")]
    titles = [item.title for item in view.attention]
    assert titles[0] == "website is down"
    assert "Echopoint could not refresh 1 source" in titles
    assert "docker:y:tags (HTTP 429)" in view.attention[1].detail
    assert "Data is 5h old" in titles
    assert "4 sources are waiting on Echopoint" in titles


def test_quiet_state_has_nothing_to_flag(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.statuses = []
    state.meta.last_run = {}
    state.meta.last_updated = NOW.isoformat()
    assert build_today(state, NOW).attention == []


def test_package_download_periods(tmp_path: Path) -> None:
    view = build_today(demo_state(tmp_path), NOW)
    periods = {p.ecosystem: p.downloads_period for p in view.packages}
    assert periods["crates"] == "90d"
    assert periods["npm"] == "mo"


def test_year_summary(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.user.contribution_days = days(0, 3, 9, 0, 3)
    year = build_today(state, NOW).year
    assert year.active_days == 3
    assert year.best_day is not None
    assert (year.best_day.count, year.best_day.day) == (9, TODAY - timedelta(days=2))
    assert year.average_active == 5.0

    state.user.contribution_days = []
    assert build_today(state, NOW).year.best_day is None
