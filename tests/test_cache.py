from pathlib import Path

from echohub.cache import CacheStore
from echohub.demo import demo_store
from echohub.types import as_int, as_object, as_str, decode_json_object


def test_cache_is_one_atomic_latest_snapshot(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    store = demo_store()
    _ = cache.save(store)
    assert cache.exists()
    loaded = cache.load()
    assert loaded is not None
    assert loaded.last_updated == as_str(store.get("_meta:last_updated"))
    repo = as_object(loaded.store.get("github:echopoint:repo"))
    assert as_str(repo.get("name")) == "echopoint"
    payload = decode_json_object((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert as_int(payload.get("version")) == 1
    assert "history" not in payload


def test_corrupt_cache_reads_as_missing(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    _ = (tmp_path / "store.json").write_text("{not json", encoding="utf-8")
    assert cache.load() is None


def test_save_leaves_no_temp_files_and_overwrites(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path / "nested")
    _ = cache.save({"_meta:last_updated": "one"})
    _ = cache.save({"_meta:last_updated": "two"})
    assert [p.name for p in (tmp_path / "nested").iterdir()] == ["store.json"]
    loaded = cache.load()
    assert loaded is not None
    assert loaded.last_updated == "two"


def test_clear_is_idempotent(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    cache.clear()
    _ = cache.save({})
    cache.clear()
    assert not cache.exists()


def test_private_flag_round_trips_and_defaults_to_public(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    _ = cache.save({"_meta:last_updated": "x"}, private=True)
    loaded = cache.load()
    assert loaded is not None and loaded.private
    _ = (tmp_path / "store.json").write_text(
        '{"version": 1, "last_updated": "x", "store": {}}', encoding="utf-8"
    )
    legacy = cache.load()
    assert legacy is not None and not legacy.private
