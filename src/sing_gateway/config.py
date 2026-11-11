"""Types and defaults shared by the singing plugin and gateway."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_VOICE_URL = "https://huggingface.co/leicanxi/rvc-models/resolve/main/keine_genso_flat.zip"
DEFAULT_REPLICATE_BASE = "https://api.replicate.com/v1"
DEFAULT_MODEL = "zsxkib/realistic-voice-cloning"
# Zero-shot reference-clip voice conversion (our own Cog around
# Soul-AILab/SoulX-Singer-SVC). Publish it under the operator's account and
# point SING_SVC_MODEL at it.
DEFAULT_SVC_MODEL = "leicanxi/soulx-singer-svc"
RVC_ENGINE = "rvc"
SVC_ENGINE = "svc_ref"
VOICE_ENGINES = frozenset({RVC_ENGINE, SVC_ENGINE})
# A voice entry whose URL ends in one of these is a reference clip, not a
# trained RVC zip. Explicit ``engine`` in the JSON wins over the suffix.
REFERENCE_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"})
PITCH_MODES = frozenset({"no-change", "male-to-female", "female-to-male"})
# Not a model value: the gateway resolves it to semitones from the song's
# artist and the chosen voice, then sends the model a plain key shift.
AUTO_PITCH_MODE = "auto"
# Search across sources (see AUTO_SOURCE_ORDER) instead of pinning one.
AUTO_SOURCE = "auto"
MUSIC_SOURCES = frozenset({"bilibili", "netease", "qq", AUTO_SOURCE})
# Used when source=auto: the first source that yields a usable recording wins.
AUTO_SOURCE_ORDER = ("qq", "netease", "bilibili")
# Mixing gains are dB offsets the cover model applies when remixing converted
# vocals with the separated stems: 0 keeps a stem at source loudness, -60 mutes
# it, positive values boost it. The model's schema has no bounds; +12 measured
# clean through its output stage (peaks pinned at 0 dBFS, no flat-topped
# samples), so that is the cap we expose.
VOLUME_MIN = -60
VOLUME_MAX = 12


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
    # ``rvc`` downloads voice_model_url as a trained .pth zip. ``svc_ref``
    # treats it as a 5–30s clean reference clip for the zero-shot model.
    voice_engine: str = RVC_ENGINE
    model: str = DEFAULT_MODEL
    model_version: str = ""
    svc_model: str = DEFAULT_SVC_MODEL
    svc_model_version: str = ""
    svc_n_steps: int = 32
    svc_cfg: float = 3.0
    svc_seed: int = 42
    svc_random_seed: bool = False
    # Set when pitch_mode=auto: let SoulX match the reference/target registers
    # from their F0 medians instead of pre-resolving a semitone count.
    svc_auto_shift: bool = False
    replicate_base_url: str = DEFAULT_REPLICATE_BASE
    replicate_token: str = ""
    pitch: int = 2
    pitch_mode: str = "no-change"
    start: int = 60
    duration: int = 25
    music_source: str = "bilibili"
    # Refuse a free recording by another artist when the requested one is paid.
    strict_source: bool = False
    index_rate: float = 0.75
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect: float = 0.33
    instrumental_volume: int = VOLUME_MIN
    backup_vocals_volume: int = VOLUME_MIN
    # Gender of the selected voice ("male"/"female") and the label shown to the
    # gender classifier, used by pitch_mode=auto.
    voice_label: str = ""
    voice_gender: str = ""
    prediction_timeout: float = 1800.0
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
    # Whole-mix semitone shift that was baked into this render, and whether it
    # came from pitch_mode=auto rather than from the caller.
    pitch: int = 0
    pitch_auto: bool = False
    # Which recording the vocal was converted from: "same-artist" (the requested
    # singer), "other-artist" (a free recording by someone else) or "unknown"
    # (Bilibili uploads, where the artist field is the uploader).
    source_match: str = ""
    original_artist: str = ""
    # "rvc" or "svc_ref"; lets the client tell a trained model from a
    # zero-shot reference clip without another lookup.
    engine: str = ""

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
        if self.pitch:
            block["pitch"] = self.pitch
        if self.pitch_auto:
            block["pitch_auto"] = True
        # ``artist`` is the recording actually used; when it differs from the
        # requested original, say so instead of letting the client assume.
        if self.source_match:
            block["source_match"] = self.source_match
        if self.original_artist:
            block["original_artist"] = self.original_artist
        if self.engine:
            block["engine"] = self.engine
        return block
