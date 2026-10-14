from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

DEFAULT_BASE_URL = "https://echopoint.ujjwalvivek.com"


def _default_cache_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "echohub"
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "echohub"


def _env(primary: str, legacy: str, default: str | None = None) -> str | None:
    return os.environ.get(primary) or os.environ.get(legacy) or default


@dataclass(slots=True)
class DashboardConfig:
    base_url: str = DEFAULT_BASE_URL
    cache_dir: Path = field(default_factory=_default_cache_dir)
    refresh_token: str | None = None
    # Health and store reads are small and should fail fast; an upstream
    # refresh blocks while Echopoint fetches its sources, so it gets longer.
    timeout_seconds: float = 20.0
    refresh_timeout_seconds: float = 120.0
    user_agent: str = f"echohub/{__version__}"

    @classmethod
    def from_env(cls) -> DashboardConfig:
        return cls(
            base_url=(
                _env("ECHOHUB_SOURCE_URL", "ECHOPOINT_URL", DEFAULT_BASE_URL)
                or DEFAULT_BASE_URL
            ).rstrip("/"),
            cache_dir=Path(
                _env(
                    "ECHOHUB_CACHE_DIR",
                    "ECHOPOINT_CACHE_DIR",
                    str(_default_cache_dir()),
                )
                or _default_cache_dir()
            ),
            refresh_token=_env("ECHOHUB_REFRESH_TOKEN", "ECHOPOINT_REFRESH_TOKEN")
            or None,
            timeout_seconds=float(
                _env("ECHOHUB_TIMEOUT", "ECHOPOINT_TIMEOUT", "20") or "20"
            ),
            refresh_timeout_seconds=float(
                _env("ECHOHUB_REFRESH_TIMEOUT", "ECHOPOINT_REFRESH_TIMEOUT", "120")
                or "120"
            ),
        )
