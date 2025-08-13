from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import final

from .types import JsonObject, as_object, as_str, decode_json_object


@dataclass(slots=True)
class CachedPayload:
    store: JsonObject
    last_updated: str
    fetched_at: str


@final
class CacheStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "store.json"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> CachedPayload | None:
        if not self.path.exists():
            return None
        try:
            payload = decode_json_object(self.path.read_text(encoding="utf-8"))
            return CachedPayload(
                store=as_object(payload.get("store")),
                last_updated=as_str(payload.get("last_updated")),
                fetched_at=as_str(payload.get("fetched_at")),
            )
        except (OSError, ValueError, TypeError):
            return None

    def save(self, store: JsonObject, last_updated: str | None = None) -> CachedPayload:
        self.directory.mkdir(parents=True, exist_ok=True)
        effective_updated = last_updated or as_str(store.get("_meta:last_updated"))
        fetched_at = datetime.now(UTC).isoformat()
        payload: JsonObject = {
            "version": 1,
            "last_updated": effective_updated,
            "fetched_at": fetched_at,
            "store": store,
        }
        fd, tmp_name = tempfile.mkstemp(
            prefix="store-", suffix=".json", dir=self.directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return CachedPayload(
            store=store,
            last_updated=effective_updated,
            fetched_at=fetched_at,
        )

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
