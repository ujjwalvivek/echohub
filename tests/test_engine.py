from pathlib import Path
from typing import final

from echohub.client import Health
from echohub.config import DashboardConfig
from echohub.demo import demo_store
from echohub.engine import EchopointEngine, ProgressUpdate
from echohub.types import JsonObject, as_str


@final
class FakeClient:
    def __init__(self, store: JsonObject) -> None:
        self.current = store
        self.health_calls = 0
        self.store_calls = 0
        self.refresh_calls = 0

    def health(self) -> Health:
        self.health_calls += 1
        return Health(
            True,
            "echopoint",
            42,
            as_str(self.current.get("_meta:last_updated")),
            "now",
        )

    def store(self) -> JsonObject:
        self.store_calls += 1
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
