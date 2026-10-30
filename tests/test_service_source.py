"""Music source dispatch in the singing service."""

from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from sing_gateway import bilibili, netease, service
from sing_gateway.config import ClientSongError, SingConfig, SingResult, SongCandidate


def _candidate(song_id: int, title: str = "song") -> SongCandidate:
    return SongCandidate(
        title=title,
        artist="artist",
        duration_seconds=200,
        url=f"https://music.163.com/song?id={song_id}",
    )


def _patch_search(monkeypatch: MonkeyPatch, rows: list[SongCandidate]) -> None:
    monkeypatch.setattr(service, "search_songs", lambda query, limit, source: rows)


def test_search_songs_dispatches_by_source(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "search_bilibili", lambda query, limit: ["bili"])
    monkeypatch.setattr(netease, "search_netease", lambda query, limit: ["netease"])
    assert service.search_songs("q", 1) == ["bili"]
    assert service.search_songs("q", 1, "bilibili") == ["bili"]
    assert service.search_songs("q", 1, "netease") == ["netease"]


def test_pick_candidate_prefers_full_track_over_vip_trial(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1, "大鱼 (唱片版)"), _candidate(2, "大鱼 Cover")]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(
        netease,
        "track_info",
        lambda url: (True, 30.0, 30.0) if url.endswith("id=1") else (True, 319.0, None),
    )
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: True)
    picked = service._pick_candidate("大鱼", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=2")


def test_pick_candidate_skips_instrumental_uploads(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1, "大鱼（纯音乐版）"), _candidate(2, "大鱼 Cover")]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 319.0, None))
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: True)
    picked = service._pick_candidate("大鱼", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=2")


def test_pick_candidate_skips_preview_without_vocals(monkeypatch: MonkeyPatch) -> None:
    # The reported 大鱼 case: preview covers the requested window, but its first
    # 30s are pure intro, so the next (free) version wins.
    rows = [_candidate(1, "大鱼 (唱片版)"), _candidate(2, "大鱼 Cover")]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(
        netease,
        "track_info",
        lambda url: (True, 30.0, 30.0) if url.endswith("id=1") else (True, 319.0, None),
    )
    monkeypatch.setattr(
        netease, "window_has_lyrics", lambda url, start, duration: not url.endswith("id=1")
    )
    picked = service._pick_candidate("大鱼", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=2")


def test_pick_candidate_skips_full_track_without_vocals_in_window(
    monkeypatch: MonkeyPatch,
) -> None:
    rows = [_candidate(1), _candidate(2)]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 319.0, None))
    monkeypatch.setattr(
        netease, "window_has_lyrics", lambda url, start, duration: not url.endswith("id=1")
    )
    picked = service._pick_candidate("歌", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=2")


def test_pick_candidate_uses_preview_when_it_has_vocals(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1)]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 30.0, 30.0))
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: True)
    picked = service._pick_candidate("歌", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=1")


def test_pick_candidate_accepts_preview_when_lyrics_unknown(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1)]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 30.0, 30.0))
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: None)
    picked = service._pick_candidate("歌", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=1")


def test_pick_candidate_skips_preview_shorter_than_clip(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1)]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 30.0, 30.0))
    monkeypatch.setattr(
        netease, "window_has_lyrics", lambda url, start, duration: pytest.fail("unreachable")
    )
    with pytest.raises(ClientSongError, match="VIP"):
        service._pick_candidate("歌", SingConfig(music_source="netease", duration=60))


def test_pick_candidate_rejects_only_unusable_previews(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1), _candidate(2)]
    _patch_search(monkeypatch, rows)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 30.0, 30.0))
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: False)
    with pytest.raises(ClientSongError, match="VIP"):
        service._pick_candidate("歌", SingConfig(music_source="netease"))


def test_pick_candidate_keeps_first_result_for_bilibili(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1), _candidate(2)]
    _patch_search(monkeypatch, rows)
    picked = service._pick_candidate("大鱼", SingConfig(music_source="bilibili"))
    assert picked.url.endswith("id=1")


def test_pick_candidate_falls_back_when_probe_unavailable(monkeypatch: MonkeyPatch) -> None:
    rows = [_candidate(1)]
    _patch_search(monkeypatch, rows)

    def probe_fails(url: str) -> tuple[bool, float, float | None]:
        raise RuntimeError("network down")

    monkeypatch.setattr(netease, "track_info", probe_fails)
    picked = service._pick_candidate("大鱼", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=1")


class _SearchResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _SearchClient:
    """Minimal fake httpx client: every GET answers the search payload."""

    def __init__(self, songs: list[dict]) -> None:
        self._payload = {"code": 200, "result": {"songs": songs}}

    def __enter__(self) -> _SearchClient:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, url: str, params: dict | None = None, **kwargs: object) -> _SearchResponse:
        return _SearchResponse(self._payload)


def test_pick_candidate_follows_the_source_match_ranking(monkeypatch: MonkeyPatch) -> None:
    """The source's ranking decides: plain 稻香 beats the 深情版 upload."""
    songs = [
        {"id": 1, "name": "稻香(深情版)", "artists": [{"name": "Lucky小爱"}], "duration": 231000},
        {"id": 2, "name": "稻香", "artists": [{"name": "Lie"}], "duration": 196000},
    ]
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _SearchClient(songs))
    ranked = netease.search_netease("稻香", 5)
    _patch_search(monkeypatch, ranked)
    monkeypatch.setattr(netease, "track_info", lambda url: (True, 320.0, None))
    monkeypatch.setattr(netease, "window_has_lyrics", lambda url, start, duration: True)
    picked = service._pick_candidate("稻香", SingConfig(music_source="netease"))
    assert picked.url.endswith("id=2")


def test_render_song_by_query_labels_the_picked_song(monkeypatch: MonkeyPatch) -> None:
    """The block must name the version that was sung, not just the file name."""
    picked = _candidate(1, "稻香")
    monkeypatch.setattr(service, "_pick_candidate", lambda song, cfg: picked)
    monkeypatch.setattr(
        service, "render_song", lambda url, cfg: SingResult("https://cdn/a.mp3", "a.mp3")
    )
    result = service.render_song_by_query("稻香", SingConfig(music_source="netease"))
    assert result.audio_url == "https://cdn/a.mp3"
    assert result.title == "稻香"
    assert result.artist == "artist"
