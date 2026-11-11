"""Zero-shot reference voices: engine inference, dispatch, payload, failures."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from sing_gateway import cache, replicate, service
from sing_gateway.config import (
    AUTO_PITCH_MODE,
    RVC_ENGINE,
    SVC_ENGINE,
    ClientSongError,
    SingConfig,
    SingResult,
)
from sing_gateway.server import sing
from sing_gateway.voices import infer_engine, load_voices


def test_engine_inferred_from_audio_suffix() -> None:
    assert infer_engine("https://cdn/me.mp3") == SVC_ENGINE
    assert infer_engine("https://cdn/me.FLAC?token=x") == SVC_ENGINE
    assert infer_engine("https://cdn/me.zip") == RVC_ENGINE
    # Opaque storage URLs keep the historical RVC behaviour unless the entry
    # says otherwise.
    assert infer_engine("https://cdn/download?id=1") == RVC_ENGINE
    assert infer_engine("https://cdn/download?id=1", "svc_ref") == SVC_ENGINE


def test_voice_json_declares_reference_engine(tmp_path: Path) -> None:
    path = tmp_path / "voices.json"
    path.write_text(
        json.dumps(
            {
                "me": {"label": "Me", "url": "https://cdn/me.mp3"},
                "trained": {"url": "https://cdn/trained.zip"},
                "forced": {"url": "https://cdn/download?id=9", "engine": "svc_ref"},
            }
        ),
        encoding="utf-8",
    )
    voices = load_voices(path)
    assert voices["me"].engine == SVC_ENGINE
    assert voices["me"].is_reference is True
    assert voices["trained"].engine == RVC_ENGINE
    assert voices["forced"].engine == SVC_ENGINE


def test_config_picks_engine_from_the_voice(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "voices.json"
    path.write_text(
        json.dumps({"me": {"label": "Me", "url": "https://cdn/me.mp3"}}), encoding="utf-8"
    )
    monkeypatch.setenv("SING_VOICES_FILE", str(path))
    monkeypatch.setenv("SING_SVC_MODEL", "operator/soulx-svc")
    monkeypatch.delenv("SING_SVC_VERSION", raising=False)

    config = sing._config({"voice": "me"})
    assert config.voice_engine == SVC_ENGINE
    assert config.voice_model_url == "https://cdn/me.mp3"
    assert config.svc_model == "operator/soulx-svc"
    assert config.svc_n_steps == 32
    assert config.svc_cfg == 3.0
    assert config.svc_auto_shift is False


def test_config_keeps_rvc_for_zip_voices(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "voices.json"
    path.write_text(
        json.dumps({"cirno": {"label": "Cirno", "url": "https://cdn/cirno.zip"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_VOICES_FILE", str(path))
    assert sing._config({"voice": "cirno"}).voice_engine == RVC_ENGINE


def test_audio_block_reports_engine() -> None:
    block = SingResult("https://cdn/a.mp3", "a.mp3", engine=SVC_ENGINE).as_block()
    assert block["engine"] == SVC_ENGINE


def test_cache_key_separates_reference_renders() -> None:
    url, start, duration = "https://www.bilibili.com/video/BV1", 60, 25
    rvc = SingConfig(voice_model_url="https://cdn/a.zip")
    svc = SingConfig(
        voice_engine=SVC_ENGINE,
        voice_model_url="https://cdn/a.mp3",
    )
    base_key = cache.cache_key(url, start, duration, svc)

    assert base_key != cache.cache_key(url, start, duration, rvc)
    # A different reference clip is a different voice.
    assert base_key != cache.cache_key(
        url, start, duration, replace(svc, voice_model_url="https://cdn/b.mp3")
    )
    # Sampling knobs change the audio too.
    assert base_key != cache.cache_key(url, start, duration, replace(svc, svc_n_steps=16))
    assert base_key != cache.cache_key(url, start, duration, replace(svc, svc_seed=7))
    assert base_key != cache.cache_key(
        url, start, duration, replace(svc, svc_model="operator/other-cog")
    )
    assert base_key == cache.cache_key(url, start, duration, replace(svc))


def test_job_view_exposes_engine() -> None:
    from sing_gateway.jobs import Job, JobManager

    manager = JobManager(lambda payload: {})
    job = Job(id="job_test", payload={}, dedupe_key="key")
    job.status = "succeeded"
    job.result = {"source": {"url": "https://x/a.mp3"}, "engine": SVC_ENGINE}
    assert manager.view(job)["engine"] == SVC_ENGINE


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
    """Replays one terminal job and records the submitted payload."""

    def __init__(self, job: dict[str, Any], captured: dict[str, Any]) -> None:
        self._job = job
        self._captured = captured

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        if isinstance(kwargs.get("json"), dict):
            self._captured.update(kwargs["json"])
        return _FakeResponse({"id": "pred-test"})

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._job)


def _patch_svc(
    monkeypatch: MonkeyPatch,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    terminal = job or {"status": "succeeded", "output": ["https://x/out.mp3"]}
    monkeypatch.setattr(
        replicate.httpx, "Client", lambda **kwargs: _FakeClient(terminal, captured)
    )
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)
    return captured


def _svc_cfg(**overrides: Any) -> SingConfig:
    values: dict[str, Any] = {
        "replicate_token": "r8_test",
        "voice_engine": SVC_ENGINE,
        "voice_model_url": "https://cdn/ref.mp3",
        "svc_model": "operator/soulx-svc",
        "svc_model_version": "v-test",
        "pitch": 0,
    }
    values.update(overrides)
    return SingConfig(**values)


def test_predict_svc_payload_for_auto_shift(monkeypatch: MonkeyPatch) -> None:
    captured = _patch_svc(monkeypatch)
    replicate.predict_svc(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/clip.wav",
        _svc_cfg(svc_auto_shift=True, instrumental_volume=-6),
    )
    payload = captured["input"]
    assert payload["target_audio"] == "https://x/clip.wav"
    assert payload["reference_audio"] == "https://cdn/ref.mp3"
    assert payload["auto_shift"] is True
    assert payload["pitch_shift"] == 0
    assert payload["n_steps"] == 32
    assert payload["cfg_scale"] == 3.0
    assert payload["seed"] == 42
    assert payload["instrumental_volume"] == -6
    assert payload["output_format"] == "mp3"


def test_predict_svc_folds_octave_into_manual_shift(monkeypatch: MonkeyPatch) -> None:
    captured = _patch_svc(monkeypatch)
    replicate.predict_svc(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/clip.wav",
        _svc_cfg(pitch=2, pitch_mode="male-to-female"),
    )
    payload = captured["input"]
    assert payload["auto_shift"] is False
    assert payload["pitch_shift"] == 14


def test_predict_svc_clamps_knobs(monkeypatch: MonkeyPatch) -> None:
    captured = _patch_svc(monkeypatch)
    replicate.predict_svc(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/clip.wav",
        _svc_cfg(svc_n_steps=999, svc_cfg=99.0, svc_seed=-5),
    )
    payload = captured["input"]
    assert payload["n_steps"] == 64
    assert payload["cfg_scale"] == 8.0
    assert payload["seed"] == 0


def test_predict_svc_requires_a_reference(monkeypatch: MonkeyPatch) -> None:
    captured = _patch_svc(monkeypatch)
    with pytest.raises(ClientSongError):
        replicate.predict_svc(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/clip.wav",
            _svc_cfg(voice_model_url=""),
        )
    assert captured == {}, "a missing reference must fail before calling the API"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("ValueError: REFERENCE_DOWNLOAD_FAILED 404", "HTTP 404"),
        ("REFERENCE_TOO_SHORT", "5–30"),
        ("REFERENCE_NO_VOCAL", "没有检测到人声"),
        ("TARGET_NO_VOCAL", "这段歌曲"),
        ("INVALID_AUDIO", "无法解码"),
        ("downloading reference_audio failed: HTTP 404", "参考音频"),
    ],
)
def test_predict_svc_failure_tokens_become_client_errors(
    monkeypatch: MonkeyPatch, failure: str, expected: str
) -> None:
    _patch_svc(monkeypatch, {"status": "failed", "error": failure, "logs": ""})
    with pytest.raises(ClientSongError) as excinfo:
        replicate.predict_svc(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/clip.wav",
            _svc_cfg(),
        )
    assert expected in str(excinfo.value)


def test_predict_svc_unknown_failure_stays_runtime_error(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_svc(monkeypatch, {"status": "failed", "error": "CUDA out of memory", "logs": ""})
    with pytest.raises(RuntimeError) as excinfo:
        replicate.predict_svc(
            "https://api.replicate.com/v1",
            "r8_test",
            "https://x/clip.wav",
            _svc_cfg(),
        )
    assert not isinstance(excinfo.value, ClientSongError)


def _patch_render(monkeypatch: MonkeyPatch, captured: dict[str, Any]) -> None:
    def fake_download(url: str, workdir: Path) -> tuple[Path, str, float]:
        source = workdir / "source.mp3"
        source.write_bytes(b"src")
        return source, "title", 90.0

    def fake_trim(source: Path, target: Path, start: int, duration: int) -> None:
        target.write_bytes(b"clip")

    def fake_upload(base: str, token: str, path: Path) -> str:
        return "https://replicate.delivery/clip.wav"

    def fake_svc(base: str, token: str, audio: str, cfg: SingConfig) -> str:
        captured["audio"] = audio
        captured["cfg"] = cfg
        return "https://replicate.delivery/svc.mp3"

    def fake_cover(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("an svc_ref voice must not use the RVC backend")

    def fake_fetch(url: str, workdir: Path) -> Path:
        generated = workdir / "generated.mp3"
        generated.write_bytes(b"gen")
        return generated

    monkeypatch.setattr(service.netease, "is_netease_url", lambda url: False)
    monkeypatch.setattr(service.bilibili, "download_audio", fake_download)
    monkeypatch.setattr(service.media, "trim_audio", fake_trim)
    monkeypatch.setattr(service.replicate, "upload_file", fake_upload)
    monkeypatch.setattr(service.replicate, "predict_svc", fake_svc)
    monkeypatch.setattr(service.replicate, "predict_cover", fake_cover)
    monkeypatch.setattr(service.media, "fetch_output", fake_fetch)


def test_render_song_dispatches_to_svc(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_render(monkeypatch, captured)
    cfg = _svc_cfg(cache_root=tmp_path)
    result = service.render_song("https://www.bilibili.com/video/BV1", cfg)

    assert result.audio_url == "https://replicate.delivery/svc.mp3"
    assert result.engine == SVC_ENGINE
    assert captured["audio"] == "https://replicate.delivery/clip.wav"
    assert captured["cfg"].voice_model_url == "https://cdn/ref.mp3"


def test_svc_auto_pitch_skips_the_gender_classifier(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    _patch_render(monkeypatch, captured)

    def forbid_classifier(*args: Any, **kwargs: Any) -> tuple[int, bool]:
        raise AssertionError("SoulX resolves the key from F0 medians")

    monkeypatch.setattr(service.pitch, "resolve_pitch", forbid_classifier)
    cfg = replace(_svc_cfg(cache_root=tmp_path), pitch_mode=AUTO_PITCH_MODE)
    result = service.render_song("https://www.bilibili.com/video/BV1", cfg)

    assert result.pitch_auto is True
    assert result.pitch == 0
    assert captured["cfg"].svc_auto_shift is True
    assert captured["cfg"].pitch_mode == "no-change"
