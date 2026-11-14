"""Minimal Replicate client for the two cover backends.

``predict_cover`` runs AICoverGen with a trained RVC voice zip; ``predict_svc``
runs our SoulX-Singer-SVC Cog with a 5–30s reference clip. Upload, version
lookup and polling are shared; only the input schema and the failure messages
differ.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from sing_gateway.config import (
    PITCH_MODES,
    VOLUME_MAX,
    VOLUME_MIN,
    ClientSongError,
    SingConfig,
)

logger = logging.getLogger(__name__)

# Replicate's edge returns 503 bursts and drops connections while a prediction
# is still healthy; failing the job on the first one throws away a render the
# GPU has already been paid for. Retry transient responses within the overall
# prediction timeout instead.
_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 10
_RETRY_BASE_SECONDS = 2.0
_RETRY_MAX_SECONDS = 60.0

_VOICE_DOWNLOAD_MARKER = "downloading voice model"
_HTTP_STATUS_RE = re.compile(r"HTTP(?: Error)? (\d{3})")
_REFERENCE_DOWNLOAD_RE = re.compile(r"REFERENCE_DOWNLOAD_FAILED (\d{3})")
# urllib, which AICoverGen uses to fetch the voice zip, writes the HTTP request
# line as ASCII. ModelScope/Hugging Face keep the uploaded file's Chinese name
# in the path, so the download dies with a UnicodeEncodeError before the model
# runs. Both hosts accept the percent-encoded form; '%' stays safe so an
# already-encoded URL is not encoded twice.
_URL_SAFE = ":/?#[]@!$&'()*+,;=%~-._"


def _ascii_url(url: str) -> str:
    return quote(url.strip(), safe=_URL_SAFE)


class _PredictionFailed(RuntimeError):
    """A terminal Replicate job; callers turn it into a user-facing error."""

    def __init__(self, error: str, logs: str) -> None:
        super().__init__(error)
        self.error = error
        self.logs = logs


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


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                return min(max(float(raw), 0.0) + 1.0, 120.0)
            except ValueError:
                pass
    return float(min(_RETRY_BASE_SECONDS * (2**attempt), _RETRY_MAX_SECONDS))


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    idempotent: bool = True,
    attempts: int = _RETRY_ATTEMPTS,
    **kwargs: Any,
) -> httpx.Response:
    """Send one request, retrying Replicate's transient failures.

    ``idempotent`` is False for ``POST /predictions``: retrying a read timeout
    there could create a second prediction and bill the render twice, so only
    connection-level failures are retried.
    """
    send = client.get if method.upper() == "GET" else client.post
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = send(url, **kwargs)
        except httpx.TransportError as exc:
            if not idempotent and not isinstance(
                exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
            ):
                raise
            last = exc
            delay = _retry_delay(None, attempt)
            logger.warning(
                "replicate %s %s transport error %r; retrying in %.0fs (%d/%d)",
                method,
                url,
                exc,
                delay,
                attempt + 1,
                attempts,
            )
            time.sleep(delay)
            continue
        if response.status_code in _RETRY_STATUSES:
            last = RuntimeError(f"HTTP {response.status_code}")
            delay = _retry_delay(response, attempt)
            logger.warning(
                "replicate %s %s -> HTTP %d; retrying in %.0fs (%d/%d)",
                method,
                url,
                response.status_code,
                delay,
                attempt + 1,
                attempts,
            )
            time.sleep(delay)
            continue
        return response
    raise RuntimeError(f"replicate {method} {url} failed after {attempts} attempts: {last}") from last


def upload_file(base_url: str, token: str, path: Path) -> str:
    content_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    last: Exception | None = None
    with httpx.Client(timeout=180.0) as client:
        for attempt in range(_RETRY_ATTEMPTS):
            # A failed attempt consumes the handle, so reopen it for the retry.
            with path.open("rb") as handle:
                try:
                    response = client.post(
                        f"{base_url}/files",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"content": (path.name, handle, content_type)},
                    )
                except httpx.TransportError as exc:
                    last = exc
                    delay = _retry_delay(None, attempt)
                    logger.warning(
                        "replicate file upload transport error %r; retrying in %.0fs (%d/%d)",
                        exc,
                        delay,
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                    )
                    time.sleep(delay)
                    continue
            if response.status_code in _RETRY_STATUSES:
                last = RuntimeError(f"HTTP {response.status_code}")
                delay = _retry_delay(response, attempt)
                logger.warning(
                    "replicate file upload -> HTTP %d; retrying in %.0fs (%d/%d)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                )
                time.sleep(delay)
                continue
            response.raise_for_status()
            url = (response.json().get("urls") or {}).get("get")
            if not url:
                raise RuntimeError("replicate file upload returned no url")
            return str(url)
    raise RuntimeError(f"replicate file upload failed after {_RETRY_ATTEMPTS} attempts: {last}") from last


def _create_prediction(
    client: httpx.Client,
    base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str:
    response = _request(
        client,
        "POST",
        f"{base_url}/predictions",
        idempotent=False,
        json=payload,
        headers=headers,
    )
    response.raise_for_status()
    return str(response.json()["id"])


def _model_version(client: httpx.Client, base_url: str, model: str, version: str) -> str:
    if version:
        return version
    response = _request(client, "GET", f"{base_url}/models/{model}")
    response.raise_for_status()
    return str(response.json()["latest_version"]["id"])


def _run_prediction(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    version: str,
    payload_input: dict[str, Any],
    timeout: float,
) -> str:
    prediction_id = _create_prediction(
        client,
        base_url,
        {"version": version, "input": payload_input},
        headers,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(2)
        response = _request(client, "GET", f"{base_url}/predictions/{prediction_id}")
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
            raise _PredictionFailed(error, full_logs)
    raise RuntimeError("prediction timed out")


def _cover_error(failure: _PredictionFailed) -> Exception:
    if "out of bounds for axis 0" in failure.error:
        # The voice zip ships an empty faiss index (ntotal=0); relays would
        # retry a 502 and burn quota for nothing.
        return ClientSongError("该音色的模型文件损坏（特征索引为空），暂时无法翻唱，换一个音色试试")
    download_status = _voice_download_status(failure.error, failure.logs)
    if download_status is not None:
        return ClientSongError(
            f"该音色的模型文件无法下载（HTTP {download_status}），"
            "链接可能已失效或不可访问，请换一个音色"
        )
    return RuntimeError(failure.error)


def predict_cover(base_url: str, token: str, audio_url: str, cfg: SingConfig) -> str:
    """Run the AICoverGen model and return the generated audio URL."""
    timeout = float(cfg.prediction_timeout)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pitch_mode = cfg.pitch_mode if cfg.pitch_mode in PITCH_MODES else "no-change"
    # AICoverGen transposes vocals-only for pitch_change and the whole mix for
    # pitch_change_all. Sending the octave through pitch_change would leave the
    # accompaniment in the old key, so fold both into one whole-mix shift.
    octaves = {"male-to-female": 1, "female-to-male": -1}.get(pitch_mode, 0)
    total_pitch = _clamp_int(cfg.pitch + octaves * 12, -24, 24)
    payload_input = {
        "song_input": _ascii_url(audio_url),
        "rvc_model": "CUSTOM",
        "custom_rvc_model_download_url": _ascii_url(cfg.voice_model_url),
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
        version = _model_version(client, base_url, cfg.model, cfg.model_version.strip())
        try:
            return _run_prediction(
                client, base_url, headers, version, payload_input, timeout
            )
        except _PredictionFailed as failure:
            raise _cover_error(failure) from None


def _svc_error(failure: _PredictionFailed) -> Exception:
    """Map the Cog's stable failure tokens to actionable Chinese messages."""
    text = f"{failure.error}\n{failure.logs}"
    download = _REFERENCE_DOWNLOAD_RE.search(text)
    if download:
        return ClientSongError(
            f"参考音频无法下载（HTTP {download.group(1)}），请重新上传或换一个参考音色"
        )
    if "REFERENCE_TOO_SHORT" in text:
        return ClientSongError("参考音频太短，请上传 5–30 秒的连续清唱")
    if "REFERENCE_NO_VOCAL" in text:
        return ClientSongError("参考音频里没有检测到人声，请换一段单人清唱")
    if "TARGET_NO_VOCAL" in text:
        return ClientSongError("这段歌曲里没有检测到人声，换一段副歌试试")
    if "INVALID_AUDIO" in text:
        return ClientSongError("音频文件无法解码，请换一个文件")
    lowered = text.casefold()
    if "reference_audio" in lowered and ("download" in lowered or "http error" in lowered):
        # Cog downloads inputs before predict(), so this failure has no token.
        return ClientSongError("参考音频无法下载，请重新上传或换一个参考音色")
    return RuntimeError(failure.error)


def predict_svc(base_url: str, token: str, audio_url: str, cfg: SingConfig) -> str:
    """Run the zero-shot SoulX-Singer-SVC Cog with a reference clip."""
    if not cfg.voice_model_url.strip():
        raise ClientSongError("该参考音色没有音频文件，无法翻唱")
    timeout = float(cfg.prediction_timeout)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pitch_mode = cfg.pitch_mode if cfg.pitch_mode in PITCH_MODES else "no-change"
    octaves = {"male-to-female": 1, "female-to-male": -1}.get(pitch_mode, 0)
    manual_pitch = _clamp_int(cfg.pitch + octaves * 12, -24, 24)
    # auto_pitch=auto sets svc_auto_shift instead of resolving semitones; the
    # model then matches registers from the two F0 medians. A non-zero
    # pitch_shift would override that upstream, so force it to zero.
    payload_input = {
        "target_audio": _ascii_url(audio_url),
        "reference_audio": _ascii_url(cfg.voice_model_url),
        "pitch_shift": 0 if cfg.svc_auto_shift else manual_pitch,
        "auto_shift": bool(cfg.svc_auto_shift),
        "n_steps": _clamp_int(cfg.svc_n_steps, 8, 64),
        "cfg_scale": _clamp_float(cfg.svc_cfg, 1.0, 8.0),
        "seed": _clamp_int(cfg.svc_seed, 0, 0xFFFFFFFF),
        "random_seed": bool(cfg.svc_random_seed),
        "instrumental_volume": _clamp_int(cfg.instrumental_volume, VOLUME_MIN, VOLUME_MAX),
        "output_format": "mp3",
    }
    with httpx.Client(timeout=120.0, headers=headers) as client:
        version = _model_version(client, base_url, cfg.svc_model, cfg.svc_model_version.strip())
        try:
            return _run_prediction(
                client, base_url, headers, version, payload_input, timeout
            )
        except _PredictionFailed as failure:
            raise _svc_error(failure) from None
