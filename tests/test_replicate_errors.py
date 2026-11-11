"""Broken voice zips (empty faiss index) must surface as ClientSongError (400)."""

from __future__ import annotations

from typing import Any

import pytest

from sing_gateway import replicate
from sing_gateway.config import ClientSongError, SingConfig


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:  # pragma: no cover - tests use 200 only
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Replays canned responses for create + poll."""

    def __init__(self, job: dict[str, Any]) -> None:
        self._job = job

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({"id": "pred-test"})

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._job)


def _predict_with_job(monkeypatch: pytest.MonkeyPatch, job: dict[str, Any]) -> None:
    monkeypatch.setattr(replicate.httpx, "Client", lambda **kwargs: _FakeClient(job))
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)


def test_empty_index_failure_maps_to_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _predict_with_job(
        monkeypatch,
        {"status": "failed", "error": "index -1 is out of bounds for axis 0 with size 0"},
    )
    with pytest.raises(ClientSongError):
        replicate.predict_cover(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/song.mp3",
            SingConfig(replicate_token="r8_test", model_version="v-test"),
        )


def test_other_prediction_failures_stay_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _predict_with_job(monkeypatch, {"status": "failed", "error": "cuDNN error"})
    with pytest.raises(RuntimeError) as excinfo:
        replicate.predict_cover(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/song.mp3",
            SingConfig(replicate_token="r8_test", model_version="v-test"),
        )
    assert not isinstance(excinfo.value, ClientSongError)
    assert "cuDNN" in str(excinfo.value)


def test_dead_voice_link_maps_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _predict_with_job(
        monkeypatch,
        {
            "status": "failed",
            "error": "HTTP Error 404: Not Found",
            "logs": (
                "[!] The model will be downloaded as 'GawrGura_RVC_v2'.\n"
                "[~] Downloading voice model with name GawrGura_RVC_v2...\n"
                "Traceback (most recent call last):\n"
                "urllib.error.HTTPError: HTTP Error 404: Not Found"
            ),
        },
    )
    with pytest.raises(ClientSongError) as excinfo:
        replicate.predict_cover(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/song.mp3",
            SingConfig(replicate_token="r8_test", model_version="v-test"),
        )
    assert "HTTP 404" in str(excinfo.value)
    assert "换一个音色" in str(excinfo.value)


def test_private_voice_link_maps_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _predict_with_job(
        monkeypatch,
        {
            "status": "failed",
            "error": "HTTP Error 401: Unauthorized",
            "logs": "[~] Downloading voice model with name aya...",
        },
    )
    with pytest.raises(ClientSongError) as excinfo:
        replicate.predict_cover(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/song.mp3",
            SingConfig(replicate_token="r8_test", model_version="v-test"),
        )
    assert "HTTP 401" in str(excinfo.value)


def test_song_download_404_is_not_a_voice_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _predict_by_job = {"status": "failed", "error": "HTTP Error 404: Not Found"}
    _predict_with_job(monkeypatch, _predict_by_job)
    with pytest.raises(RuntimeError) as excinfo:
        replicate.predict_cover(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/song.mp3",
            SingConfig(replicate_token="r8_test", model_version="v-test"),
        )
    assert not isinstance(excinfo.value, ClientSongError)


def test_payload_carries_configured_mixing_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CaptureClient(_FakeClient):
        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            if isinstance(kwargs.get("json"), dict):
                captured.update(kwargs["json"])
            return super().post(url, **kwargs)

    monkeypatch.setattr(
        replicate.httpx,
        "Client",
        lambda **kwargs: _CaptureClient({"status": "succeeded", "output": ["https://x/out.mp3"]}),
    )
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)
    replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.mp3",
        SingConfig(
            replicate_token="r8_test",
            model_version="v-test",
            instrumental_volume=0,
            backup_vocals_volume=-6,
        ),
    )
    payload_input = captured["input"]
    assert payload_input["instrumental_volume_change"] == 0
    assert payload_input["backup_vocals_volume_change"] == -6
    assert payload_input["main_vocals_volume_change"] == 0


def test_payload_mutes_stems_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _CaptureClient(_FakeClient):
        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            if isinstance(kwargs.get("json"), dict):
                captured.update(kwargs["json"])
            return super().post(url, **kwargs)

    monkeypatch.setattr(
        replicate.httpx,
        "Client",
        lambda **kwargs: _CaptureClient({"status": "succeeded", "output": ["https://x/out.mp3"]}),
    )
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)
    replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.mp3",
        SingConfig(replicate_token="r8_test", model_version="v-test"),
    )
    payload_input = captured["input"]
    assert payload_input["instrumental_volume_change"] == -60
    assert payload_input["backup_vocals_volume_change"] == -60


def test_chinese_voice_url_is_percent_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """urllib inside AICoverGen dies on a non-ASCII request line."""
    captured: dict[str, Any] = {}

    class _CaptureClient(_FakeClient):
        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            if isinstance(kwargs.get("json"), dict):
                captured.update(kwargs["json"])
            return super().post(url, **kwargs)

    monkeypatch.setattr(
        replicate.httpx,
        "Client",
        lambda **kwargs: _CaptureClient({"status": "succeeded", "output": ["https://x/out.mp3"]}),
    )
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)
    raw = (
        "https://modelscope.cn/models/leicanxi/rvc-voice-uploads/resolve/master/"
        "uploads/纳西妲-2dab.zip"
    )
    replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.mp3",
        SingConfig(replicate_token="r8_test", model_version="v-test", voice_model_url=raw),
    )

    url = captured["input"]["custom_rvc_model_download_url"]
    assert url.endswith("/uploads/%E7%BA%B3%E8%A5%BF%E5%A6%B2-2dab.zip")
    url.encode("ascii")  # must not raise
    # An already-encoded URL must not be encoded twice.
    assert replicate._ascii_url(url) == url
