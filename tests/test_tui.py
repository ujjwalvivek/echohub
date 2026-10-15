import json
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from echohub.client import EchopointError
from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine, ProgressUpdate, SyncResult
from echohub.renderers.tui import TuiApp
from echohub.renderers.tui.pages.activity import ActivityPage
from echohub.renderers.tui.pages.constellation import ConstellationPage
from echohub.renderers.tui.pages.inspector import InspectorPage
from echohub.renderers.tui.pages.projects import ProjectsPage
from echohub.renderers.tui.style import clip, plain, width
from echohub.renderers.tui.term import KeyDecoder, windows_key
from echohub.renderers.tui.worker import Done, Progress, Task
from echohub.types import JsonObject

SIZES = [(80, 24), (100, 30), (120, 40), (160, 48), (220, 60)]


@pytest.fixture
def engine(tmp_path: Path) -> EchopointEngine:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(demo_store())
    return engine


def _app(engine: EchopointEngine, opened: list[str] | None = None) -> TuiApp:
    sink = opened if opened is not None else []

    def open_url(url: str) -> bool:
        sink.append(url)
        return True

    return TuiApp(engine, open_url=open_url)


def _text(app: TuiApp, cells: int = 160, rows: int = 48) -> str:
    return "\n".join(plain(line) for line in app.frame(cells, rows))


def _wait(app: TuiApp, timeout: float = 5.0) -> None:
    """Drain the worker until it reports done or failed."""
    task = app.task
    assert task is not None
    task.join(timeout)
    app.poll()


# Drawing -----------------------------------------------------------------------


@pytest.mark.parametrize(("cells", "rows"), SIZES)
def test_every_page_fills_the_screen_exactly(
    engine: EchopointEngine, cells: int, rows: int
) -> None:
    app = _app(engine)
    for index, page in enumerate(app.pages):
        app.current = index
        lines = app.frame(cells, rows)
        assert len(lines) == rows, page.name
        wrong = [n for n, line in enumerate(lines) if width(line) != cells]
        assert not wrong, f"{page.name} {cells}x{rows}: rows {wrong} off width"


def test_pages_keep_the_desktop_order_and_names(engine: EchopointEngine) -> None:
    names = [page.name for page in _app(engine).pages]
    assert names == [
        "Today",
        "Projects",
        "Activity",
        "Languages",
        "Contributions",
        "Sources",
        "Constellation",
        "Inspector",
    ]


def test_chrome_shows_page_source_and_keys(engine: EchopointEngine) -> None:
    text = _text(_app(engine))
    assert "Echohub / Today" in text
    assert "Echopoint · public snapshot" in text
    assert "refresh" in text and "check" in text
    assert "Views" in text and "Developer" in text


def test_narrow_terminal_drops_the_sidebar_for_page_numbers(
    engine: EchopointEngine,
) -> None:
    text = _text(_app(engine), 80, 24)
    assert "Views" not in text
    assert "1 2 3 4 5 6 7 8" in text


def test_labels_are_never_all_caps(engine: EchopointEngine) -> None:
    # Data may be upper case (HTML, MIT); our own words never are.
    data = json.dumps(engine.raw_store)
    app = _app(engine)
    for index in range(len(app.pages)):
        app.current = index
        for line in _text(app).splitlines():
            for word in line.split():
                letters = "".join(c for c in word if c.isalpha())
                if len(letters) > 3 and letters.isupper():
                    assert letters in data or letters in {"JSON", "HTTP"}, word


def test_too_small_terminal_asks_for_room(engine: EchopointEngine) -> None:
    lines = _app(engine).frame(60, 20)
    assert len(lines) == 20
    assert all(width(line) == 60 for line in lines)
    assert "at least 80 × 24" in "\n".join(plain(line) for line in lines)


def test_resizing_between_frames_keeps_every_page_in_bounds(
    engine: EchopointEngine,
) -> None:
    app = _app(engine)
    for index in range(len(app.pages)):
        app.current = index
        for key in ("G", "pgdn", "j"):
            app.handle(key)
        for cells, rows in [(220, 60), (80, 24), (160, 48), (80, 24)]:
            lines = app.frame(cells, rows)
            assert len(lines) == rows
            assert all(width(line) == cells for line in lines)


def test_snapshot_text_cannot_move_the_cursor(engine: EchopointEngine) -> None:
    project = engine.state.projects[0]
    project.commits[0].message = "evil\x1b[2J\x1b]0;title\x07 done\r\nnext"
    project.description = "desc\x1b[31m"
    app = _app(engine)
    for index in range(len(app.pages)):
        app.current = index
        for line in app.frame(160, 48):
            assert "\x1b[2J" not in line
            assert "\x1b]" not in line
            assert "\x07" not in line and "\r" not in line and "\n" not in line


def test_wide_characters_count_two_cells() -> None:
    assert width("日本") == 4
    assert width("á") == 1  # combining accent
    cut = clip("🚀🚀🚀 launch", 5)
    assert width(cut) == 5
    assert plain(cut).endswith("…")


# Keys ----------------------------------------------------------------------------


def test_decoder_reads_arrows_and_navigation_keys() -> None:
    decoder = KeyDecoder()
    keys = decoder.feed(
        "\x1b[A\x1b[B\x1bOC\x1b[1;5D\x1b[5~\x1b[6~\x1b[H\x1b[4~\x1b[Z\x1b[3~"
    )
    assert keys == [
        "up",
        "down",
        "right",
        "left",
        "pgup",
        "pgdn",
        "home",
        "end",
        "backtab",
        "delete",
    ]


def test_decoder_reads_text_and_controls() -> None:
    decoder = KeyDecoder()
    assert decoder.feed("jk/é\r\n\t\x7f\x03") == [
        "j",
        "k",
        "/",
        "é",
        "enter",
        "tab",
        "backspace",
        "ctrl-c",
    ]


def test_decoder_holds_a_lone_escape_until_flushed() -> None:
    decoder = KeyDecoder()
    assert decoder.feed("\x1b") == []
    assert decoder.pending
    assert decoder.flush() == ["esc"]
    assert not decoder.pending


def test_decoder_joins_a_sequence_split_across_reads() -> None:
    decoder = KeyDecoder()
    assert decoder.feed("\x1b[") == []
    assert decoder.feed("6~j") == ["pgdn", "j"]


def test_decoder_reads_escape_then_a_key_as_both() -> None:
    assert KeyDecoder().feed("\x1bq") == ["esc", "q"]


def test_decoder_skips_unknown_sequences() -> None:
    assert KeyDecoder().feed("\x1b[200~x") == ["x"]


def test_windows_special_keys() -> None:
    assert windows_key("\xe0", "H") == "up"
    assert windows_key("\x00", "Q") == "pgdn"
    assert windows_key("\xe0", "?") == ""


def test_number_keys_switch_pages_and_q_quits(engine: EchopointEngine) -> None:
    app = _app(engine)
    app.handle("3")
    assert "Echohub / Activity" in _text(app)
    app.handle("8")
    assert "Echohub / Inspector" in _text(app)
    app.handle("q")
    assert not app.running


def test_help_lists_global_and_page_keys(engine: EchopointEngine) -> None:
    app = _app(engine)
    app.handle("2")
    app.handle("?")
    text = _text(app)
    assert "Everywhere" in text and "Projects" in text
    assert "filter by name" in text
    app.handle("esc")
    assert "Everywhere" not in _text(app)


def test_projects_filter_detail_sort_and_open(engine: EchopointEngine) -> None:
    opened: list[str] = []
    app = _app(engine, opened)
    app.handle("2")
    page = app.page
    assert isinstance(page, ProjectsPage)
    total = len(page.table.view)
    for key in "/voxel":
        app.handle(key)
    assert page.typing
    assert app.running, "q-like letters go to the filter while typing"
    assert [p.alias for p in page.table.view] == ["voxelhalla"]
    app.handle("enter")
    assert not page.typing
    app.handle("enter")
    assert "back to Projects" in _text(app)
    app.handle("o")
    voxel = next(p for p in engine.state.projects if p.alias == "voxelhalla")
    assert opened == [voxel.html_url]
    app.handle("esc")
    assert not page.detail_open
    assert len(page.table.view) == 1, "the first Esc only leaves the details"
    app.handle("esc")
    assert len(page.table.view) == total
    before = page.table.sort_column
    app.handle("s")
    assert page.table.sort_column is not before


def test_activity_toggles_automated_commits(engine: EchopointEngine) -> None:
    project = engine.state.projects[0]
    project.commits[0].automated = True
    app = _app(engine)
    app.handle("3")
    page = app.page
    assert isinstance(page, ActivityPage)
    hidden = len(page.table.view)
    app.handle("a")
    assert len(page.table.view) == hidden + 1


def test_inspector_opens_on_a_key_and_filters(engine: EchopointEngine) -> None:
    app = _app(engine)
    app.handle("8")
    page = app.page
    assert isinstance(page, InspectorPage)
    row = page.selected
    assert row is not None and row.key.startswith("_meta:")
    assert row.key.split(":")[-1] in _text(app)
    for key in "/pypi":
        app.handle(key)
    app.handle("enter")
    assert all("pypi" in row.path for row in page.rows)
    app.handle("tab")
    assert page.pane == 1


@pytest.mark.parametrize(("cells", "rows"), [(160, 48), (80, 24)])
def test_constellation_steps_from_a_language_to_its_repos(
    engine: EchopointEngine, cells: int, rows: int
) -> None:
    opened: list[str] = []
    app = _app(engine, opened)
    app.handle("7")
    page = app.page
    assert isinstance(page, ConstellationPage)
    # No frame first: keys can arrive before the graph was ever drawn.
    app.handle("j")
    app.handle("k")
    hub = page.selected
    assert hub is not None and hub.kind == "language", "languages come first"
    repos = [link.source for link in page.hub_links(hub)]
    assert repos

    app.handle("enter")
    assert page.inside
    text = _text(app, cells, rows)
    assert all(alias in text for alias in repos[: rows // 4])
    if len(repos) > 1:
        app.handle("j")
    picked = repos[min(1, len(repos) - 1)]
    assert page.repo is not None and page.repo.id == picked

    app.handle("enter")
    assert f"back to {hub.label}" in _text(app, cells, rows)
    app.handle("o")
    project = next(p for p in engine.state.projects if p.alias == picked)
    assert opened == [project.html_url]

    app.handle("esc")
    assert page.inside and not page.detail_open, "Esc goes up one level"
    app.handle("esc")
    assert not page.inside
    assert page.selected is hub
    lines = app.frame(cells, rows)
    assert all(width(line) == cells for line in lines)


def test_list_keys_stay_in_range(engine: EchopointEngine) -> None:
    app = _app(engine)
    app.handle("2")
    page = app.page
    assert isinstance(page, ProjectsPage)
    app.handle("G")
    assert page.table.index == len(page.table.view) - 1
    app.handle("j")
    assert page.table.index == len(page.table.view) - 1
    app.handle("g")
    assert page.table.index == 0


# Background work -----------------------------------------------------------------


def test_check_reports_up_to_date(
    engine: EchopointEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sync(*, progress: Callable[[ProgressUpdate], None]) -> SyncResult:
        progress(ProgressUpdate("health", 0.5, "Checking Echopoint"))
        return SyncResult(False, "cache", "", "No change")

    monkeypatch.setattr(engine, "sync", sync)
    app = _app(engine)
    app.check()
    assert app.status.state == "busy"
    _wait(app)
    assert app.status.state == "ready"
    assert app.status.message == "Up to date"
    assert app.task is None


def test_failed_check_keeps_the_saved_snapshot(
    engine: EchopointEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sync(**_kwargs: object) -> SyncResult:
        raise EchopointError("HTTP 503 from /v1/health", status=503)

    monkeypatch.setattr(engine, "sync", sync)
    app = _app(engine)
    app.check()
    _wait(app)
    assert app.status.state == "failed"
    assert app.status.message == "Echopoint had an error · showing the saved snapshot"
    assert "Today" in _text(app)


def test_refresh_without_a_token_explains(engine: EchopointEngine) -> None:
    app = _app(engine)
    app.handle("r")
    assert app.task is None
    assert app.status.message.startswith("Refresh needs a token")


def test_first_run_shows_welcome_until_data_arrives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    app = _app(engine)
    text = _text(app)
    assert "Welcome to Echohub" in text
    assert "not set · public repos only" in text
    app.handle("2")
    assert "Welcome to Echohub" in _text(app), "pages wait for data"

    def failing(**_kwargs: object) -> SyncResult:
        raise OSError("[WinError 10061] connection refused")

    monkeypatch.setattr(engine, "sync", failing)
    app.handle("c")
    _wait(app)
    assert "Can't reach Echopoint" in _text(app)

    def succeed(**_kwargs: object) -> SyncResult:
        return SyncResult(True, "network", "", "Updated")

    monkeypatch.setattr(engine, "sync", succeed)
    _ = engine.install_demo(demo_store())
    app.handle("c")
    _wait(app)
    assert app.welcome is None
    assert "Echohub / Today" in _text(app)


def test_welcome_never_shows_the_token(tmp_path: Path) -> None:
    config = DashboardConfig(cache_dir=tmp_path, refresh_token="s3cret-token")
    text = _text(_app(EchopointEngine(config)))
    assert "s3cret" not in text
    assert "set · private repos included" in text


def test_cancelled_task_stops_at_the_next_step() -> None:
    reached = threading.Event()
    release = threading.Event()
    steps: list[str] = []

    def work(progress: Callable[[ProgressUpdate], None]) -> object:
        progress(ProgressUpdate("a", 0.1, "first"))
        reached.set()
        assert release.wait(5)
        steps.append("before second")
        progress(ProgressUpdate("b", 0.5, "second"))
        steps.append("after second")
        return "done"

    task = Task(work, lambda exc: ("Failed", str(exc)))
    task.start()
    assert reached.wait(5)
    task.cancel()
    release.set()
    task.join(5)
    assert not task.running
    assert steps == ["before second"]
    events = task.drain()
    assert all(isinstance(event, Progress) for event in events)
    assert not any(isinstance(event, Done) for event in events)


def test_quitting_mid_sync_cancels_without_waiting(
    engine: EchopointEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow(*, progress: Callable[[ProgressUpdate], None]) -> SyncResult:
        started.set()
        _ = release.wait(5)  # a request still in flight
        progress(ProgressUpdate("store", 0.5, "late"))
        return SyncResult(True, "network", "", "Updated")

    monkeypatch.setattr(engine, "sync", slow)
    app = _app(engine)
    app.check()
    assert started.wait(5)
    task = app.task
    assert task is not None
    app.handle("q")
    app.cancel_work()
    assert app.task is None
    release.set()
    task.join(5)
    assert not task.running
    assert not any(isinstance(event, Done) for event in task.drain())


def test_store_with_no_data_reports_nothing_matches(tmp_path: Path) -> None:
    store: JsonObject = {"_meta:last_updated": "2026-08-23T04:00:00.000Z"}
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    _ = engine.install_demo(store)
    app = _app(engine)
    for index in range(len(app.pages)):
        app.current = index
        lines = app.frame(100, 30)
        assert len(lines) == 30
        assert all(width(line) == 100 for line in lines)
