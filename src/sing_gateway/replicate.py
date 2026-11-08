"""Minimal Replicate client for the AICoverGen voice-conversion model."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from sing_gateway.config import (
    PITCH_MODES,
    VOLUME_MAX,
    VOLUME_MIN,
    ClientSongError,
    SingConfig,
)

logger = logging.getLogger(__name__)

_VOICE_DOWNLOAD_MARKER = "downloading voice model"
_HTTP_STATUS_RE = re.compile(r"HTTP(?: Error)? (\d{3})")


def _voice_download_status(error: str, logs: str) -> int | None:
    """HTTP status when AICoverGen could not fetch the custom voice zip.

    The model downloads ``custom_rvc_model_download_url`` with urllib before it
    touches the song, so a dead or private link fails the prediction with a
    bare ``HTTP Error 404/401`` that means nothing to end users.
    """
    if _VOICE_DOWNLOAD_MARKER not in logs.casefold():
        return None
    match = _HTTP_STATUS_RE.search(error) or _HTTP_STATUS_RE.search(logs[-1500:])
    return int(match.group(1)) if match else None


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def upload_file(base_url: str, token: str, path: Path) -> str:
    with httpx.Client(timeout=180.0) as client, path.open("rb") as handle:
        response = client.post(
            f"{base_url}/files",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "content": (
                    path.name,
                    handle,
                    "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg",
                )
            },
        )
    response.raise_for_status()
    url = (response.json().get("urls") or {}).get("get")
    if not url:
        raise RuntimeError("replicate file upload returned no url")
    return str(url)


def _create_prediction(
    client: httpx.Client,
    base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str:
    for _ in range(8):
        response = client.post(f"{base_url}/predictions", json=payload, headers=headers)
        if response.status_code == 429:
            wait = int(response.headers.get("retry_after") or 10)
            logger.info("replicate throttled, waiting %ss", wait)
            time.sleep(wait + 2)
            continue
        response.raise_for_status()
        return str(response.json()["id"])
    raise RuntimeError("replicate prediction stayed rate-limited")


def predict_cover(base_url: str, token: str, audio_url: str, cfg: SingConfig) -> str:
    """Run the cover model and return the generated audio URL."""
    version = cfg.model_version.strip()
    timeout = float(cfg.prediction_timeout)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pitch_mode = cfg.pitch_mode if cfg.pitch_mode in PITCH_MODES else "no-change"
    # AICoverGen transposes vocals-only for pitch_change and the whole mix for
    # pitch_change_all. Sending the octave through pitch_change would leave the
    # accompaniment in the old key, so fold both into one whole-mix shift.
    octaves = {"male-to-female": 1, "female-to-male": -1}.get(pitch_mode, 0)
    total_pitch = _clamp_int(cfg.pitch + octaves * 12, -24, 24)
    payload_input = {
        "song_input": audio_url,
        "rvc_model": "CUSTOM",
        "custom_rvc_model_download_url": cfg.voice_model_url,
        "pitch_change": "no-change",
        "pitch_change_all": total_pitch,
        "index_rate": _clamp_float(cfg.index_rate, 0.0, 1.0),
        "filter_radius": _clamp_int(cfg.filter_radius, 0, 7),
        "rms_mix_rate": _clamp_float(cfg.rms_mix_rate, 0.0, 1.0),
        "protect": _clamp_float(cfg.protect, 0.0, 0.5),
        "main_vocals_volume_change": 0,
        "backup_vocals_volume_change": _clamp_int(cfg.backup_vocals_volume, VOLUME_MIN, VOLUME_MAX),
        "instrumental_volume_change": _clamp_int(cfg.instrumental_volume, VOLUME_MIN, VOLUME_MAX),
        "reverb_size": 0.15,
        "reverb_wetness": 0.0,
        "reverb_dryness": 1.0,
        "reverb_damping": 0.7,
        # AICoverGen exports mp3 without a bitrate (ffmpeg's 128 kbps default)
        # and only exposes wav as the alternative. Wav URLs are ~10 MB per
        # minute and QQ voice/file sends fail on them, so delivery stays mp3.
        # Raising this ceiling needs our own inference pipeline.
        "output_format": "mp3",
    }
    with httpx.Client(timeout=120.0, headers=headers) as client:
        if not version:
            response = client.get(f"{base_url}/models/{cfg.model}")
            response.raise_for_status()
            version = str(response.json()["latest_version"]["id"])
        prediction_id = _create_prediction(
            client,
            base_url,
            {"version": version, "input": payload_input},
            headers,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            response = client.get(f"{base_url}/predictions/{prediction_id}")
            response.raise_for_status()
            job = response.json()
            status = str(job.get("status") or "")
            if status == "succeeded":
                output = job.get("output")
                url = output[-1] if isinstance(output, list) and output else output
                if not url:
                    raise RuntimeError("replicate returned no output")
                return str(url)
            if status in {"failed", "canceled"}:
                full_logs = str(job.get("logs") or "")
                error = str(job.get("error") or f"prediction {status}: {full_logs[-800:]}")
                if "out of bounds for axis 0" in error:
                    # The voice zip ships an empty faiss index (ntotal=0);
                    # relays would retry a 502 and burn quota for nothing.
                    raise ClientSongError(
                        "该音色的模型文件损坏（特征索引为空），暂时无法翻唱，换一个音色试试"
                    ) from None
                download_status = _voice_download_status(error, full_logs)
                if download_status is not None:
                    raise ClientSongError(
                        f"该音色的模型文件无法下载（HTTP {download_status}），"
                        "链接可能已失效或不可访问，请换一个音色"
                    ) from None
                raise RuntimeError(error)
    raise RuntimeError("prediction timed out")
