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
