from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import final

from .config import DashboardConfig
from .types import (
    JsonObject,
    JsonValue,
    as_bool,
    as_int,
    as_object,
    as_str,
    decode_json_value,
)


class EchopointError(RuntimeError):
    pass


@dataclass(slots=True)
class Health:
    ok: bool
    service: str
    sources: int | None
    last_updated: str
    timestamp: str


@final
class EchopointClient:
    """Tiny HTTP client."""

    def __init__(self, config: DashboardConfig) -> None:
        self.config = config

    def _request(self, path: str, *, token: bool = False) -> JsonValue:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
            "Cache-Control": "no-cache",
        }
        if token and self.config.refresh_token:
            headers["Authorization"] = f"Bearer {self.config.refresh_token}"
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            headers=headers,
            method="GET",
        )
        try:
            # urlopen's typeshed return is intentionally broad across URL/file
            # handlers. Runtime behavior is narrowed immediately by read/decode.
            with urllib.request.urlopen(  # pyright: ignore[reportAny]
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")  # pyright: ignore[reportAny]
            return decode_json_value(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EchopointError(f"HTTP {exc.code} for {path}: {detail[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise EchopointError(f"Request failed for {path}: {exc}") from exc

    def health(self) -> Health:
        data = as_object(self._request("/v1/health"))
        sources_value = data.get("sources")
        sources = as_int(sources_value) if sources_value is not None else None
        return Health(
            ok=as_bool(data.get("ok")),
            service=as_str(data.get("service"), "echopoint"),
            sources=sources,
            last_updated=as_str(data.get("last_updated")),
            timestamp=as_str(data.get("timestamp")),
        )

    def store(self) -> JsonObject:
        data = self._request("/v1/store")
        if not isinstance(data, dict):
            raise EchopointError("/v1/store did not return a JSON object")
        return data

    def refresh(self) -> JsonObject:
        data = self._request("/v1/refresh", token=True)
        if not isinstance(data, dict):
            raise EchopointError("/v1/refresh did not return a JSON object")
        if data.get("ok") is False:
            raise EchopointError(as_str(data.get("error"), "Echopoint refresh failed"))
        return data
