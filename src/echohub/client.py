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
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def explain_error(
    exc: BaseException, *, base_url: str, has_token: bool
) -> tuple[str, str]:
    """A short title and one plain sentence for a failed sync or refresh.

    The raw message is technical (urllib reasons, HTTP bodies); people need
    to know what happened and what to try.
    """
    text = str(exc)
    lowered = text.casefold()
    status = exc.status if isinstance(exc, EchopointError) else None
    host = base_url.split("://", 1)[-1].split("/", 1)[0]
    if status == 401:
        if not has_token:
            return (
                "Refresh needs a token",
                "Set ECHOHUB_REFRESH_TOKEN to refresh and to include private repos.",
            )
        return (
            "Echopoint rejected the token",
            "ECHOHUB_REFRESH_TOKEN doesn't match Echopoint's. Check the value "
            + "and restart Echohub.",
        )
    if status == 404 and "/v1/private" in text:
        return ("Echopoint is out of date", text)
    if status == 429:
        return (
            "Echopoint is busy",
            "It's rate limiting requests. Try again in a minute.",
        )
    if status is not None and status >= 500:
        return (
            "Echopoint had an error",
            f"It answered HTTP {status}. Try again later.",
        )
    if status is not None:
        return (f"Echopoint answered HTTP {status}", text)
    if "refused" in lowered or "10061" in lowered:
        return ("Can't reach Echopoint", f"Nothing is answering at {host}.")
    if "timed out" in lowered or "timeout" in lowered:
        return (
            "Echopoint isn't responding",
            f"{host} didn't answer in time. Check your connection.",
        )
    if "getaddrinfo" in lowered or "name or service" in lowered or "11001" in lowered:
        return (
            "Can't find Echopoint",
            f"{host} doesn't resolve. Check your connection or ECHOHUB_SOURCE_URL.",
        )
    if "ssl" in lowered or "certificate" in lowered:
        return ("Secure connection failed", f"Couldn't verify {host}'s certificate.")
    return ("Sync failed", text)


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

    def _request(
        self,
        path: str,
        *,
        token: bool = False,
        method: str = "GET",
        timeout: float | None = None,
    ) -> JsonValue:
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
            # An empty body keeps POST explicit (Content-Length: 0) for proxies.
            data=None if method == "GET" else b"",
            method=method,
        )
        try:
            # urlopen's typeshed return is intentionally broad across URL/file
            # handlers. Runtime behavior is narrowed immediately by read/decode.
            with urllib.request.urlopen(  # pyright: ignore[reportAny]
                request,
                timeout=timeout or self.config.timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")  # pyright: ignore[reportAny]
            return decode_json_value(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EchopointError(
                f"HTTP {exc.code} for {path}: {detail[:300]}", exc.code
            ) from exc
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

    def store(self, *, private: bool = False) -> JsonObject:
        """Download the snapshot; ``private`` uses the token-only full dump."""
        path = "/v1/private" if private else "/v1/store"
        try:
            data = self._request(path, token=private)
        except EchopointError as exc:
            if private and exc.status == 404:
                raise EchopointError(
                    "Echopoint has no /v1/private route; deploy the latest Echopoint "
                    + "or unset ECHOPOINT_REFRESH_TOKEN to use the public snapshot.",
                    404,
                ) from exc
            if private and exc.status == 401:
                raise EchopointError(
                    "Echopoint rejected the refresh token for /v1/private.", 401
                ) from exc
            raise
        if not isinstance(data, dict):
            raise EchopointError(f"{path} did not return a JSON object")
        return data

    def refresh(self) -> JsonObject:
        data = self._request(
            "/v1/refresh",
            token=True,
            method="POST",
            timeout=self.config.refresh_timeout_seconds,
        )
        if not isinstance(data, dict):
            raise EchopointError("/v1/refresh did not return a JSON object")
        if data.get("ok") is False:
            raise EchopointError(as_str(data.get("error"), "Echopoint refresh failed"))
        return data
