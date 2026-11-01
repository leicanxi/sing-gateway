"""Types and defaults shared by the singing plugin and gateway."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_VOICE_URL = "https://huggingface.co/leicanxi/rvc-models/resolve/main/keine_genso_flat.zip"
DEFAULT_REPLICATE_BASE = "https://api.replicate.com/v1"
DEFAULT_MODEL = "zsxkib/realistic-voice-cloning"
PITCH_MODES = frozenset({"no-change", "male-to-female", "female-to-male"})
MUSIC_SOURCES = frozenset({"bilibili", "netease"})
# Mixing gains are dB offsets the cover model applies when remixing converted
# vocals with the separated stems: 0 keeps a stem at source loudness, -60 mutes
# it. Positive gains risk clipping and are not exposed.
VOLUME_MIN = -60
VOLUME_MAX = 0


class ClientSongError(RuntimeError):
    """A song-level problem the caller can fix (VIP track, no search results)."""


@dataclass(frozen=True)
class SongCandidate:
    """One Bilibili search result the agent can show or sing."""

    title: str
    artist: str
    duration_seconds: int
    url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration_seconds": self.duration_seconds,
            "url": self.url,
        }


@dataclass(frozen=True)
class SingConfig:
    """Provider-neutral knobs for one cover generation."""

    voice_model_url: str = DEFAULT_VOICE_URL
    model: str = DEFAULT_MODEL
    model_version: str = ""
    replicate_base_url: str = DEFAULT_REPLICATE_BASE
    replicate_token: str = ""
    pitch: int = 2
    pitch_mode: str = "no-change"
    start: int = 60
    duration: int = 25
    music_source: str = "bilibili"
    index_rate: float = 0.75
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect: float = 0.33
    instrumental_volume: int = VOLUME_MIN
    backup_vocals_volume: int = VOLUME_MIN
    prediction_timeout: float = 600.0
    cache_ttl_hours: float = 168.0
    cache_max_entries: int = 50
    cache_root: Path | None = None


@dataclass(frozen=True)
class SingResult:
    audio_url: str
    filename: str
    cached: bool = False
    title: str = ""
    artist: str = ""
    duration_seconds: int = 0

    def as_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "audio",
            "source": {"type": "url", "url": self.audio_url},
            "media_type": "audio/mpeg",
            "filename": self.filename,
            "cached": self.cached,
        }
        if self.duration_seconds > 0:
            block["duration_seconds"] = self.duration_seconds
        # Clients show these so the user can tell which version was sung without
        # listening to the whole clip.
        if self.title:
            block["title"] = self.title
        if self.artist:
            block["artist"] = self.artist
        return block
