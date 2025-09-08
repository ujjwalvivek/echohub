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
