"""Stable cache-backed audio URLs, content validation and job dedupe."""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from starlette.requests import Request

from sing_gateway import cache, service
from sing_gateway.config import SingConfig
from sing_gateway.jobs import JobManager
from sing_gateway.server import sing


def _client() -> TestClient:
    return TestClient(sing.app, base_url="https://testserver")


def _request(scheme: str = "http", host: str = "127.0.0.1", port: int = 9001) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": (host, port),
            "root_path": "",
            "headers": [],
            "query_string": b"",
            "method": "GET",
            "path": "/",
            "http_version": "1.1",
        }
    )


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, content_type: str) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        return self._response


def test_audio_endpoint_serves_cached_mp3(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    root = cache.default_cache_root()
    root.mkdir(parents=True)
    key = "a" * 32
    (root / f"{key}.mp3").write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")

    response = _client().get(f"/v1/sing/audio/{key}.mp3")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content.startswith(b"ID3")

    head = _client().head(f"/v1/sing/audio/{key}.mp3")
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(response.content))

    ranged = _client().get(f"/v1/sing/audio/{key}.mp3", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == b"ID3\x04"


def test_audio_endpoint_rejects_unknown_and_malformed_keys(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    cache.default_cache_root().mkdir(parents=True)

    assert _client().get("/v1/sing/audio/" + "b" * 32 + ".mp3").status_code == 404
    assert _client().get("/v1/sing/audio/not-a-key.mp3").status_code == 404


def test_url_check_rejects_json_error_page(monkeypatch: MonkeyPatch) -> None:
    # Replicate serves this 39-byte page with HTTP 200/206 after Cloudflare
    # caches it, so a status-only check would consider a dead link healthy.
    body = b'{"detail": "requested file not found"}'
    monkeypatch.setattr(
        service.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(_FakeResponse(200, body, "application/json")),
    )

    assert service._url_reachable("https://replicate.delivery/dead.mp3") is False


def test_url_check_accepts_audio_bytes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        service.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            _FakeResponse(206, b"ID3\x04\x00\x00", "application/octet-stream")
        ),
    )

    assert service._url_reachable("https://replicate.delivery/live.mp3") is True


def test_cache_hit_returns_gateway_url(monkeypatch: MonkeyPatch, tmp_path) -> None:
    cfg = SingConfig(cache_root=tmp_path, replicate_token="r8_test")
    key = cache.cache_key("https://x/song", cfg.start, cfg.duration, cfg)
    meta = {
        "filename": "雨爱.mp3",
        "duration_seconds": 25,
        "audio_url": "https://replicate.delivery/dead.mp3",
    }
    monkeypatch.setattr(
        cache, "cache_lookup", lambda root, cache_key, ttl: (tmp_path / f"{key}.mp3", meta)
    )
    # Even when the stored delivery URL is dead, the local mp3 is enough.
    monkeypatch.setattr(service, "_url_reachable", lambda url: False)

    result = service.render_song(
        "https://x/song", cfg, audio_base="https://voice-models.flowbee.top/"
    )

    assert result.cached is True
    assert result.audio_url == f"https://voice-models.flowbee.top/v1/sing/audio/{key}.mp3"
    assert result.filename == "雨爱.mp3"


def test_audio_base_prefers_explicit_origin(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_AUDIO_BASE_URL", "https://voice-models.flowbee.top/")
    assert sing._audio_base(_request()) == "https://voice-models.flowbee.top"

    monkeypatch.delenv("SING_AUDIO_BASE_URL")
    monkeypatch.setenv("SING_PUBLIC_BASE_URL", "https://example.com/")
    assert sing._audio_base(_request()) == "https://example.com"


def test_audio_base_falls_back_to_request_host(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_AUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("SING_PUBLIC_BASE_URL", raising=False)

    assert sing._audio_base(_request()) == "http://127.0.0.1:9001"


def test_jobs_share_only_while_in_flight() -> None:
    async def scenario() -> None:
        def render(payload: dict[str, object]) -> dict[str, object]:
            time.sleep(0.15)
            return {"source": {"url": "https://cdn/a.mp3"}, "filename": "a.mp3"}

        manager = JobManager(render)
        first = manager.submit({"song": "雨爱"})
        second = manager.submit({"song": "雨爱"})
        assert second.id == first.id  # still queued/running: merged

        for _ in range(100):
            if first.status == "succeeded":
                break
            await asyncio.sleep(0.02)
        assert first.status == "succeeded"

        third = manager.submit({"song": "雨爱"})
        assert third.id != first.id  # finished: a new job hits the disk cache
        for _ in range(100):
            if third.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.02)

    asyncio.run(scenario())
