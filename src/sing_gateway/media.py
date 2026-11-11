"""ffmpeg helpers for trimming and normalizing generated audio."""

from __future__ import annotations

import logging
import re
import subprocess
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx

from sing_gateway.bilibili import strip_tags

logger = logging.getLogger(__name__)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", strip_tags(value)).strip("._")
    return (cleaned[:60] or "cover") + ".mp3"


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return str(imageio_ffmpeg.get_ffmpeg_exe())


def trim_audio(source: Path, target: Path, start: int, duration: int) -> None:
    """Cut the clip losslessly.

    The source is already lossy (streamed mp3/m4a), so encoding the clip to mp3
    here would spend another generation of quality before RVC ever hears it.
    ``target`` should be a ``.wav`` path.
    """
    subprocess.run(
        [
            _ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(source),
            "-vn",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )


def to_mp3(source: Path, target: Path, *, bitrate: str = "320k") -> None:
    subprocess.run(
        [
            _ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )


def prepare_reference(source: Path, workdir: Path, *, max_seconds: int = 30) -> tuple[Path, float]:
    """Normalise a submitted reference clip to mono 44.1k mp3.

    Returns the mp3 and its decoded duration. ffmpeg also validates the
    container: a non-audio upload raises ``CalledProcessError`` and the caller
    rejects the submission instead of storing an unusable voice.
    """
    wav = workdir / "reference.wav"
    subprocess.run(
        [
            _ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-t",
            str(max_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    with wave.open(str(wav), "rb") as handle:
        duration = handle.getnframes() / float(handle.getframerate() or 1)
    mp3 = workdir / "reference.mp3"
    to_mp3(wav, mp3, bitrate="192k")
    return mp3, duration


def sniff_audio_suffix(content: bytes, content_type: str, url: str) -> str:
    """Identify the container from magic bytes, not just headers.

    Replicate delivery URLs usually have no extension and sometimes serve
    ``application/octet-stream``, so trusting the header alone would cache a WAV
    under a ``.mp3`` name.
    """
    if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return ".wav"
    if content[:4] in {b"fLaC", b"OggS"}:
        return ".flac" if content[:4] == b"fLaC" else ".ogg"
    if content[:3] == b"ID3":
        return ".mp3"
    if len(content) > 1 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0:
        return ".mp3"
    lowered = (content_type or "").lower()
    if "wav" in lowered:
        return ".wav"
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix or ".mp3"


def fetch_output(output_url: str, workdir: Path) -> Path:
    """Download the generated cover, transcoding non-mp3 output to 320 kbps mp3."""
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        response = client.get(output_url)
        response.raise_for_status()
        content = response.content
        content_type = str(response.headers.get("content-type") or "")
    suffix = sniff_audio_suffix(content, content_type, output_url)
    raw = workdir / f"generated{suffix}"
    raw.write_bytes(content)
    if suffix == ".mp3":
        return raw
    mp3 = workdir / "generated.mp3"
    to_mp3(raw, mp3)
    return mp3
