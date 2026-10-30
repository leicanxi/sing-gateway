"""NetEase Cloud Music source for short singing clips.

Uses the anonymous web APIs: search returns plain JSON and the player endpoint
issues direct mp3 links for free songs. With ``SING_NCM_API`` set, VIP tracks
are resolved through the unblock sidecar instead; without it they have no
anonymous URL and fail with an explicit error.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from sing_gateway.config import ClientSongError, SongCandidate

logger = logging.getLogger(__name__)

SEARCH_URL = "https://music.163.com/api/search/get"
PLAYER_URL = "https://music.163.com/api/song/enhance/player/url"
LYRIC_URL = "https://music.163.com/api/song/lyric"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}
_SONG_URL_RE = re.compile(r"(?:song\?id=|/song/)(\d+)")
_LYRIC_TIME_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
# LRC files usually carry a timestamped credit block (作词/作曲/编曲 …) before
# the first real line; those are not vocals.
_LYRIC_CREDIT_RE = re.compile(
    r"^(作词|作曲|编曲|制作人|监制|出品|录音|混音|母带|吉他|贝斯|鼓|键盘|和声|弦乐|词|曲|OP|SP)\s*[:：]",
    re.IGNORECASE,
)
_TITLE_NOISE_RE = re.compile(r"[\s\-_·・,，。.、!！?？'\"“”‘’()（）\[\]【】《》]+")
# Decorations that mark a different arrangement rather than the master. Plain
# and 唱片版/原版/原唱-labelled hits are the recording the user asked for, so they
# are deliberately absent here.
_VARIANT_RE = re.compile(
    r"深情|治愈|伤感|史诗|史詩|女声|男声|男生|女生|童声|合唱|和声|钢琴|吉他|清唱|哼唱|"
    r"现场|加速|慢速|抖音|翻唱|伴奏|纯音乐|铃声|片段|串烧|medley|cover|live|remix|dj",
    re.IGNORECASE,
)


def _normalized_title(value: str) -> str:
    return _TITLE_NOISE_RE.sub("", value or "").casefold()


def title_match_score(query: str, title: str) -> float:
    """How well *title* answers *query*: 1.0 for an exact title, 0.2 unrelated.

    NetEase ranks unknown cover, remix and live uploads above the original for
    anonymous searches (稻香 → 稻香(深情版) by an uploader), so the query is
    matched against the title instead of trusting the result order. A title that
    only decorates the query stays usable but ranks below a plain-titled upload.
    """
    wanted = _normalized_title(query)
    found = _normalized_title(title)
    if not wanted or not found:
        return 0.0
    if found == wanted:
        return 1.0
    if found.startswith(wanted):
        base = 0.7
    elif wanted in found:
        base = 0.4
    else:
        base = 0.2
    return max(0.1, base - 0.2) if _VARIANT_RE.search(found) else base


def _proxy() -> str | None:
    return os.environ.get("SING_PROXY", "").strip() or None


def _ncm_base() -> str:
    return os.environ.get("SING_NCM_API", "").strip().rstrip("/")


def is_netease_url(url: str) -> bool:
    return bool(_SONG_URL_RE.search(url or ""))


def _song_id(url: str) -> str:
    match = _SONG_URL_RE.search(url or "")
    if not match:
        raise RuntimeError(f"not a netease song url: {url}")
    return match.group(1)


def search_netease(query: str, limit: int = 3) -> list[SongCandidate]:
    """Search NetEase and return up to ``limit`` candidates, best match first."""
    query = (query or "").strip()
    if not query:
        return []
    with httpx.Client(
        timeout=20.0, headers=HEADERS, follow_redirects=True, proxy=_proxy()
    ) as client:
        response = client.get(SEARCH_URL, params={"s": query, "type": 1, "limit": limit})
        response.raise_for_status()
        payload = response.json()
    if int(payload.get("code") or 200) != 200:
        raise RuntimeError(
            payload.get("message") or f"netease search failed: {payload.get('code')}"
        )
    data = payload.get("result")
    songs = data.get("songs") if isinstance(data, dict) else None
    candidates: list[SongCandidate] = []
    for song in songs if isinstance(songs, list) else []:
        if not isinstance(song, dict):
            continue
        song_id = str(song.get("id") or "").strip()
        title = str(song.get("name") or "").strip()
        if not song_id or not title:
            continue
        artists = song.get("artists") or song.get("ar") or []
        artist = "/".join(
            str(item.get("name") or "")
            for item in artists
            if isinstance(item, dict) and item.get("name")
        )
        duration_ms = song.get("duration") or song.get("dt") or 0
        duration = int(duration_ms) // 1000 if isinstance(duration_ms, (int, float)) else 0
        candidates.append(
            SongCandidate(
                title=title,
                artist=artist,
                duration_seconds=duration,
                url=f"https://music.163.com/song?id={song_id}",
            )
        )
    # Best title match first; ``sort`` is stable, so hits NetEase considers
    # equally relevant keep the order it returned them in.
    candidates.sort(key=lambda candidate: -title_match_score(query, candidate.title))
    return candidates


def _player_row(client: httpx.Client, song_id: str) -> dict[str, Any]:
    """Resolve the play row; prefer the ncm-api unblock sidecar when configured."""
    base = _ncm_base()
    if base:
        try:
            response = client.get(
                f"{base}/song/url/v1",
                # ``unblock`` resolves VIP tracks through the sidecar's
                # third-party sources; without it they only come back as a
                # 30-45s preview clip, which the caller then treats as unusable.
                params={"id": int(song_id), "level": "exhigh", "unblock": "true"},
            )
            response.raise_for_status()
            rows = response.json().get("data")
            row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
            if str(row.get("url") or "").strip():
                return row
        except Exception:
            pass  # fall back to the bare endpoint below
    response = client.get(PLAYER_URL, params={"ids": json.dumps([int(song_id)]), "br": 320000})
    response.raise_for_status()
    rows = response.json().get("data")
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}


def _metadata_seconds(client: httpx.Client, song_id: str) -> float:
    """Track length from the sidecar's detail endpoint, ``0.0`` when unknown.

    Unblocked player rows carry no ``time`` field, so the length has to come
    from metadata; callers skip the start clamp when this returns 0.
    """
    base = _ncm_base()
    if not base:
        return 0.0
    try:
        response = client.get(f"{base}/song/detail", params={"ids": song_id})
        response.raise_for_status()
        songs = response.json().get("songs")
    except Exception:
        logger.warning("netease song detail failed for %s", song_id, exc_info=True)
        return 0.0
    song = songs[0] if isinstance(songs, list) and songs and isinstance(songs[0], dict) else {}
    raw_ms = song.get("dt")
    return float(raw_ms) / 1000.0 if isinstance(raw_ms, (int, float)) else 0.0


def track_info(url: str) -> tuple[bool, float, float | None]:
    """Return ``(has_audio, total_seconds, trial_end_seconds)`` for a song URL.

    ``total_seconds`` is the length of the file that will be downloaded — a VIP
    track is only its ``freeTrialInfo`` clip. ``trial_end_seconds`` is ``None``
    for a full track and the clip end otherwise.
    """
    song_id = _song_id(url)
    with httpx.Client(
        timeout=20.0, headers=HEADERS, follow_redirects=True, proxy=_proxy()
    ) as client:
        row = _player_row(client, song_id)
        has_audio = bool(str(row.get("url") or "").strip())
        trial = row.get("freeTrialInfo")
        trial_end: float | None = None
        if isinstance(trial, dict):
            end = trial.get("end")
            trial_end = float(end) if isinstance(end, (int, float)) else 0.0
        raw_ms = row.get("time")
        total = float(raw_ms) / 1000.0 if isinstance(raw_ms, (int, float)) else 0.0
        if total <= 0 and trial_end:
            total = trial_end
        if total <= 0 and has_audio:
            total = _metadata_seconds(client, song_id)
    return has_audio, total, trial_end


def _parse_lrc(lrc: str) -> list[tuple[float, str]]:
    lines: list[tuple[float, str]] = []
    for raw in lrc.splitlines():
        line = raw.strip()
        match = _LYRIC_TIME_RE.match(line)
        if match is None:
            continue
        timestamp = int(match.group(1)) * 60 + float(match.group(2))
        lines.append((timestamp, line[match.end() :].strip()))
    return lines


def window_has_lyrics(url: str, start: int, duration: int) -> bool | None:
    """Whether a lyric line falls inside ``[start, start + duration]``.

    Covers are cut from a fixed window, so a long intro or instrumental section
    leaves the model without vocals. ``None`` means the lyric timeline is
    unavailable and the clip should not be rejected on this basis.
    """
    song_id = _song_id(url)
    try:
        with httpx.Client(
            timeout=20.0, headers=HEADERS, follow_redirects=True, proxy=_proxy()
        ) as client:
            response = client.get(LYRIC_URL, params={"id": song_id, "lv": 1, "kv": 1, "tv": -1})
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.warning("netease lyric fetch failed for %s", song_id, exc_info=True)
        return None
    if payload.get("pureMusic") or payload.get("nolyric"):
        return False
    lrc = str((payload.get("lrc") or {}).get("lyric") or "")
    if not lrc.strip():
        return None
    end = start + duration
    for timestamp, text in _parse_lrc(lrc):
        if not text or _LYRIC_CREDIT_RE.match(text):
            continue
        if start <= timestamp <= end:
            return True
    return False


def download_audio(url: str, workdir: Path) -> tuple[Path, str, float]:
    """Download the mp3 stream for a NetEase song URL into *workdir*."""
    song_id = _song_id(url)
    with httpx.Client(
        timeout=60.0, headers=HEADERS, follow_redirects=True, proxy=_proxy()
    ) as client:
        row = _player_row(client, song_id)
        direct = str(row.get("url") or "").strip()
        if not direct:
            raise ClientSongError(
                "网易云没有返回音频直链：该歌曲可能需要 VIP/数字专辑，或接口被风控，请换一首免费歌曲"
            )
        trial = row.get("freeTrialInfo")
        if isinstance(trial, dict) and isinstance(trial.get("end"), (int, float)):
            # Trial files contain only the clip, not the full track.
            total_seconds = float(trial["end"])
        else:
            raw_ms = row.get("time")
            total_seconds = float(raw_ms) / 1000.0 if isinstance(raw_ms, (int, float)) else 0.0
        if total_seconds <= 0:
            total_seconds = _metadata_seconds(client, song_id)
        audio = client.get(direct)
        audio.raise_for_status()
    target = workdir / "source.mp3"
    target.write_bytes(audio.content)
    return target, f"netease-{song_id}", total_seconds
