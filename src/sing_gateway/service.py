"""Orchestrate search, clip extraction, cover generation and caching."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from sing_gateway import bilibili, cache, media, netease, replicate
from sing_gateway.config import (
    MUSIC_SOURCES,
    PITCH_MODES,
    ClientSongError,
    SingConfig,
    SingResult,
    SongCandidate,
)

logger = logging.getLogger(__name__)

# Uploads without a lead vocal make the cover model emit artifacts instead of
# singing, so they are useless as a source even when they are full-length.
_INSTRUMENTAL_TITLE_HINTS = (
    "伴奏",
    "纯音乐",
    "消音",
    "instrumental",
    "karaoke",
    "off vocal",
)


def _normalized(cfg: SingConfig) -> SingConfig:
    return replace(
        cfg,
        start=max(0, min(3600, int(cfg.start))),
        duration=max(5, min(60, int(cfg.duration))),
        pitch=max(-24, min(24, int(cfg.pitch))),
        pitch_mode=cfg.pitch_mode if cfg.pitch_mode in PITCH_MODES else "no-change",
        music_source=cfg.music_source if cfg.music_source in MUSIC_SOURCES else "bilibili",
        index_rate=max(0.0, min(1.0, float(cfg.index_rate))),
        filter_radius=max(0, min(7, int(cfg.filter_radius))),
        rms_mix_rate=max(0.0, min(1.0, float(cfg.rms_mix_rate))),
        protect=max(0.0, min(0.5, float(cfg.protect))),
        prediction_timeout=max(30.0, float(cfg.prediction_timeout)),
        cache_ttl_hours=max(0.0, float(cfg.cache_ttl_hours)),
        cache_max_entries=max(0, min(500, int(cfg.cache_max_entries))),
    )


def _resolve_token(cfg: SingConfig) -> str:
    token = (cfg.replicate_token or os.environ.get("REPLICATE_API_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("Replicate token is not configured")
    return token


def _url_reachable(url: str, timeout: float = 10.0) -> bool:
    """Check that a cached public audio URL still serves before returning it."""
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"Range": "bytes=0-0"}
        ) as client:
            response = client.head(url)
            if response.status_code in (405, 501):
                response = client.get(url)
            return response.status_code < 400
    except Exception:
        return False


def search_songs(query: str, limit: int = 3, source: str = "bilibili") -> list[SongCandidate]:
    """Search the configured music source and return up to ``limit`` candidates."""
    limit = max(1, min(5, int(limit)))
    if source == "netease":
        return netease.search_netease(query, limit)
    return bilibili.search_bilibili(query, limit)


def render_song(url: str, cfg: SingConfig) -> SingResult:
    """Generate one short cover for an already-resolved Bilibili/audio URL.

    Cache hits only re-upload the cached mp3 to Replicate Files, so they return
    a fresh public URL in about a second without running the model.
    """
    cfg = _normalized(cfg)
    token = _resolve_token(cfg)
    base_url = cfg.replicate_base_url.rstrip("/")
    root = cache.cache_root(cfg)
    key = cache.cache_key(url, cfg.start, cfg.duration, cfg)
    cached = cache.cache_lookup(root, key, cfg.cache_ttl_hours)
    if cached is not None:
        audio, meta = cached
        # Hits must return a publicly playable URL: the original delivery link
        # is stored in the cache meta. Replicate Files URLs need auth, and old
        # entries predate the field — both regenerate below.
        public_url = str(meta.get("audio_url") or "").strip()
        if public_url and _url_reachable(public_url):
            logger.info("sing cache hit %s", key)
            return SingResult(
                public_url,
                str(meta.get("filename") or "cover.mp3"),
                True,
                duration_seconds=int(meta.get("duration_seconds") or cfg.duration),
            )
        logger.info("sing cache entry has no playable url; regenerating %s", key)
        audio.unlink(missing_ok=True)
        audio.with_suffix(".json").unlink(missing_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="octop-sing-"))
    try:
        if netease.is_netease_url(url):
            source, title, total = netease.download_audio(url, workdir)
        else:
            source, title, total = bilibili.download_audio(url, workdir)
        start = cfg.start
        clip_seconds = cfg.duration
        if total > 0:
            start = min(start, max(0, int(total) - cfg.duration - 1))
            clip_seconds = min(cfg.duration, max(0, int(total) - start)) or cfg.duration
        clip = workdir / "clip.mp3"
        media.trim_audio(source, clip, start, cfg.duration)
        audio_url = replicate.upload_file(base_url, token, clip)
        output_url = replicate.predict_cover(base_url, token, audio_url, cfg)
        filename = media.safe_filename(title)
        try:
            generated = media.fetch_output(output_url, workdir)
            cache.cache_store(
                root,
                key,
                generated,
                {
                    "filename": filename,
                    "audio_url": output_url,
                    "duration_seconds": clip_seconds,
                },
                cfg.cache_max_entries,
            )
        except Exception:
            logger.warning("sing cache store failed", exc_info=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return SingResult(output_url, filename, cached=False, duration_seconds=clip_seconds)


def _pick_candidate(song: str, cfg: SingConfig) -> SongCandidate:
    """Pick the best-matching search hit whose window actually contains singing.

    Covers are generated from a fixed ``start`` window. NetEase VIP tracks
    resolve to a short preview clip starting at 0s, and long intros or
    instrumental sections leave the window without vocals — the model then
    turns separation bleed into noise. Walk the hits in match order (the source
    ranks them): full tracks win over previews, and any hit whose window has no
    lyric line is skipped.
    """
    candidates = search_songs(song, 5 if cfg.music_source == "netease" else 1, cfg.music_source)
    if not candidates:
        raise ClientSongError(f"no song found for {song!r}")
    if cfg.music_source != "netease":
        return candidates[0]
    preview_fallback: SongCandidate | None = None
    probed = False
    for candidate in candidates:
        if any(hint in candidate.title.lower() for hint in _INSTRUMENTAL_TITLE_HINTS):
            continue
        try:
            has_audio, total, trial_end = netease.track_info(candidate.url)
        except Exception:
            logger.warning("netease probe failed for %s", candidate.url, exc_info=True)
            continue
        probed = True
        if not has_audio:
            continue
        if total > 0:
            start = min(cfg.start, max(0, int(total) - cfg.duration - 1))
            if total - start < cfg.duration:
                continue
            if netease.window_has_lyrics(candidate.url, start, cfg.duration) is False:
                continue
        if trial_end is None:
            return candidate
        preview_fallback = preview_fallback or candidate
    if preview_fallback is not None:
        return preview_fallback
    if not probed:
        return candidates[0]
    raise ClientSongError(
        "网易云没有找到可翻唱的版本（VIP 试听段或指定时间段内没有歌词），"
        "请换一首免费歌曲或调整 start 再试"
    )


def render_song_by_query(song: str, cfg: SingConfig) -> SingResult:
    """Search for *song* and generate a cover from the best-matching result."""
    candidate = _pick_candidate(song, cfg)
    # Carry the picked title/artist so clients can show which version was used.
    return replace(render_song(candidate.url, cfg), title=candidate.title, artist=candidate.artist)
