"""Contract tests for the asynchronous job API."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from sing_gateway.config import ClientSongError, SingResult
from sing_gateway.server import sing


def _client() -> TestClient:
    return TestClient(sing.app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def _job_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    monkeypatch.setenv("SING_VOICE_URL", "https://example.com/voice.zip")
    monkeypatch.setattr(sing, "_JOBS", sing.JobManager(lambda payload: sing._render(payload)))


def _submit(payload: dict) -> dict:
    response = _client().post(
        "/sing/v1/jobs",
        headers={"Authorization": "Bearer secret"},
        json=payload,
    )
    assert response.status_code == 202, response.text
    return response.json()


def _poll(job_id: str, *, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    client = _client()
    while time.monotonic() < deadline:
        response = client.get(
            f"/sing/v1/jobs/{job_id}",
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {body}")


def test_submit_and_poll_success(monkeypatch: MonkeyPatch) -> None:
    def fake_render(payload: dict) -> dict:
        assert payload["song"] == "雨爱"
        assert payload["duration"] == 30
        return {
            "type": "audio",
            "source": {"type": "url", "url": "https://cdn.example/cover.mp3"},
            "filename": "yuai.mp3",
            "title": "雨爱",
            "artist": "杨丞琳",
            "duration_seconds": 30,
            "cached": True,
        }

    monkeypatch.setattr(sing, "_render", fake_render)
    submitted = _submit({"song": "雨爱", "duration": 30})
    assert submitted["status"] in {"queued", "running", "succeeded"}
    finished = _poll(submitted["id"])
    assert finished["status"] == "succeeded"
    assert finished["audio_url"] == "https://cdn.example/cover.mp3"
    assert finished["title"] == "雨爱"
    assert finished["artist"] == "杨丞琳"
    assert finished["duration_seconds"] == 30
    assert finished["cached"] is True


def test_identical_submissions_share_one_job() -> None:
    first = _submit({"song": "晴天", "duration": 25})
    second = _submit({"song": "晴天", "duration": 25})
    assert first["id"] == second["id"]


def test_failure_is_reported(monkeypatch: MonkeyPatch) -> None:
    def fail_render(payload: dict) -> dict:
        raise ClientSongError("no song found for '不存在的歌'")

    monkeypatch.setattr(sing, "_render", fail_render)
    submitted = _submit({"song": "不存在的歌"})
    finished = _poll(submitted["id"])
    assert finished["status"] == "failed"
    assert "no song found" in finished["error"]


def test_unknown_voice_is_rejected_before_queueing(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_VOICES_FILE", "does-not-exist.json")
    response = _client().post(
        "/sing/v1/jobs",
        headers={"Authorization": "Bearer secret"},
        json={"song": "雨爱", "voice": "not-a-voice"},
    )
    assert response.status_code == 400
    assert "unknown voice" in response.text


def test_job_api_requires_token() -> None:
    response = _client().post("/sing/v1/jobs", json={"song": "雨爱"})
    assert response.status_code == 401


def test_unknown_job_is_404() -> None:
    response = _client().get(
        "/sing/v1/jobs/job_missing",
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 404


def test_duration_seconds_and_cache_flag_in_audio_block() -> None:
    block = SingResult(
        "https://cdn.example/a.mp3",
        "a.mp3",
        cached=True,
        duration_seconds=42,
    ).as_block()
    assert block["cached"] is True
    assert block["duration_seconds"] == 42
