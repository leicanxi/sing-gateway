"""Orchestrate search, clip extraction, cover generation and caching."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from sing_gateway import bilibili, cache, media, netease, pitch, qqmusic, replicate, titles
from sing_gateway.config import (
    AUTO_PITCH_MODE,
    AUTO_SOURCE,
    AUTO_SOURCE_ORDER,
    MUSIC_SOURCES,
    PITCH_MODES,
    VOLUME_MAX,
    VOLUME_MIN,
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
    mode = cfg.pitch_mode if cfg.pitch_mode in PITCH_MODES else "no-change"
    if cfg.pitch_mode == AUTO_PITCH_MODE:
        mode = AUTO_PITCH_MODE
    return replace(
        cfg,
        start=max(0, min(3600, int(cfg.start))),
        duration=max(5, min(600, int(cfg.duration))),
        pitch=max(-24, min(24, int(cfg.pitch))),
        pitch_mode=mode,
        music_source=cfg.music_source if cfg.music_source in MUSIC_SOURCES else "bilibili",
        index_rate=max(0.0, min(1.0, float(cfg.index_rate))),
        filter_radius=max(0, min(7, int(cfg.filter_radius))),
        rms_mix_rate=max(0.0, min(1.0, float(cfg.rms_mix_rate))),
        protect=max(0.0, min(0.5, float(cfg.protect))),
        instrumental_volume=max(VOLUME_MIN, min(VOLUME_MAX, int(cfg.instrumental_volume))),
        backup_vocals_volume=max(VOLUME_MIN, min(VOLUME_MAX, int(cfg.backup_vocals_volume))),
        prediction_timeout=max(30.0, float(cfg.prediction_timeout)),
        cache_ttl_hours=max(0.0, float(cfg.cache_ttl_hours)),
        cache_max_entries=max(0, min(5000, int(cfg.cache_max_entries))),
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
    if source == AUTO_SOURCE:
        # The confirm step asks one service; ``_pick_candidate`` does the real
        # playability probing later, so the first non-empty list is enough.
        last_error: Exception | None = None
        for candidate_source in AUTO_SOURCE_ORDER:
            try:
                results = search_songs(query, limit, candidate_source)
            except Exception as exc:  # noqa: BLE001 - try the next source
                last_error = exc
                continue
            if results:
                return results
        if last_error is not None:
            raise last_error
        return []
    if source == "netease":
        return netease.search_netease(query, limit)
    if source == "qq":
        return qqmusic.search_qq(query, limit)
    return bilibili.search_bilibili(query, limit)


def render_song(url: str, cfg: SingConfig, artist: str = "") -> SingResult:
    """Generate one short cover for an already-resolved Bilibili/audio URL.

    Cache hits only re-upload the cached mp3 to Replicate Files, so they return
    a fresh public URL in about a second without running the model.
    """
    cfg = _normalized(cfg)
    pitch_auto = False
    if cfg.pitch_mode == AUTO_PITCH_MODE:
        semitones, pitch_auto = pitch.resolve_pitch(
            artist, cfg.voice_label, cfg.voice_gender, cfg.pitch
        )
        # Resolve to a concrete whole-mix shift: the model never sees "auto".
        cfg = replace(cfg, pitch=semitones, pitch_mode="no-change")
        logger.info(
            "auto pitch %+d semitones (artist=%r, voice=%r, resolved=%s)",
            semitones,
            artist,
            cfg.voice_label,
            pitch_auto,
        )
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
                pitch=cfg.pitch,
                pitch_auto=pitch_auto,
            )
        logger.info("sing cache entry has no playable url; regenerating %s", key)
        audio.unlink(missing_ok=True)
        audio.with_suffix(".json").unlink(missing_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="octop-sing-"))
    try:
        if netease.is_netease_url(url):
            source, title, total = netease.download_audio(url, workdir)
        elif qqmusic.is_qq_url(url):
            source, title, total = qqmusic.download_audio(url, workdir)
        else:
            source, title, total = bilibili.download_audio(url, workdir)
        start = cfg.start
        clip_seconds = cfg.duration
        if total > 0:
            start = min(start, max(0, int(total) - cfg.duration - 1))
            clip_seconds = min(cfg.duration, max(0, int(total) - start)) or cfg.duration
        clip = workdir / "clip.wav"
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
    return SingResult(
        output_url,
        filename,
        cached=False,
        duration_seconds=clip_seconds,
        pitch=cfg.pitch,
        pitch_auto=pitch_auto,
    )


@dataclass(frozen=True)
class _Pick:
    """A chosen recording plus how it relates to the requested original."""

    candidate: SongCandidate
    match: str = ""
    original_artist: str = ""


def _artist_names(value: str) -> set[str]:
    return {part.strip().casefold() for part in re.split(r"[/、,&，]", value or "") if part.strip()}


def _same_artist(left: str, right: str) -> bool:
    names = _artist_names(left)
    return bool(names) and bool(names & _artist_names(right))


def _rank_candidates(
    candidates: list[SongCandidate], strict: bool
) -> tuple[list[SongCandidate], SongCandidate | None]:
    """Order hits by how likely they are the recording the user asked for.

    The best title match defines the reference singer and length. Same-artist
    hits come first; a clean-titled upload by someone else next (usually a
    re-upload of the original); decorated titles (live, cover, piano …) last.
    AI-cover uploads and instrumentals are dropped outright: the first would
    compound artifacts, the second has no vocal to convert.
    """
    usable = [
        candidate
        for candidate in candidates
        if not titles.is_ai_cover_title(candidate.title)
        and not any(hint in candidate.title.lower() for hint in _INSTRUMENTAL_TITLE_HINTS)
    ]
    if not usable:
        return [], None
    reference = usable[0]
    reference_duration = reference.duration_seconds

    def key(candidate: SongCandidate) -> tuple[int, int]:
        if candidate is reference or _same_artist(reference.artist, candidate.artist):
            tier = 0
        elif titles.is_variant_title(candidate.title):
            tier = 2
        else:
            tier = 1
        gap = 0
        if reference_duration > 0 and candidate.duration_seconds > 0:
            gap = abs(candidate.duration_seconds - reference_duration)
        return tier, gap

    ranked = sorted(usable, key=key)
    if strict:
        ranked = [
            candidate
            for candidate in ranked
            if candidate is reference or _same_artist(reference.artist, candidate.artist)
        ]
    return ranked, reference


def _match_info(
    source: str, reference: SongCandidate | None, chosen: SongCandidate
) -> tuple[str, str]:
    if source == "bilibili" or reference is None or not reference.artist:
        return "unknown", ""
    if chosen is reference or _same_artist(reference.artist, chosen.artist):
        return "same-artist", ""
    return "other-artist", reference.artist


def _pick_from_source(song: str, cfg: SingConfig, source: str) -> _Pick:
    """Pick a usable hit from one source, or raise ``ClientSongError``."""
    probing = source in {"netease", "qq"}
    candidates = search_songs(song, 5 if probing else 1, source)
    if not candidates:
        raise ClientSongError(f"no song found for {song!r}")
    ranked, reference = _rank_candidates(candidates, cfg.strict_source)
    if not ranked:
        if cfg.strict_source:
            raise ClientSongError("只找到其他歌手的免费版本（已开启严格模式）")
        raise ClientSongError(f"{source} 只返回了伴奏或 AI 翻唱版本，没有可用的演唱录音")
    if source == "qq":
        chosen = _pick_qq_candidate(ranked, cfg)
    elif source == "netease":
        chosen = _pick_netease_candidate(ranked, cfg)
    else:
        chosen = ranked[0]
    match, original = _match_info(source, reference, chosen)
    return _Pick(chosen, match, original)


def _pick_netease_candidate(candidates: list[SongCandidate], cfg: SingConfig) -> SongCandidate:
    preview_fallback: SongCandidate | None = None
    probed = False
    for candidate in candidates:
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


def _pick_candidate(song: str, cfg: SingConfig) -> _Pick:
    """Pick the best-matching search hit whose window actually contains singing.

    Covers are generated from a fixed ``start`` window. NetEase VIP tracks
    resolve to a short preview clip starting at 0s, and long intros or
    instrumental sections leave the window without vocals — the model then
    turns separation bleed into noise. Hits are ranked first (same singer, then
    clean same-title uploads, then decorated versions) and probed in that order.

    ``source=auto`` tries :data:`AUTO_SOURCE_ORDER` and keeps the first source
    that yields a usable recording, so a VIP-only entry on one service can still
    be sung from a free copy on another.
    """
    if cfg.music_source != AUTO_SOURCE:
        return _pick_from_source(song, cfg, cfg.music_source)
    reasons: list[str] = []
    for source in AUTO_SOURCE_ORDER:
        try:
            pick = _pick_from_source(song, cfg, source)
        except ClientSongError as exc:
            reasons.append(f"{source}: {exc}")
        except Exception as exc:  # noqa: BLE001 - try the next source
            logger.warning("auto source %s failed", source, exc_info=True)
            reasons.append(f"{source}: {exc}")
        else:
            if source != AUTO_SOURCE_ORDER[0]:
                logger.info("auto source picked %s for %r", source, song)
            return pick
    raise ClientSongError("没有找到可翻唱的版本（" + "；".join(reasons) + "）")


def _pick_qq_candidate(candidates: list[SongCandidate], cfg: SingConfig) -> SongCandidate:
    """Return the first ranked QQ hit with a stream and singing in the window."""
    probed = False
    for candidate in candidates:
        try:
            playable = qqmusic.can_play(candidate.url)
        except Exception:
            logger.warning("qq probe failed for %s", candidate.url, exc_info=True)
            continue
        probed = True
        if not playable:
            continue
        total = candidate.duration_seconds
        if total > 0:
            start = min(cfg.start, max(0, total - cfg.duration - 1))
            if total - start < cfg.duration:
                continue
            if qqmusic.window_has_lyrics(candidate.url, start, cfg.duration) is False:
                continue
        return candidate
    if not probed:
        # Every probe failed at the network level: let download_audio report it.
        return candidates[0]
    raise ClientSongError(
        "QQ 音乐没有找到可翻唱的版本（VIP/数字专辑或指定时间段内没有歌词）；"
        "可配置 SING_QQ_COOKIES 用已登录账号解锁，或换一首免费歌曲/调整 start"
    )


def render_song_by_query(song: str, cfg: SingConfig) -> SingResult:
    """Search for *song* and generate a cover from the best-matching result."""
    pick = _pick_candidate(song, cfg)
    # The artist doubles as the pitch_mode=auto source-gender hint.
    result = render_song(pick.candidate.url, cfg, artist=pick.candidate.artist)
    # Carry the picked title/artist so clients can show which version was used,
    # and whether it is the requested singer or a free stand-in.
    return replace(
        result,
        title=pick.candidate.title,
        artist=pick.candidate.artist,
        source_match=pick.match,
        original_artist=pick.original_artist,
    )
