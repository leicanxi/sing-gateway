"""Music source dispatch in the singing service."""

from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from sing_gateway import bilibili, netease, service
from sing_gateway.config import ClientSongError, SingConfig, SongCandidate


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
