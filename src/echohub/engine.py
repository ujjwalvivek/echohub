from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, final

from .analytics import build_analytics
from .cache import CacheStore
from .client import EchopointClient, Health
from .config import DashboardConfig
from .models import DashboardState
from .normalize import (
    normalize_docker,
    normalize_meta,
    normalize_packages,
    normalize_private_languages,
    normalize_projects,
    normalize_statuses,
    normalize_user,
)
from .types import JsonObject, as_int, as_str

# Guards against a server that never reports an empty queue. One pass covers
# Echopoint's per-invocation fetch budget, so this bounds a full catch-up.
MAX_REFRESH_PASSES = 60


@dataclass(slots=True)
class ProgressUpdate:
    stage: str
    progress: float | None
    message: str


@dataclass(slots=True)
class SyncResult:
    changed: bool
    source: str
    last_updated: str
    message: str


ProgressCallback = Callable[[ProgressUpdate], None]


class EchopointClientProtocol(Protocol):
    def health(self) -> Health: ...
    def store(self, *, private: bool = False) -> JsonObject: ...
    def refresh(self) -> JsonObject: ...


@final
class EchopointEngine:
    """Network rules:
    1. GET /v1/health to learn whether last_updated changed.
    2. GET /v1/store (or the token-only /v1/private) only if it changed, no
       local snapshot exists, or the cached snapshot has the other visibility.
    3. Manual refresh calls Echopoint's /v1/refresh once, then re-syncs.
    """

    def __init__(
        self,
        config: DashboardConfig | None = None,
        *,
        client: EchopointClientProtocol | None = None,
    ) -> None:
        self.config = config or DashboardConfig.from_env()
        self.client: EchopointClientProtocol = client or EchopointClient(self.config)
        self.cache = CacheStore(self.config.cache_dir)
        self._lock = threading.RLock()
        self._state: DashboardState | None = None
        self._raw: JsonObject = {}
        self._remote_sources: int | None = None

    @property
    def state(self) -> DashboardState:
        with self._lock:
            if self._state is None:
                cached = self.cache.load()
                if cached is None:
                    raise RuntimeError(
                        "Engine has no data. Call sync() first or use demo mode."
                    )
                _ = self._apply(
                    cached.store, fetched_at=cached.fetched_at, from_cache=True
                )
            assert self._state is not None
            return self._state

    @property
    def wants_private(self) -> bool:
        """With a token, sync the full dump including private repositories."""
        return bool(self.config.refresh_token)

    @property
    def raw_store(self) -> JsonObject:
        with self._lock:
            return dict(self._raw)

    def load_cache(self) -> bool:
        cached = self.cache.load()
        if cached is None:
            return False
        _ = self._apply(cached.store, fetched_at=cached.fetched_at, from_cache=True)
        return True

    def _apply(
        self, store: JsonObject, *, fetched_at: str, from_cache: bool
    ) -> DashboardState:
        projects = normalize_projects(store)
        npm = normalize_packages(store, "npm")
        crates = normalize_packages(store, "crates")
        pypi = normalize_packages(store, "pypi")
        docker = normalize_docker(store)
        statuses = normalize_statuses(store)
        user = normalize_user(store)
        # The sanitized aggregate sums the configured private repos. Once those
        # repos arrive as real projects, counting it too would double them.
        private_languages = (
            {}
            if any(project.private for project in projects)
            else normalize_private_languages(store)
        )
        analytics = build_analytics(
            projects, npm, crates, docker, private_languages, pypi=pypi
        )
        state = DashboardState(
            meta=normalize_meta(
                store,
                fetched_at=fetched_at,
                from_cache=from_cache,
                remote_sources=self._remote_sources,
            ),
            projects=projects,
            npm=npm,
            crates=crates,
            docker=docker,
            statuses=statuses,
            user=user,
            analytics=analytics,
            raw_key_count=len(store),
            pypi=pypi,
        )
        with self._lock:
            self._raw = store
            self._state = state
        return state

    def sync(
        self,
        *,
        force_store: bool = False,
        progress: ProgressCallback | None = None,
    ) -> SyncResult:
        callback = progress or _noop_progress
        callback(
            ProgressUpdate("health", 0.08, "Checking Echopoint for a changed snapshot")
        )
        health = self.client.health()
        self._remote_sources = health.sources
        cached = self.cache.load()
        current = cached.last_updated if cached else ""
        private = self.wants_private
        if (
            cached
            and not force_store
            and cached.private == private
            and health.last_updated
            and health.last_updated == current
        ):
            if self._state is None:
                _ = self._apply(
                    cached.store, fetched_at=cached.fetched_at, from_cache=True
                )
            callback(ProgressUpdate("done", 1.0, "Local snapshot is already current"))
            return SyncResult(False, "cache", current, "No change")

        route = "/v1/private" if private else "/v1/store"
        callback(
            ProgressUpdate("store", 0.55, f"Snapshot changed; downloading {route} once")
        )
        store = self.client.store(private=private)
        last_updated = as_str(store.get("_meta:last_updated")) or health.last_updated
        saved = self.cache.save(store, last_updated, private=private)
        callback(
            ProgressUpdate("normalize", 0.85, "Normalizing telemetry for all renderers")
        )
        _ = self._apply(saved.store, fetched_at=saved.fetched_at, from_cache=False)
        callback(ProgressUpdate("done", 1.0, "Dashboard snapshot updated"))
        return SyncResult(True, "network", saved.last_updated, "Updated")

    def refresh(self, progress: ProgressCallback | None = None) -> SyncResult:
        """Drain Echopoint's due queue, then re-sync once.

        Each /v1/refresh call is one Worker invocation with a fixed fetch
        budget, so a single call only covers a slice of the due sources. Keep
        asking until Echopoint reports nothing left over budget.
        """
        callback = progress or _noop_progress
        callback(ProgressUpdate("refresh", 0.06, "Requesting source refresh"))
        callback(ProgressUpdate("refresh", None, "Echopoint is collecting telemetry"))
        initial_due = 0
        for attempt in range(1, MAX_REFRESH_PASSES + 1):
            result = self.client.refresh()
            processed = as_int(result.get("processed"))
            remaining = as_int(result.get("budget_skipped"))
            initial_due = initial_due or as_int(result.get("due"))
            if remaining <= 0 or processed <= 0:
                break
            done = 1.0 - remaining / initial_due if initial_due else 0.0
            callback(
                ProgressUpdate(
                    "refresh",
                    0.06 + 0.72 * max(0.0, min(1.0, done)),
                    f"Echopoint pass {attempt}: {processed} sources refreshed, "
                    + f"{remaining} still queued",
                )
            )
        callback(
            ProgressUpdate("verify", 0.78, "Refresh returned; checking snapshot marker")
        )

        def scaled(update: ProgressUpdate) -> None:
            scaled_progress = (
                None if update.progress is None else 0.78 + update.progress * 0.22
            )
            callback(ProgressUpdate(update.stage, scaled_progress, update.message))

        result = self.sync(force_store=False, progress=scaled)
        callback(ProgressUpdate("done", 1.0, "Refresh complete"))
        return result

    def install_demo(self, store: JsonObject) -> DashboardState:
        now = datetime.now(UTC).isoformat()
        saved = self.cache.save(store, as_str(store.get("_meta:last_updated")) or now)
        return self._apply(saved.store, fetched_at=saved.fetched_at, from_cache=False)


def _noop_progress(_update: ProgressUpdate) -> None:
    return
