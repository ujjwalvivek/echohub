from pathlib import Path

import pytest

from echohub import __version__
from echohub.config import DEFAULT_BASE_URL, DashboardConfig

ENV_NAMES = (
    "ECHOHUB_SOURCE_URL",
    "ECHOPOINT_URL",
    "ECHOHUB_CACHE_DIR",
    "ECHOPOINT_CACHE_DIR",
    "ECHOHUB_REFRESH_TOKEN",
    "ECHOPOINT_REFRESH_TOKEN",
    "ECHOHUB_TIMEOUT",
    "ECHOPOINT_TIMEOUT",
    "ECHOHUB_REFRESH_TIMEOUT",
    "ECHOPOINT_REFRESH_TIMEOUT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    config = DashboardConfig.from_env()
    assert config.base_url == DEFAULT_BASE_URL
    assert config.refresh_token is None
    assert config.timeout_seconds < config.refresh_timeout_seconds
    assert config.user_agent == f"echohub/{__version__}"
    assert config.cache_dir.name == "echohub"


def test_primary_env_names_win(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ECHOHUB_SOURCE_URL", "https://primary.invalid/")
    monkeypatch.setenv("ECHOPOINT_URL", "https://legacy.invalid")
    monkeypatch.setenv("ECHOHUB_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ECHOHUB_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("ECHOHUB_TIMEOUT", "5")
    monkeypatch.setenv("ECHOHUB_REFRESH_TIMEOUT", "300")
    config = DashboardConfig.from_env()
    assert config.base_url == "https://primary.invalid"
    assert config.cache_dir == tmp_path
    assert config.refresh_token == "tok"
    assert config.timeout_seconds == 5.0
    assert config.refresh_timeout_seconds == 300.0


def test_legacy_env_names_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECHOPOINT_URL", "https://legacy.invalid")
    monkeypatch.setenv("ECHOPOINT_REFRESH_TOKEN", "old")
    config = DashboardConfig.from_env()
    assert config.base_url == "https://legacy.invalid"
    assert config.refresh_token == "old"
