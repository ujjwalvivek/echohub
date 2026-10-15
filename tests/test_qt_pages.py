import os
from pathlib import Path

import pytest

# Render without a display (CI, headless); must be set before Qt starts.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine
from echohub.models import Project
from echohub.renderers.qt import theme as T
from echohub.renderers.qt.app import PAGE_NAMES, MainWindow, create_app
from echohub.renderers.qt.pages.activity import ActivityPage
from echohub.renderers.qt.pages.constellation import ConstellationPage
from echohub.renderers.qt.pages.contributions import ContributionsPage
from echohub.renderers.qt.pages.inspector import InspectorPage
from echohub.renderers.qt.pages.projects import ProjectsPage
from echohub.renderers.qt.pages.sources import SourcesPage
from echohub.renderers.qt.table import Column, RecordTable

AppFonts = tuple[QApplication, T.Fonts]


@pytest.fixture
def app_fonts() -> AppFonts:
    return create_app()


@pytest.fixture
def engine(tmp_path: Path) -> EchopointEngine:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(demo_store())
    return engine


def test_every_page_builds_and_navigation_tracks_it(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    app, fonts = app_fonts
    window = MainWindow(engine, fonts)
    try:
        for name in PAGE_NAMES:
            page = window.page(name)
            assert window.pages.currentWidget() is page
            assert window.nav_buttons[name].isChecked()
            assert window.title_bar.page.text().endswith(name)
        window.show_page("Projects")
        assert window.page("Projects") is window.page("Projects"), "built once"
        window._render()  # pyright: ignore[reportPrivateUsage]
        assert window.current_page == "Projects", "a refresh keeps the open view"
    finally:
        window.deleteLater()
        app.processEvents()


def test_table_hides_empty_columns_filters_and_selects(app_fonts: AppFonts) -> None:
    _, fonts = app_fonts
    rows = [Project(alias="alpha"), Project(alias="beta")]
    columns: list[Column[Project]] = [
        Column("Name", lambda p: p.alias),
        Column("Stars", lambda p: p.stars, numeric=True, hide_if_empty=True),
    ]
    table: RecordTable[Project] = RecordTable(columns, rows, fonts)
    assert table.visible_titles == ["Name"]
    picked: list[object] = []
    table.selected.connect(picked.append)
    table.set_filter("bet")
    assert table.row_count() == 1
    table.select_first()
    assert picked == [rows[1]]
    table.set_filter("")
    table.set_predicate(lambda p: p.alias.startswith("a"))
    assert table.row_count() == 1
    assert table.row_at(0).alias == "alpha"


def test_table_cells_size_for_their_kind(app_fonts: AppFonts) -> None:
    from PySide6.QtWidgets import QStyleOptionViewItem

    _, fonts = app_fonts
    rows = [
        Project(alias="alpha", private=True),
        Project(alias="alpha", commit_count=40),
    ]
    columns: list[Column[Project]] = [
        Column("Name", lambda p: p.alias, kind="strong", flag=lambda p: p.private),
        Column("Commits", lambda p: p.commit_count, numeric=True, kind="bar"),
    ]
    table: RecordTable[Project] = RecordTable(columns, rows, fonts)
    delegate = table.itemDelegate()
    option = QStyleOptionViewItem()
    model = table.model()
    locked = delegate.sizeHint(option, model.index(0, 0)).width()
    plain = delegate.sizeHint(option, model.index(1, 0)).width()
    assert locked > plain, "the padlock takes room before a private name"
    bar = delegate.sizeHint(option, model.index(1, 1)).width()
    assert bar > 40, "bar cells reserve the inline track"
    table.set_filter("nothing-matches-this")
    assert table.row_count() == 0


def test_diff_column_scales_to_the_biggest_side(app_fonts: AppFonts) -> None:
    from echohub.renderers.qt.table import _peak  # pyright: ignore[reportPrivateUsage]

    column: Column[tuple[int, int]] = Column(
        "Changes", lambda r: r[0] + r[1], kind="diff", pair=lambda r: r
    )
    assert _peak(column, [(3, 40), (900, 2)]) == 900
    assert column.style == "diff"


def test_nav_shows_counts_and_status_bar_keys(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    from PySide6.QtWidgets import QLabel

    app, fonts = app_fonts
    window = MainWindow(engine, fonts)
    try:
        assert window.nav_buttons["Projects"].count == str(len(engine.state.projects))
        assert window.nav_buttons["Today"].count == ""
        keys = [
            w.text() for w in window.findChildren(QLabel) if w.objectName() == "Key"
        ]
        assert keys == ["1–8", "R", "C"]
        window._on_failed("boom")  # pyright: ignore[reportPrivateUsage]
        assert window.state_mark.state == "failed"
    finally:
        window.deleteLater()
        app.processEvents()


def test_month_bars_add_up_to_the_year(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    from echohub.renderers.qt.pages.contributions import MonthChart

    _, fonts = app_fonts
    page = ContributionsPage(engine.state, fonts)
    bars = page.findChildren(MonthChart)
    assert len(bars) == 1
    from echohub.insights import year_view

    totals = bars[0].totals
    view = year_view(engine.state, page.current_year, page._today)  # pyright: ignore[reportPrivateUsage]
    assert sum(totals) == sum(day.count for day in view.days if day.count > 0)
    assert len(totals) == 12


def test_projects_filter(app_fonts: AppFonts, engine: EchopointEngine) -> None:
    _, fonts = app_fonts
    state = engine.state
    page = ProjectsPage(state, fonts)
    assert page.table.row_count() == len(state.projects)
    page.filter.setText("echopoint")
    assert page.table.row_count() == 1
    assert "Forks" not in page.table.visible_titles


def test_activity_hides_automated_until_asked(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    _, fonts = app_fonts
    state = engine.state
    state.projects[0].commits[0].automated = True
    total = sum(len(project.commits) for project in state.projects)
    page = ActivityPage(state, fonts)
    assert page.table.row_count() == total - 1
    page.show_automated.setChecked(True)
    assert page.table.row_count() == total


def test_contributions_switch_years(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    _, fonts = app_fonts
    page = ContributionsPage(engine.state, fonts)
    years = sorted(engine.state.user.annual_totals)
    page.show_year(years[0])
    assert page.current_year == years[0]
    assert page.year_card.title.text() == str(years[0])


def test_sources_tabs_and_constellation_selection(
    app_fonts: AppFonts, engine: EchopointEngine
) -> None:
    _, fonts = app_fonts
    state = engine.state
    sources = SourcesPage(state, fonts)
    packages = len(state.npm) + len(state.crates) + len(state.pypi) + len(state.docker)
    assert sources.registries.row_count() == packages
    assert sources.status.row_count() == len(state.statuses)

    page = ConstellationPage(state, fonts)
    alias = state.projects[0].alias
    page.view.select(alias)
    page.view.selected.emit(alias)
    assert page.view.selected_alias == alias
    assert page.detail.widget() is not None

    view = page.view
    view.resize(800, 600)
    view.settle()
    assert view.layout_.settled
    # Selecting lights the repo and its languages; everything else dims.
    lit = {alias} | view.graph.neighbours(alias)
    for node in view.graph.nodes:
        assert view._fade[node.id] == (1.0 if node.id in lit else 0.12)  # pyright: ignore[reportPrivateUsage]
    view.select("")
    view.set_query("rust")
    view.settle()
    rust = view.graph.node("lang:Rust")
    if rust is not None:
        assert view._fade[rust.id] == 1.0  # pyright: ignore[reportPrivateUsage]


def test_inspector_filters_keys(app_fonts: AppFonts, engine: EchopointEngine) -> None:
    _, fonts = app_fonts
    page = InspectorPage(engine.raw_store, fonts)
    everything = page.visible_keys()
    assert sorted(everything) == sorted(engine.raw_store)
    page.filter.setText("npm:")
    shown = page.visible_keys()
    assert shown
    assert all("npm:" in key for key in shown)
    page.show_key(shown[0])
    assert page.current_key == shown[0]
    assert page.text.toPlainText().startswith(("{", "["))
    page.filter.setText("")
    assert len(page.visible_keys()) == len(everything)


def test_series_colours_follow_rank() -> None:
    T.rank_series(["Rust", "Go"])
    assert T.series_color("Rust") == T.SERIES[0]
    assert T.series_color("Go") == T.SERIES[1]
    assert T.series_color("No code") == T.MUTED


def test_release_cadence_counts_by_month(engine: EchopointEngine) -> None:
    from echohub.renderers.qt.pages.sources import release_cadence

    labels, counts = release_cadence(engine.state, months=12)
    assert len(labels) == len(counts) == 12
    assert all(count >= 0 for count in counts)
