"""Automatic key selection and the lossless clip path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from sing_gateway import media, pitch, replicate, service
from sing_gateway.config import AUTO_PITCH_MODE, SingConfig, SongCandidate


@pytest.fixture(autouse=True)
def _isolated_gender_cache(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GENDER_CACHE_FILE", str(tmp_path / "genders.json"))
    monkeypatch.delenv("SING_GENDER_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SING_GENDER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SING_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("SING_REVIEW_API_KEY", raising=False)
    monkeypatch.setattr(pitch, "_cache", {"artists": {}, "voices": {}})
    monkeypatch.setattr(pitch, "_cache_stamp", None)


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("female", "female", 0),
        ("male", "male", 0),
        ("male", "female", 12),
        ("female", "male", -12),
        ("", "female", None),
        ("male", "unknown", None),
    ],
)
def test_semitones_for(source: str, target: str, expected: int | None) -> None:
    assert pitch.semitones_for(source, target) == expected


def test_gender_cache_is_hand_editable(tmp_path: Path) -> None:
    target = pitch.gender_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"artists": {"杨丞琳": "女"}, "voices": {"Keine": "female"}}),
        encoding="utf-8",
    )
    assert pitch.artist_gender("杨丞琳") == "female"
    assert pitch.voice_gender("keine") == "female"


def test_llm_verdict_is_cached_to_disk(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "female"}}]}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        calls.append(url)
        return _Response()

    monkeypatch.setenv("SING_GENDER_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("SING_GENDER_LLM_API_KEY", "k")
    monkeypatch.setattr(pitch.httpx, "post", fake_post)

    assert pitch.artist_gender("Some Artist") == "female"
    assert pitch.artist_gender("Some Artist") == "female"
    assert len(calls) == 1, "the second lookup must come from the cache"

    stored = json.loads((tmp_path / "genders.json").read_text(encoding="utf-8"))
    assert stored["artists"]["some artist"] == "female"


def test_llm_answer_parsing_prefers_female() -> None:
    # "female" contains "male"; a naive substring check would misclassify it.
    assert pitch._parse_answer("Female") == "female"
    assert pitch._parse_answer("male") == "male"
    assert pitch._parse_answer("女") == "female"
    assert pitch._parse_answer("不确定") == ""


def test_resolve_pitch_uses_declared_voice_gender() -> None:
    target = pitch.gender_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"artists": {"男歌手": "male"}}), encoding="utf-8")

    semitones, resolved = pitch.resolve_pitch("男歌手", "Some Voice", "female", 2)
    assert (semitones, resolved) == (12, True)


def test_resolve_pitch_falls_back_when_unknown() -> None:
    semitones, resolved = pitch.resolve_pitch("Whoever", "Some Voice", "", 2)
    assert (semitones, resolved) == (2, False)


def test_label_gender_beats_a_machine_verdict() -> None:
    target = pitch.gender_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"artists": {"band": "male"}, "voices": {"miku (female)": "male"}}),
        encoding="utf-8",
    )
    # A cached/LLM verdict is a machine guess; the label word is deterministic.
    assert pitch.label_gender("Miku (Female) (RVC V2)") == "female"
    assert pitch.resolve_pitch("band", "Miku (Female)", "", 2) == (12, True)


def test_declared_gender_beats_the_label() -> None:
    target = pitch.gender_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"artists": {"band": "male"}}), encoding="utf-8")
    # The operator explicitly marked this voice male; the label says female.
    assert pitch.resolve_pitch("band", "Some Voice (Female)", "male", 2) == (0, True)


def test_gateway_maps_auto_pitch(monkeypatch: MonkeyPatch) -> None:
    from sing_gateway.server import sing

    monkeypatch.setenv("SING_VOICE_URL", "https://x/voice.zip")
    monkeypatch.setenv("SING_PITCH", "2")

    config = sing._config({"pitch_mode": "auto", "pitch": 5})
    assert config.pitch_mode == AUTO_PITCH_MODE
    assert config.pitch == 2, "the caller's pitch is only the fallback in auto mode"

    # Accepting pitch="auto" keeps older clients working when they grow a mode.
    assert sing._config({"pitch": "auto"}).pitch_mode == AUTO_PITCH_MODE


def test_voice_json_declares_gender(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from sing_gateway.voices import load_voices

    voices = tmp_path / "voices.json"
    voices.write_text(
        json.dumps({"miku": {"label": "Miku", "url": "https://x/v.zip", "gender": "女"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_VOICES_FILE", str(voices))
    assert load_voices(voices)["miku"].gender == "female"


def _patch_render(monkeypatch: MonkeyPatch, captured: dict[str, Any]) -> None:
    def fake_download(url: str, workdir: Path) -> tuple[Path, str, float]:
        source = workdir / "source.mp3"
        source.write_bytes(b"src")
        return source, "title", 90.0

    def fake_trim(source: Path, target: Path, start: int, duration: int) -> None:
        assert target.suffix == ".wav", "the clip uploaded to Replicate must be lossless"
        target.write_bytes(b"clip")

    def fake_upload(base: str, token: str, path: Path) -> str:
        assert path.suffix == ".wav"
        return "https://replicate.delivery/clip.wav"

    def fake_predict(base: str, token: str, audio: str, cfg: SingConfig) -> str:
        captured["cfg"] = cfg
        return "https://replicate.delivery/out.mp3"

    def fake_fetch(url: str, workdir: Path) -> Path:
        generated = workdir / "generated.mp3"
        generated.write_bytes(b"gen")
        return generated

    monkeypatch.setattr(service.netease, "is_netease_url", lambda url: False)
    monkeypatch.setattr(service.bilibili, "download_audio", fake_download)
    monkeypatch.setattr(service.media, "trim_audio", fake_trim)
    monkeypatch.setattr(service.replicate, "upload_file", fake_upload)
    monkeypatch.setattr(service.replicate, "predict_cover", fake_predict)
    monkeypatch.setattr(service.media, "fetch_output", fake_fetch)


def test_auto_pitch_is_resolved_before_the_model(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    genders = pitch.gender_cache_path()
    genders.parent.mkdir(parents=True, exist_ok=True)
    genders.write_text(json.dumps({"artists": {"杨丞琳": "female"}}), encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_render(monkeypatch, captured)
    monkeypatch.setattr(
        service,
        "_pick_candidate",
        lambda song, cfg: service._Pick(
            SongCandidate("雨爱", "杨丞琳", 240, "https://x/song"), "same-artist"
        ),
    )

    cfg = SingConfig(cache_root=tmp_path, replicate_token="r8_test", pitch_mode=AUTO_PITCH_MODE)
    result = service.render_song_by_query("雨爱", cfg)

    # Female artist, unknown voice, so auto cannot decide: keep the fallback.
    assert captured["cfg"].pitch == 2
    assert captured["cfg"].pitch_mode == "no-change"
    assert result.pitch_auto is False

    captured.clear()
    genders.write_text(json.dumps({"artists": {"杨丞琳": "female"}}), encoding="utf-8")
    cfg = SingConfig(
        cache_root=tmp_path,
        replicate_token="r8_test",
        pitch_mode=AUTO_PITCH_MODE,
        voice_label="Miku",
        voice_gender="female",
    )
    monkeypatch.setattr(service.pitch, "voice_gender", lambda label: "female")
    result = service.render_song_by_query("雨爱", cfg)

    assert captured["cfg"].pitch == 0
    assert captured["cfg"].pitch_mode == "no-change"
    assert result.pitch == 0
    assert result.pitch_auto is True
    assert result.as_block()["pitch_auto"] is True


def test_auto_pitch_shifts_an_octave_for_cross_gender(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    genders = pitch.gender_cache_path()
    genders.parent.mkdir(parents=True, exist_ok=True)
    genders.write_text(json.dumps({"artists": {"male singer": "male"}}), encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_render(monkeypatch, captured)
    monkeypatch.setattr(
        service,
        "_pick_candidate",
        lambda song, cfg: service._Pick(
            SongCandidate("song", "male singer", 240, "https://x/song"), "same-artist"
        ),
    )

    cfg = SingConfig(
        cache_root=tmp_path,
        replicate_token="r8_test",
        pitch_mode=AUTO_PITCH_MODE,
        voice_label="Miku",
        voice_gender="female",
    )
    result = service.render_song_by_query("song", cfg)

    assert captured["cfg"].pitch == 12
    assert result.pitch == 12
    assert result.pitch_auto is True


def test_payload_folds_octave_mode_into_the_whole_mix(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"id": "pred"}

    class _PollResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"status": "succeeded", "output": ["https://x/out.mp3"]}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> _Response:
            captured.update(kwargs.get("json") or {})
            return _Response()

        def get(self, url: str, **kwargs: Any) -> _PollResponse:
            return _PollResponse()

    monkeypatch.setattr(replicate.httpx, "Client", _Client)
    monkeypatch.setattr(replicate.time, "sleep", lambda seconds: None)

    replicate.predict_cover(
        "https://api.replicate.com/v1",
        "r8_test",
        "https://x/song.wav",
        SingConfig(
            replicate_token="r8_test",
            model_version="v-test",
            pitch=2,
            pitch_mode="male-to-female",
        ),
    )

    payload = captured["input"]
    assert payload["pitch_change"] == "no-change"
    # +12 octave and +2 key offset, applied to vocals and accompaniment alike.
    assert payload["pitch_change_all"] == 14
    assert payload["output_format"] == "mp3"


def test_sniff_audio_suffix_ignores_bad_headers() -> None:
    wav_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8
    assert (
        media.sniff_audio_suffix(wav_header, "application/octet-stream", "https://x/out") == ".wav"
    )
    assert media.sniff_audio_suffix(b"ID3\x04\x00", "", "https://x/out") == ".mp3"
    assert media.sniff_audio_suffix(b"\xff\xfb\x90\x00", "", "https://x/out") == ".mp3"
    assert media.sniff_audio_suffix(b"XXXX", "audio/wav", "https://x/out") == ".wav"
