from datetime import date
from pathlib import Path

from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine
from echohub.insights import (
    PADDING,
    commit_ledger,
    contribution_years,
    language_fingerprint,
    release_coverage,
    year_view,
)
from echohub.models import Commit, ContributionDay, DashboardState, Project, Release


def demo_state(tmp_path: Path) -> DashboardState:
    return EchopointEngine(DashboardConfig(cache_dir=tmp_path)).install_demo(
        demo_store()
    )


def test_year_view_pads_to_sunday_and_stops_today(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.user.contribution_days = [
        ContributionDay("2026-01-01", 3),
        ContributionDay("2026-01-02", 5),
        ContributionDay("2025-12-31", 99),
    ]
    view = year_view(state, 2026, date(2026, 1, 10))
    padding = [day for day in view.days if day.count == PADDING]
    assert len(padding) == 4, "1 Jan 2026 is a Thursday"
    assert view.days[0].day.weekday() == 6
    assert view.days[-1].day == date(2026, 1, 10)
    assert view.total == 8, "days from the year before do not count"
    assert view.summary.active_days == 2


def test_contribution_years_merge_totals_and_days(tmp_path: Path) -> None:
    state = demo_state(tmp_path)
    state.user.annual_totals = {2019: 4}
    state.user.contribution_days = [ContributionDay("2021-05-01", 1)]
    assert contribution_years(state) == [2019, 2021]


def test_fingerprint_ranks_languages_and_skips_prose_repos() -> None:
    projects = [
        Project(alias="big", languages={"Rust": 900, "Go": 100}),
        Project(alias="small", languages={"Go": 50}),
        Project(alias="notes", languages={}),
    ]
    fingerprint = language_fingerprint(projects, limit=1)
    assert fingerprint.languages == ["Rust"]
    assert [row.alias for row in fingerprint.rows] == ["big", "small"]
    assert fingerprint.rows[0].shares == {"Rust": 0.9}
    assert fingerprint.rows[1].shares == {}


def test_release_coverage_puts_newest_releases_first() -> None:
    projects = [
        Project(alias="zeta"),
        Project(
            alias="old",
            latest_release=Release(tag="v1", published_at="2025-01-01T00:00:00Z"),
        ),
        Project(
            alias="new",
            latest_release=Release(tag="v2", published_at="2026-01-01T00:00:00Z"),
        ),
        Project(alias="alpha"),
    ]
    assert [row.alias for row in release_coverage(projects)] == [
        "new",
        "old",
        "alpha",
        "zeta",
    ]


def test_commit_ledger_is_newest_first_across_repos() -> None:
    projects = [
        Project(alias="a", commits=[Commit(sha="1" * 40, date="2026-01-01T00:00:00Z")]),
        Project(
            alias="b",
            private=True,
            commits=[Commit(sha="2" * 40, date="2026-02-01T00:00:00Z")],
        ),
    ]
    ledger = commit_ledger(projects)
    assert [(row.alias, row.sha, row.private) for row in ledger] == [
        ("b", "2222222", True),
        ("a", "1111111", False),
    ]
