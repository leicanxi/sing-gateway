"""QQ Music source: anonymous search, free-track playback and lyric windows.

The search, vkey and lyric endpoints answer without login. Free tracks come
back with a ``purl``; VIP/digital-album tracks answer ``104003`` and are
reported as a song-level error, mirroring how the NetEase source handles them.
There is no cookie support yet: a VIP-only catalogue entry simply has no
anonymous stream, so callers should pick a free recording.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import urllib.parse
from pathlib import Path

import httpx

from sing_gateway import lrc
from sing_gateway.config import ClientSongError, SongCandidate
from sing_gateway.titles import title_rank_key

logger = logging.getLogger(__name__)

SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
VKEY_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
DETAIL_URL = "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg"
LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://y.qq.com/",
}
_SONG_URL_RE = re.compile(r"(?:songDetail/|songmid=)([0-9A-Za-z]+)")
# 104003: the account has no playback right (VIP / digital album / region).
_NO_RIGHT = 104003
_AUDIO_SUFFIXES = {".m4a", ".mp3", ".flac", ".aac"}


def _proxy() -> str | None:
    return os.environ.get("SING_PROXY", "").strip() or None


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True, proxy=_proxy())


def is_qq_url(url: str) -> bool:
    return bool(_SONG_URL_RE.search(url or ""))


def _mid(url: str) -> str:
    match = _SONG_URL_RE.search(url or "")
    if not match:
        raise RuntimeError(f"not a qq music song url: {url}")
    return match.group(1)


def search_qq(query: str, limit: int = 3) -> list[SongCandidate]:
    """Search QQ Music and return up to ``limit`` candidates, best match first."""
    query = (query or "").strip()
    if not query:
        return []
    with _client() as client:
        response = client.get(
            SEARCH_URL,
            params={"w": query, "format": "json", "n": limit, "p": 1, "new_json": 1, "cr": 1},
        )
        response.raise_for_status()
        payload = response.json()
    if int(payload.get("code") or 0) != 0:
        raise RuntimeError(
            payload.get("message") or f"qq music search failed: {payload.get('code')}"
        )
    rows = ((payload.get("data") or {}).get("song") or {}).get("list") or []
    candidates: list[SongCandidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("mid") or "").strip()
        title = str(row.get("name") or row.get("title") or "").strip()
        if not mid or not title:
            continue
        singers = row.get("singer") or []
        artist = "/".join(
            str(item.get("name") or "")
            for item in singers
            if isinstance(item, dict) and item.get("name")
        )
        interval = row.get("interval")
        candidates.append(
            SongCandidate(
                title=title,
                artist=artist,
                duration_seconds=int(interval) if isinstance(interval, int | float) else 0,
                url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
            )
        )
    # Best title match first, then the caller's capitalisation; QQ's own order
    # breaks remaining ties (stable sort).
    candidates.sort(key=lambda candidate: title_rank_key(query, candidate.title), reverse=True)
    return candidates[:limit]


def _vkey(client: httpx.Client, mid: str) -> tuple[str, int]:
    """Return ``(playable_url, result_code)`` for one song mid."""
    guid = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
    request = {
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": guid,
                "songmid": [mid],
                "songtype": [0],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        },
        "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
    }
    response = client.get(
        VKEY_URL,
        params={
            "format": "json",
            "data": json.dumps(request, separators=(",", ":")),
        },
    )
    response.raise_for_status()
    payload = response.json()
    data = ((payload.get("req_0") or {}).get("data")) or {}
    rows = data.get("midurlinfo") or [{}]
    row = rows[0] if isinstance(rows[0], dict) else {}
    purl = str(row.get("purl") or "").strip()
    result = int(row.get("result") or 0)
    if not purl:
        return "", result
    if purl.startswith("http://") or purl.startswith("https://"):
        return purl, result
    sips = [str(item) for item in (data.get("sip") or []) if str(item).strip()]
    # Prefer an https CDN when the list offers one.
    sip = next((item for item in sips if item.startswith("https://")), sips[0] if sips else "")
    return f"{sip}{purl}", result


def can_play(url: str) -> bool:
    """Whether the anonymous vkey endpoint issues a stream for this song."""
    with _client() as client:
        playable, _ = _vkey(client, _mid(url))
    return bool(playable)


def _detail(client: httpx.Client, mid: str) -> tuple[str, float]:
    try:
        response = client.get(
            DETAIL_URL, params={"songmid": mid, "format": "json", "platform": "yqq"}
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
        row = rows[0] if isinstance(rows, list) and rows else {}
        title = str(row.get("name") or row.get("title") or "").strip()
        interval = row.get("interval")
        total = float(interval) if isinstance(interval, int | float) else 0.0
        return title, total
    except Exception:
        logger.info("qq detail lookup failed for %s", mid, exc_info=True)
        return "", 0.0


def window_has_lyrics(url: str, start: int, duration: int) -> bool | None:
    """Whether a sung line falls inside ``[start, start + duration]``."""
    mid = _mid(url)
    try:
        with _client() as client:
            response = client.get(
                LYRIC_URL, params={"songmid": mid, "format": "json", "nobase64": 1}
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.warning("qq lyric fetch failed for %s", mid, exc_info=True)
        return None
    if int(payload.get("retcode") or 0) != 0:
        return None
    lyric = str(payload.get("lyric") or "")
    if not lyric.strip():
        return None
    end = start + duration
    for timestamp, text in lrc.parse_lrc(lyric):
        if not text or lrc.is_credit(text):
            continue
        # The first line is usually "歌名 - 歌手", not a lyric.
        if timestamp <= 15 and " - " in text:
            continue
        if start <= timestamp <= end:
            return True
    return False


def download_audio(url: str, workdir: Path) -> tuple[Path, str, float]:
    """Download the free m4a stream for a QQ Music song URL into *workdir*."""
    mid = _mid(url)
    with _client() as client:
        audio_url, result = _vkey(client, mid)
        if not audio_url:
            detail = f"（接口返回 {result}）" if result else ""
            raise ClientSongError(
                f"QQ 音乐没有返回音频直链{detail}：该歌曲可能需要 VIP/数字专辑或存在地区限制，"
                "请换一首免费歌曲"
            )
        title, total = _detail(client, mid)
        audio = client.get(audio_url, headers={"Referer": "https://y.qq.com/"})
        audio.raise_for_status()
    suffix = Path(urllib.parse.urlparse(audio_url).path).suffix.lower()
    if suffix not in _AUDIO_SUFFIXES:
        suffix = ".m4a"
    target = workdir / f"source{suffix}"
    target.write_bytes(audio.content)
    return target, title or f"qq-{mid}", total
