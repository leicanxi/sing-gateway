"""NetEase source parsing, search mapping and VIP error handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sing_gateway import netease
from sing_gateway.config import ClientSongError


def test_song_url_recognition_and_id() -> None:
    url = "https://music.163.com/song?id=3379716579"
    assert netease.is_netease_url(url)
    assert netease._song_id(url) == "3379716579"
    assert netease._song_id("https://music.163.com/song/123") == "123"
    assert not netease.is_netease_url("https://www.bilibili.com/video/BV1xx411c7mD")
    with pytest.raises(RuntimeError, match="netease"):
        netease._song_id("https://example.com/x")


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, url: str, params: dict | None = None, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(self._payload)


def test_search_netease_parses_songs(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "code": 200,
        "result": {
            "songs": [{"id": 1, "name": "歌", "artists": [{"name": "歌手"}], "duration": 250000}]
        },
    }
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    rows = netease.search_netease("歌", 1)
    assert len(rows) == 1
    assert rows[0].url == "https://music.163.com/song?id=1"
    assert rows[0].artist == "歌手"
    assert rows[0].duration_seconds == 250


def test_title_match_score_ranks_plain_title_above_variants() -> None:
    assert netease.title_match_score("稻香", "稻香") == 1.0
    assert netease.title_match_score("稻香", "《稻香》") == 1.0
    assert netease.title_match_score("稻香", "稻香 (Live)") < 1.0
    assert netease.title_match_score("稻香", "晴天") == 0.2
    assert netease.title_match_score("", "稻香") == 0.0


def test_title_match_score_penalizes_re_recordings() -> None:
    # 深情版 / 女声版 are different arrangements; a plain or 原唱-labelled upload
    # is likelier to be the master the user asked for.
    assert netease.title_match_score("晴天", "晴天 (原唱 周杰伦)") > netease.title_match_score(
        "晴天", "晴天(深情版)"
    )
    assert netease.title_match_score("暖暖", "暖暖") > netease.title_match_score(
        "暖暖", "暖暖（男生版）--Cover梁静茹"
    )


def test_search_netease_ranks_best_match_first(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "code": 200,
        "result": {
            "songs": [
                {"id": 1, "name": "稻香(深情版)", "artists": [{"name": "Lucky小爱"}]},
                {"id": 2, "name": "稻香", "artists": [{"name": "Lie"}]},
                {"id": 3, "name": "晴天", "artists": [{"name": "Jay"}]},
            ]
        },
    }
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    rows = netease.search_netease("稻香", 3)
    assert [row.url.rsplit("=", 1)[-1] for row in rows] == ["2", "1", "3"]


def test_search_netease_keeps_order_for_equal_scores(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "code": 200,
        "result": {
            "songs": [
                {"id": 1, "name": "雨爱", "artists": [{"name": "杨丞琳"}]},
                {"id": 2, "name": "雨爱", "artists": [{"name": "DJ冷冰冰"}]},
            ]
        },
    }
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    rows = netease.search_netease("雨爱", 2)
    assert [row.url.rsplit("=", 1)[-1] for row in rows] == ["1", "2"]


def test_download_vip_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    payload = {"code": 200, "data": [{"id": 1, "url": None, "code": 404}]}
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    with pytest.raises(ClientSongError, match="VIP"):
        netease.download_audio("https://music.163.com/song?id=1", tmp_path)


class _FakeAudioResponse:
    def __init__(self, content: bytes = b"") -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _RoutingClient:
    """Fake httpx client: player endpoints return JSON rows, CDN urls return bytes."""

    def __init__(
        self,
        *,
        sidecar: dict | None,
        bare: dict,
        content: bytes = b"mp3",
        detail: dict | None = None,
    ) -> None:
        self.sidecar = sidecar
        self.bare = bare
        self.content = content
        self.detail = detail
        self.calls: list[str] = []
        self.param_calls: list[tuple[str, dict]] = []

    def __enter__(self) -> _RoutingClient:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(
        self, url: str, params: dict | None = None, **kwargs: object
    ) -> _FakeResponse | _FakeAudioResponse:
        self.calls.append(url)
        self.param_calls.append((url, dict(params or {})))
        if "song/detail" in url:
            if self.detail is None:
                raise RuntimeError("no song detail")
            return _FakeResponse(self.detail)
        if "song/url" in url:
            if self.sidecar is None:
                raise RuntimeError("sidecar down")
            return _FakeResponse(self.sidecar)
        if "player/url" in url:
            return _FakeResponse(self.bare)
        return _FakeAudioResponse(self.content)


def test_download_trial_clip_uses_sidecar(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={
            "code": 200,
            "data": [
                {
                    "id": 7,
                    "url": "http://cdn.example/x.mp3",
                    "time": 269000,
                    "freeTrialInfo": {"start": 0, "end": 45},
                }
            ],
        },
        bare={"code": 200, "data": [{"id": 7, "url": None}]},
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    path, title, total = netease.download_audio("https://music.163.com/song?id=7", tmp_path)
    assert path.read_bytes() == b"mp3"
    assert title == "netease-7"
    assert total == 45.0
    assert any("song/url/v1" in u for u in client.calls)


def test_download_falls_back_to_bare_endpoint(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar=None,
        bare={
            "code": 200,
            "data": [{"id": 7, "url": "http://cdn.example/full.mp3", "time": 200000}],
        },
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    path, title, total = netease.download_audio("https://music.163.com/song?id=7", tmp_path)
    assert total == 200.0
    assert any("player/url" in u for u in client.calls)


def test_track_info_flags_vip_trial(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    payload = {
        "code": 200,
        "data": [
            {
                "id": 1,
                "url": "http://cdn.example/x.mp3",
                "time": 30040,
                "freeTrialInfo": {"end": 30},
            }
        ],
    }
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    assert netease.track_info("https://music.163.com/song?id=1") == (True, 30.04, 30.0)


def test_track_info_reports_full_track(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    payload = {
        "code": 200,
        "data": [{"id": 1, "url": "http://cdn.example/x.mp3", "time": 317000}],
    }
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    assert netease.track_info("https://music.163.com/song?id=1") == (True, 317.0, None)


def test_track_info_reports_missing_audio(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    payload = {"code": 200, "data": [{"id": 1, "url": None}]}
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    assert netease.track_info("https://music.163.com/song?id=1") == (False, 0.0, None)


def test_player_row_asks_sidecar_to_unblock(monkeypatch: MonkeyPatch) -> None:
    """VIP tracks only come back full length when the sidecar is asked to unblock."""
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={"code": 200, "data": [{"id": 7, "url": "http://cdn.example/x.mp3"}]},
        bare={"code": 200, "data": [{"id": 7, "url": None}]},
    )
    row = netease._player_row(client, "7")
    assert row["url"] == "http://cdn.example/x.mp3"
    params = [p for u, p in client.param_calls if "song/url/v1" in u]
    assert params and params[0].get("unblock") == "true"


def test_track_info_falls_back_to_metadata_for_unblocked_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    """Unblocked rows carry no ``time``, so the length comes from /song/detail."""
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={
            "code": 200,
            "data": [
                {
                    "id": 316100,
                    "url": "http://cdn.example/x.flac",
                    "type": "flac",
                    "freeTrialInfo": "null",
                }
            ],
        },
        bare={"code": 200, "data": [{"id": 316100, "url": None}]},
        detail={"code": 200, "songs": [{"id": 316100, "dt": 260480}]},
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    assert netease.track_info("https://music.163.com/song?id=316100") == (True, 260.48, None)


def test_track_info_keeps_trial_length_over_metadata(monkeypatch: MonkeyPatch) -> None:
    """A trial row without ``time`` still reports the clip, not the full song."""
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={
            "code": 200,
            "data": [
                {
                    "id": 7,
                    "url": "http://cdn.example/x.mp3",
                    "freeTrialInfo": {"start": 0, "end": 30},
                }
            ],
        },
        bare={"code": 200, "data": [{"id": 7, "url": None}]},
        detail={"code": 200, "songs": [{"id": 7, "dt": 260480}]},
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    assert netease.track_info("https://music.163.com/song?id=7") == (True, 30.0, 30.0)


def test_track_info_survives_missing_metadata(monkeypatch: MonkeyPatch) -> None:
    """A failed detail lookup degrades to an unknown length, not an exception."""
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={
            "code": 200,
            "data": [{"id": 7, "url": "http://cdn.example/x.flac", "type": "flac"}],
        },
        bare={"code": 200, "data": [{"id": 7, "url": None}]},
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    assert netease.track_info("https://music.163.com/song?id=7") == (True, 0.0, None)


def test_download_unblocked_track_reports_metadata_length(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The caller's start clamp needs a length even for unblocked rows."""
    monkeypatch.setenv("SING_NCM_API", "http://127.0.0.1:3010")
    client = _RoutingClient(
        sidecar={
            "code": 200,
            "data": [{"id": 316100, "url": "http://cdn.example/x.flac", "type": "flac"}],
        },
        bare={"code": 200, "data": [{"id": 316100, "url": None}]},
        detail={"code": 200, "songs": [{"id": 316100, "dt": 260480}]},
    )
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: client)
    path, title, total = netease.download_audio("https://music.163.com/song?id=316100", tmp_path)
    assert path.read_bytes() == b"mp3"
    assert title == "netease-316100"
    assert total == 260.48


def test_window_has_lyrics_ignores_credits_and_long_intro(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    lrc = "[00:00.00] 作词 : 尹约\n[00:43.65]海浪无声将夜幕深深淹没\n[00:50.29]漫过天空"
    monkeypatch.setattr(
        netease.httpx, "Client", lambda **kwargs: _FakeClient({"lrc": {"lyric": lrc}})
    )
    url = "https://music.163.com/song?id=1"
    assert netease.window_has_lyrics(url, 4, 25) is False
    assert netease.window_has_lyrics(url, 40, 25) is True


def test_window_has_lyrics_unknown_without_lrc(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    monkeypatch.setattr(
        netease.httpx, "Client", lambda **kwargs: _FakeClient({"lrc": {"lyric": ""}})
    )
    assert netease.window_has_lyrics("https://music.163.com/song?id=1", 0, 25) is None


def test_window_has_lyrics_rejects_pure_music(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SING_NCM_API", raising=False)
    payload = {"pureMusic": True, "lrc": {"lyric": ""}}
    monkeypatch.setattr(netease.httpx, "Client", lambda **kwargs: _FakeClient(payload))
    assert netease.window_has_lyrics("https://music.163.com/song?id=1", 60, 25) is False
