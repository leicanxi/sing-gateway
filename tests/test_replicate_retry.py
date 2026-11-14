"""Transient Replicate failures must not kill a render that is still running."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sing_gateway import replicate
from sing_gateway.config import SingConfig

_URL = "https://api.replicate.com/v1/predictions/pred-1"


class _Response:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", _URL),
                response=self,  # type: ignore[arg-type]
            )


class _ScriptedClient:
    """Returns canned responses (or raises canned errors) in order."""

    def __init__(self, posts: list[Any], gets: list[Any]) -> None:
        self._posts = posts
        self._gets = gets
        self.posts = 0
        self.gets = 0

    def __enter__(self) -> _ScriptedClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _Response:
        item = self._posts[min(self.posts, len(self._posts) - 1)]
        self.posts += 1
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url: str, **kwargs: Any) -> _Response:
        item = self._gets[min(self.gets, len(self._gets) - 1)]
        self.gets += 1
        if isinstance(item, Exception):
            raise item
        return item


def _sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


def test_request_retries_503_then_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([], [_Response(503), _Response(503), _Response(200, {"ok": True})])
    response = replicate._request(client, "GET", _URL)  # type: ignore[arg-type]
    assert response.status_code == 200
    assert client.gets == 3
    assert sleeps == [2.0, 4.0]


def test_request_honours_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([], [_Response(429, headers={"retry-after": "7"}), _Response(200)])
    replicate._request(client, "GET", _URL)  # type: ignore[arg-type]
    assert sleeps == [8.0]


def test_request_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([], [_Response(400)])
    response = replicate._request(client, "GET", _URL)  # type: ignore[arg-type]
    assert response.status_code == 400
    assert client.gets == 1
    assert sleeps == []


def test_get_retries_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([], [httpx.ReadTimeout("slow"), _Response(200)])
    response = replicate._request(client, "GET", _URL)  # type: ignore[arg-type]
    assert response.status_code == 200
    assert client.gets == 2
    assert len(sleeps) == 1


def test_post_does_not_retry_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([httpx.ReadTimeout("slow")], [])
    with pytest.raises(httpx.ReadTimeout):
        replicate._request(client, "POST", _URL, idempotent=False)  # type: ignore[arg-type]
    assert client.posts == 1
    assert sleeps == []


def test_post_retries_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _sleeps(monkeypatch)
    client = _ScriptedClient([httpx.ConnectError("dns"), _Response(200)], [])
    response = replicate._request(client, "POST", _URL, idempotent=False)  # type: ignore[arg-type]
    assert response.status_code == 200
    assert client.posts == 2
    assert len(sleeps) == 1


def test_request_gives_up_after_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    _sleeps(monkeypatch)
    client = _ScriptedClient([], [_Response(503)])
    with pytest.raises(RuntimeError, match="failed after 10 attempts"):
        replicate._request(client, "GET", _URL)  # type: ignore[arg-type]
    assert client.gets == 10


def test_poll_survives_503_and_returns_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _sleeps(monkeypatch)
    client = _ScriptedClient(
        [_Response(200, {"id": "pred-1"})],
        [_Response(503), _Response(200, {"status": "succeeded", "output": ["https://x/out.mp3"]})],
    )
    monkeypatch.setattr(replicate.httpx, "Client", lambda **kwargs: client)
    url = replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.mp3",
        SingConfig(replicate_token="r8_test", model_version="v-test"),
    )
    assert url == "https://x/out.mp3"


def test_create_survives_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _sleeps(monkeypatch)
    client = _ScriptedClient(
        [_Response(503), _Response(200, {"id": "pred-1"})],
        [_Response(200, {"status": "succeeded", "output": "https://x/out.mp3"})],
    )
    monkeypatch.setattr(replicate.httpx, "Client", lambda **kwargs: client)
    url = replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.mp3",
        SingConfig(replicate_token="r8_test", model_version="v-test"),
    )
    assert url == "https://x/out.mp3"
    assert client.posts == 2
