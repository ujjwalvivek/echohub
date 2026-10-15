import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import final

import pytest

from echohub import __version__
from echohub.client import EchopointClient, EchopointError
from echohub.config import DashboardConfig


@final
class FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@final
class Recorder:
    """Stands in for urlopen and remembers each request it was given."""

    def __init__(self, body: object) -> None:
        self.body = json.dumps(body)
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.body)


def make_client(**overrides: object) -> EchopointClient:
    config = DashboardConfig(base_url="https://example.invalid")
    for name, value in overrides.items():
        setattr(config, name, value)
    return EchopointClient(config)


def test_health_parses_payload_and_uses_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder(
        {
            "ok": True,
            "service": "echopoint",
            "sources": 557,
            "last_updated": "2026-10-14T20:00:16.308Z",
            "timestamp": "2026-10-15T08:00:00.000Z",
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    health = make_client().health()

    assert health.ok
    assert health.sources == 557
    assert health.last_updated == "2026-10-14T20:00:16.308Z"
    request = recorder.requests[0]
    assert request.full_url == "https://example.invalid/v1/health"
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == f"echohub/{__version__}"
    assert request.get_header("Authorization") is None
    assert recorder.timeouts == [DashboardConfig().timeout_seconds]


def test_health_tolerates_missing_sources_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", Recorder({"ok": True, "last_updated": None})
    )
    health = make_client().health()
    assert health.sources is None
    assert health.last_updated == ""


def test_refresh_posts_with_bearer_and_long_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder({"ok": True, "msg": "Refresh triggered"})
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    client = make_client(refresh_token="secret", refresh_timeout_seconds=150.0)
    _ = client.refresh()

    request = recorder.requests[0]
    assert request.full_url == "https://example.invalid/v1/refresh"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer secret"
    assert recorder.timeouts == [150.0]


def test_store_and_health_never_send_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder({"_meta:last_updated": "x"})
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    client = make_client(refresh_token="secret")
    _ = client.store()
    assert recorder.requests[0].get_header("Authorization") is None


def test_refresh_reports_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", Recorder({"ok": False, "error": "budget spent"})
    )
    with pytest.raises(EchopointError, match="budget spent"):
        _ = make_client().refresh()


def test_store_rejects_non_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", Recorder([1, 2, 3]))
    with pytest.raises(EchopointError, match="JSON object"):
        _ = make_client().store()


def test_http_error_is_wrapped_with_status_and_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_401(request: urllib.request.Request, timeout: float) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            Message(),
            io.BytesIO(b'{"error":"Unauthorized"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", raise_401)
    with pytest.raises(EchopointError, match=r"HTTP 401 for /v1/refresh"):
        _ = make_client().refresh()


def test_network_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(request: urllib.request.Request, timeout: float) -> FakeResponse:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(EchopointError, match="Request failed for /v1/health"):
        _ = make_client().health()


def test_private_store_uses_private_route_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder({"github:secret:repo": {"private": True}})
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    store = make_client(refresh_token="secret").store(private=True)
    request = recorder.requests[0]
    assert request.full_url == "https://example.invalid/v1/private"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer secret"
    assert "github:secret:repo" in store


@pytest.mark.parametrize(
    ("status", "message"),
    [(404, "no /v1/private route"), (401, "rejected the refresh token")],
)
def test_private_store_explains_missing_route_and_bad_token(
    monkeypatch: pytest.MonkeyPatch, status: int, message: str
) -> None:
    def fail(request: urllib.request.Request, timeout: float) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url, status, "x", Message(), io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(EchopointError, match=message) as info:
        _ = make_client(refresh_token="secret").store(private=True)
    assert info.value.status == status


def test_explain_error_turns_failures_into_plain_words() -> None:
    from echohub.client import EchopointError, explain_error

    url = "https://echopoint.example.com"

    def explain(exc: BaseException, token: bool = True) -> tuple[str, str]:
        return explain_error(exc, base_url=url, has_token=token)

    refused = EchopointError(
        "Request failed for /v1/health: <urlopen error [WinError 10061] refused>"
    )
    assert explain(refused) == (
        "Can't reach Echopoint",
        "Nothing is answering at echopoint.example.com.",
    )
    assert explain(EchopointError("Request failed: timed out"))[0] == (
        "Echopoint isn't responding"
    )
    assert explain(EchopointError("getaddrinfo failed"))[0] == "Can't find Echopoint"
    assert explain(EchopointError("HTTP 401", 401))[0] == "Echopoint rejected the token"
    assert explain(EchopointError("HTTP 401", 401), token=False)[0] == (
        "Refresh needs a token"
    )
    assert explain(EchopointError("HTTP 503", 503))[0] == "Echopoint had an error"
    assert explain(ValueError("odd")) == ("Sync failed", "odd")
