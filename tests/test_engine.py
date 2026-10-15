from pathlib import Path
from typing import final

from echohub.client import Health
from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine, ProgressUpdate
from echohub.types import JsonObject, as_str


class FakeClient:
    def __init__(self, store: JsonObject) -> None:
        self.current = store
        self.lagging_store: JsonObject | None = None
        self.health_calls = 0
        self.store_calls = 0
        self.refresh_calls = 0
        self.private_calls: list[bool] = []

    def health(self) -> Health:
        self.health_calls += 1
        return Health(
            True,
            "echopoint",
            42,
            as_str(self.current.get("_meta:last_updated")),
            "now",
        )

    def store(self, *, private: bool = False) -> JsonObject:
        self.store_calls += 1
        self.private_calls.append(private)
        if self.lagging_store is not None:
            lagging, self.lagging_store = self.lagging_store, None
            return lagging
        return self.current

    def refresh(self) -> JsonObject:
        self.refresh_calls += 1
        newer = dict(self.current)
        newer["_meta:last_updated"] = "2026-08-23T04:10:00.000Z"
        newer["github:echopoint:commit_count"] = {"total": 89}
        self.current = newer
        return {"ok": True}


def make_engine(tmp_path: Path) -> tuple[EchopointEngine, FakeClient]:
    store = demo_store()
    fake = FakeClient(store)
    config = DashboardConfig(cache_dir=tmp_path, base_url="https://example.invalid")
    return EchopointEngine(config, client=fake), fake


def test_store_not_fetched_when_last_updated_is_same(tmp_path: Path) -> None:
    engine, fake = make_engine(tmp_path)
    first = engine.sync()
    assert first.changed
    assert fake.store_calls == 1

    second = engine.sync()
    assert not second.changed
    assert fake.health_calls == 2
    assert fake.store_calls == 1, (
        "the invariant: unchanged health marker must not re-download /v1/store"
    )


def test_changed_marker_fetches_store_once(tmp_path: Path) -> None:
    engine, fake = make_engine(tmp_path)
    _ = engine.sync()
    changed = dict(fake.current)
    changed["_meta:last_updated"] = "2026-08-23T04:01:00.000Z"
    fake.current = changed
    result = engine.sync()
    assert result.changed
    assert fake.store_calls == 2


def test_manual_refresh_calls_echopoint_once_then_syncs(tmp_path: Path) -> None:
    engine, fake = make_engine(tmp_path)
    _ = engine.sync()
    updates: list[ProgressUpdate] = []
    result = engine.refresh(updates.append)
    assert result.changed
    assert fake.refresh_calls == 1
    assert fake.store_calls == 2
    assert engine.state.projects[0]
    assert any(update.progress is None for update in updates), (
        "refresh wait should be explicitly indeterminate"
    )


def test_cache_marker_comes_from_downloaded_store(tmp_path: Path) -> None:
    # If /v1/store lags behind /v1/health (e.g. a cached response), saving the
    # store's own marker means the next sync notices and downloads again,
    # rather than pinning a stale snapshot under a fresh marker.
    engine, fake = make_engine(tmp_path)
    _ = engine.sync()
    fake.lagging_store = dict(fake.current)
    fake.current = dict(fake.current)
    fake.current["_meta:last_updated"] = "2026-09-01T00:00:00.000Z"
    assert engine.sync().changed
    assert engine.sync().changed, "stale download must not be treated as current"
    assert not engine.sync().changed
    assert fake.store_calls == 3
    assert engine.state.meta.last_updated == "2026-09-01T00:00:00.000Z"


def test_private_languages_reach_dashboard_state(tmp_path: Path) -> None:
    store = demo_store()
    store["github:private:ujjwalvivek:langs"] = {"languages": {"Zig": 10_000_000}}
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    state = engine.install_demo(store)
    zig = next(row for row in state.analytics.languages if row.language == "Zig")
    assert zig.private_bytes == 10_000_000
    assert zig.projects == 0
    assert state.analytics.totals["private_language_bytes"] == 10_000_000


def test_state_loads_lazily_from_cache(tmp_path: Path) -> None:
    engine, _fake = make_engine(tmp_path)
    _ = engine.sync()
    fresh = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    assert fresh.state.meta.from_cache
    assert fresh.state.projects


def test_state_without_data_raises(tmp_path: Path) -> None:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    try:
        _ = engine.state
    except RuntimeError as exc:
        assert "sync()" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


@final
class QueueClient(FakeClient):
    """Echopoint with a due backlog larger than one invocation's budget."""

    def __init__(self, store: JsonObject, backlog: int, per_pass: int) -> None:
        super().__init__(store)
        self.backlog = backlog
        self.per_pass = per_pass

    def refresh(self) -> JsonObject:
        self.refresh_calls += 1
        due = self.backlog
        processed = min(self.per_pass, due)
        self.backlog -= processed
        if processed:
            self.current = dict(self.current)
            self.current["_meta:last_updated"] = f"pass-{self.refresh_calls}"
        return {
            "ok": True,
            "due": due,
            "processed": processed,
            "budget_skipped": due - processed,
        }


def test_refresh_drains_the_due_queue_then_syncs_once(tmp_path: Path) -> None:
    fake = QueueClient(demo_store(), backlog=25, per_pass=10)
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path), client=fake)
    updates: list[ProgressUpdate] = []
    result = engine.refresh(updates.append)
    assert fake.refresh_calls == 3
    assert fake.backlog == 0
    assert fake.store_calls == 1, "the snapshot is downloaded once, after draining"
    assert result.last_updated == "pass-3"
    passes = [u for u in updates if u.message.startswith("Echopoint pass")]
    assert [u.message for u in passes] == [
        "Echopoint pass 1: 10 sources refreshed, 15 still queued",
        "Echopoint pass 2: 10 sources refreshed, 5 still queued",
    ]
    fractions = [u.progress or 0.0 for u in passes]
    assert fractions == sorted(fractions)


def test_refresh_stops_when_server_makes_no_progress(tmp_path: Path) -> None:
    fake = QueueClient(demo_store(), backlog=5, per_pass=0)
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path), client=fake)
    _ = engine.refresh()
    assert fake.refresh_calls == 1


def test_pypi_reaches_dashboard_state_and_json(tmp_path: Path) -> None:
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    state = engine.install_demo(demo_store())
    assert [p.alias for p in state.pypi] == ["echohub"]
    assert state.to_dict()["pypi"]


def test_token_syncs_private_dump_and_rescopes_cache(tmp_path: Path) -> None:
    engine, fake = make_engine(tmp_path)
    _ = engine.sync()
    assert fake.private_calls == [False]

    engine.config.refresh_token = "tok"
    assert engine.sync().changed, "same marker, but the cache is the public view"
    assert fake.private_calls == [False, True]
    cached = engine.cache.load()
    assert cached is not None and cached.private

    assert not engine.sync().changed
    engine.config.refresh_token = None
    assert engine.sync().changed, "dropping the token must drop private data"
    assert fake.private_calls == [False, True, False]


def test_private_aggregate_is_dropped_once_private_projects_load(
    tmp_path: Path,
) -> None:
    store = demo_store()
    store["github:private:ujjwalvivek:langs"] = {"languages": {"Zig": 500}}
    store["github:secret:repo"] = {"name": "secret", "private": True}
    store["github:secret:langs"] = {"Zig": 500}
    engine = EchopointEngine(DashboardConfig(cache_dir=tmp_path))
    state = engine.install_demo(store)
    zig = next(row for row in state.analytics.languages if row.language == "Zig")
    assert zig.bytes == 500, "the private repo's own bytes, not doubled"
    assert zig.private_bytes == 0
    assert zig.projects == 1
    assert any(p.alias == "secret" and p.private for p in state.projects)


def test_missing_releases_are_not_collector_failures() -> None:
    from echohub.models import EngineMeta

    meta = EngineMeta(
        last_run={
            "failed": 3,
            "failures": [
                {"key": "github:resume:release", "status": 404},
                {"key": "docker:synclippy:tags", "status": 429},
                {"key": "github:x:repo", "status": 404},
            ],
        }
    )
    assert [f["key"] for f in meta.collector_failures] == [
        "docker:synclippy:tags",
        "github:x:repo",
    ]
