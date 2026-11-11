"""QQ Music source: parsing, free/VIP handling and candidate probing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from sing_gateway import qqmusic, service
from sing_gateway.config import ClientSongError, SingConfig, SingResult, SongCandidate


class _Response:
    def __init__(self, payload: dict[str, Any] | None = None, content: bytes = b"") -> None:
        self._payload = payload or {}
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.calls: list[str] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> _Response:
        self.calls.append(url)
        return self._handler(url, params or {})


def _patch_client(monkeypatch: MonkeyPatch, handler: Any) -> _Client:
    client = _Client(handler)
    monkeypatch.setattr(qqmusic, "_client", lambda: client)
    return client


def test_is_qq_url_accepts_detail_and_songmid_links() -> None:
    assert qqmusic.is_qq_url("https://y.qq.com/n/ryqq/songDetail/0039MnYb0qxYhV")
    assert qqmusic.is_qq_url("https://i.y.qq.com/v8/playsong.html?songmid=0039MnYb0qxYhV")
    assert not qqmusic.is_qq_url("https://music.163.com/song?id=1")


def test_search_parses_rows_and_ranks_exact_titles(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "code": 0,
        "data": {
            "song": {
                "list": [
                    {
                        "mid": "aaa",
                        "name": "晴天 (Live)",
                        "singer": [{"name": "周杰伦"}],
                        "interval": 269,
                    },
                    {
                        "mid": "bbb",
                        "name": "晴天",
                        "singer": [{"name": "周杰伦"}, {"name": "某合唱"}],
                        "interval": 270,
                    },
                ]
            }
        },
    }
    _patch_client(monkeypatch, lambda url, params: _Response(payload))

    candidates = qqmusic.search_qq("晴天", 5)

    assert [item.url for item in candidates] == [
        "https://y.qq.com/n/ryqq/songDetail/bbb",
        "https://y.qq.com/n/ryqq/songDetail/aaa",
    ]
    assert candidates[0].title == "晴天"
    assert candidates[0].artist == "周杰伦/某合唱"
    assert candidates[0].duration_seconds == 270


def test_search_prefers_the_capitalisation_the_user_typed(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "code": 0,
        "data": {
            "song": {
                "list": [
                    {"mid": "lower", "name": "greeeen", "singer": [{"name": "x"}], "interval": 200},
                    {
                        "mid": "styled",
                        "name": "GReeeeN",
                        "singer": [{"name": "y"}],
                        "interval": 200,
                    },
                ]
            }
        },
    }
    _patch_client(monkeypatch, lambda url, params: _Response(payload))

    typed = [item.url.rsplit("/", 1)[-1] for item in qqmusic.search_qq("GReeeeN", 5)]
    lower = [item.url.rsplit("/", 1)[-1] for item in qqmusic.search_qq("greeeen", 5)]

    assert typed == ["styled", "lower"]
    assert lower == ["lower", "styled"]


def _vkey_payload(purl: str, result: int = 0) -> dict[str, Any]:
    return {
        "code": 0,
        "req_0": {
            "code": 0,
            "data": {
                "sip": ["http://aqqmusic.tc.qq.com/", "https://sjy6.stream.qqmusic.qq.com/"],
                "midurlinfo": [{"purl": purl, "result": result, "songmid": "bbb"}],
            },
        },
    }


def _vkey_request_mid(params: dict[str, Any]) -> str:
    data = json.loads(params["data"])
    return data["req_0"]["param"]["songmid"][0]


def test_vkey_prefers_https_cdn(monkeypatch: MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        lambda url, params: _Response(_vkey_payload("C400.m4a?guid=1&vkey=x")),
    )
    with qqmusic._client() as client:
        playable, result = qqmusic._vkey(client, "bbb")

    assert result == 0
    assert playable.startswith("https://sjy6.stream.qqmusic.qq.com/")


def test_vip_track_has_no_playable_url(monkeypatch: MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda url, params: _Response(_vkey_payload("", 104003)))
    assert qqmusic.can_play("https://y.qq.com/n/ryqq/songDetail/bbb") is False


def test_parse_netscape_cookies_and_account_uin() -> None:
    text = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.qq.com\tTRUE\t/\tFALSE\t0\tqqmusic_key\tABC\n"
        ".qq.com\tTRUE\t/\tFALSE\t0\tuin\to0123456789\n"
    )
    jar = qqmusic.parse_netscape_cookies(text)

    assert jar == {"qqmusic_key": "ABC", "uin": "o0123456789"}
    assert qqmusic._account_uin(jar) == "123456789"
    assert qqmusic._account_uin({}) == ""


def test_vkey_sends_the_logged_in_uin(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text(
        "# Netscape HTTP Cookie File\n"
        ".qq.com\tTRUE\t/\tFALSE\t0\tqqmusic_key\tABC\n"
        ".qq.com\tTRUE\t/\tFALSE\t0\tuin\to0123456789\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_QQ_COOKIES", str(cookies))
    monkeypatch.setattr(qqmusic, "_cookie_stamp", None)

    captured: dict[str, Any] = {}

    def handler(url: str, params: dict[str, Any]) -> _Response:
        captured.update(json.loads(params["data"]))
        return _Response(_vkey_payload("C400.m4a?guid=1&vkey=x"))

    _patch_client(monkeypatch, handler)
    with qqmusic._client() as client:
        qqmusic._vkey(client, "bbb")

    assert captured["req_0"]["param"]["uin"] == "123456789"
    assert captured["comm"]["uin"] == 123456789


def test_auto_source_falls_back_to_the_next_service(monkeypatch: MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_pick(song: str, cfg: SingConfig, source: str) -> service._Pick:
        seen.append(source)
        if source == "qq":
            raise ClientSongError("qq: VIP")
        return service._Pick(_candidate(f"{source}-hit", "晴天"), "same-artist")

    monkeypatch.setattr(service, "_pick_from_source", fake_pick)
    picked = service._pick_candidate("晴天", SingConfig(music_source="auto"))

    assert seen == ["qq", "netease"]
    assert picked.candidate.url.endswith("/netease-hit")


def test_auto_source_reports_every_failure(monkeypatch: MonkeyPatch) -> None:
    def fail(song: str, cfg: SingConfig, source: str) -> SongCandidate:
        raise ClientSongError(f"{source}-unavailable")

    monkeypatch.setattr(service, "_pick_from_source", fail)
    with pytest.raises(ClientSongError) as excinfo:
        service._pick_candidate("晴天", SingConfig(music_source="auto"))

    message = str(excinfo.value)
    assert "qq-unavailable" in message
    assert "netease-unavailable" in message
    assert "bilibili-unavailable" in message


def test_download_writes_stream_and_metadata(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    def handler(url: str, params: dict[str, Any]) -> _Response:
        if url == qqmusic.SEARCH_URL:
            return _Response({})
        if url == qqmusic.VKEY_URL:
            assert _vkey_request_mid(params) == "bbb"
            return _Response(_vkey_payload("C400bbb.m4a?guid=1&vkey=x"))
        if url == qqmusic.DETAIL_URL:
            return _Response({"code": 0, "data": [{"name": "晴天", "interval": 270}]})
        return _Response(content=b"m4a-bytes")

    _patch_client(monkeypatch, handler)
    path, title, total = qqmusic.download_audio("https://y.qq.com/n/ryqq/songDetail/bbb", tmp_path)

    assert path.name == "source.m4a"
    assert path.read_bytes() == b"m4a-bytes"
    assert title == "晴天"
    assert total == 270


def test_vip_download_is_a_client_error(monkeypatch: MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda url, params: _Response(_vkey_payload("", 104003)))
    with pytest.raises(ClientSongError) as excinfo:
        qqmusic.download_audio("https://y.qq.com/n/ryqq/songDetail/bbb", Path("."))
    assert "VIP" in str(excinfo.value)


def test_window_has_lyrics_skips_credit_and_title_lines(monkeypatch: MonkeyPatch) -> None:
    lyric = "\n".join(
        [
            "[00:00.00]晴天 - 周杰伦",
            "[00:04.00]词：徐若瑄",
            "[00:05.00]曲：周杰伦",
            "[01:05.00]故事的小黄花",
        ]
    )
    _patch_client(monkeypatch, lambda url, params: _Response({"retcode": 0, "lyric": lyric}))

    url = "https://y.qq.com/n/ryqq/songDetail/bbb"
    assert qqmusic.window_has_lyrics(url, 60, 30) is True
    assert qqmusic.window_has_lyrics(url, 0, 20) is False


def _candidate(mid: str, title: str, duration: int = 240) -> SongCandidate:
    return SongCandidate(title, "artist", duration, f"https://y.qq.com/n/ryqq/songDetail/{mid}")


def test_pick_skips_vip_hits(monkeypatch: MonkeyPatch) -> None:
    candidates = [_candidate("vip", "晴天"), _candidate("free", "晴天 (原版)")]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: "free" in url)
    monkeypatch.setattr(qqmusic, "window_has_lyrics", lambda url, start, duration: True)

    picked = service._pick_candidate("晴天", SingConfig(music_source="qq", pitch_mode="no-change"))
    assert picked.candidate.url.endswith("/free")


def test_pick_uses_a_free_hit_by_another_artist_and_says_so(monkeypatch: MonkeyPatch) -> None:
    candidates = [
        SongCandidate("晴天", "周杰伦", 270, "https://y.qq.com/n/ryqq/songDetail/vip"),
        SongCandidate("晴天", "Lucky小爱", 270, "https://y.qq.com/n/ryqq/songDetail/free"),
    ]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: "free" in url)
    monkeypatch.setattr(qqmusic, "window_has_lyrics", lambda url, start, duration: True)

    # Availability first, but the result names the stand-in and the original.
    picked = service._pick_candidate("晴天", SingConfig(music_source="qq"))
    assert picked.candidate.url.endswith("/free")
    assert picked.match == "other-artist"
    assert picked.original_artist == "周杰伦"


def test_strict_source_refuses_another_artist(monkeypatch: MonkeyPatch) -> None:
    candidates = [
        SongCandidate("晴天", "周杰伦", 270, "https://y.qq.com/n/ryqq/songDetail/vip"),
        SongCandidate("晴天", "Lucky小爱", 270, "https://y.qq.com/n/ryqq/songDetail/free"),
    ]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: "free" in url)
    monkeypatch.setattr(qqmusic, "window_has_lyrics", lambda url, start, duration: True)

    with pytest.raises(ClientSongError):
        service._pick_candidate("晴天", SingConfig(music_source="qq", strict_source=True))


def test_pick_prefers_a_free_hit_by_the_same_artist(monkeypatch: MonkeyPatch) -> None:
    candidates = [
        SongCandidate("晴天", "周杰伦", 270, "https://y.qq.com/n/ryqq/songDetail/vip"),
        SongCandidate("晴天", "Lucky小爱", 270, "https://y.qq.com/n/ryqq/songDetail/other"),
        SongCandidate("晴天", "周杰伦/某合唱", 271, "https://y.qq.com/n/ryqq/songDetail/same"),
    ]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: "vip" not in url)
    monkeypatch.setattr(qqmusic, "window_has_lyrics", lambda url, start, duration: True)

    picked = service._pick_candidate("晴天", SingConfig(music_source="qq"))

    assert picked.candidate.url.endswith("/same")
    assert picked.match == "same-artist"


def test_rank_candidates_drops_ai_covers_and_instrumentals() -> None:
    ai = SongCandidate("晴天 (AI翻唱)", "某AI", 270, "https://y.qq.com/n/ryqq/songDetail/ai")
    inst = SongCandidate("晴天 (伴奏)", "某人", 270, "https://y.qq.com/n/ryqq/songDetail/inst")
    clean = SongCandidate("晴天", "周杰伦", 270, "https://y.qq.com/n/ryqq/songDetail/clean")

    ranked, reference = service._rank_candidates([clean, ai, inst], strict=False)

    assert [item.url for item in ranked] == [clean.url]
    assert reference is clean


def test_variant_titles_rank_below_clean_same_title(monkeypatch: MonkeyPatch) -> None:
    candidates = [
        SongCandidate("晴天", "周杰伦", 270, "https://y.qq.com/n/ryqq/songDetail/vip"),
        SongCandidate("晴天 (Live)", "某人", 270, "https://y.qq.com/n/ryqq/songDetail/live"),
        SongCandidate("晴天", "搬运工", 271, "https://y.qq.com/n/ryqq/songDetail/clean"),
    ]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: "vip" not in url)
    monkeypatch.setattr(qqmusic, "window_has_lyrics", lambda url, start, duration: True)

    picked = service._pick_candidate("晴天", SingConfig(music_source="qq"))

    assert picked.candidate.url.endswith("/clean")
    assert picked.match == "other-artist"


def test_render_by_query_discloses_the_stand_in(monkeypatch: MonkeyPatch) -> None:
    pick = service._Pick(_candidate("free", "晴天"), "other-artist", "周杰伦")
    monkeypatch.setattr(service, "_pick_candidate", lambda song, cfg: pick)
    monkeypatch.setattr(
        service,
        "render_song",
        lambda url, cfg, artist="", audio_base="": SingResult("https://cdn/a.mp3", "a.mp3"),
    )

    block = service.render_song_by_query("晴天", SingConfig()).as_block()

    assert block["artist"] == "artist"
    assert block["source_match"] == "other-artist"
    assert block["original_artist"] == "周杰伦"


def test_pick_raises_when_every_hit_is_vip(monkeypatch: MonkeyPatch) -> None:
    candidates = [_candidate("vip1", "晴天"), _candidate("vip2", "晴天")]
    monkeypatch.setattr(service, "search_songs", lambda song, limit, source: candidates)
    monkeypatch.setattr(qqmusic, "can_play", lambda url: False)

    with pytest.raises(ClientSongError) as excinfo:
        service._pick_candidate("晴天", SingConfig(music_source="qq"))
    assert "QQ" in str(excinfo.value)


def test_search_songs_dispatches_qq(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_search(query: str, limit: int) -> list[SongCandidate]:
        seen.update({"query": query, "limit": limit})
        return [_candidate("bbb", "晴天")]

    monkeypatch.setattr(qqmusic, "search_qq", fake_search)
    result = service.search_songs("晴天", 2, "qq")

    assert seen == {"query": "晴天", "limit": 2}
    assert result[0].url.endswith("/bbb")


def test_search_songs_auto_stops_at_the_first_service_with_hits(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(qqmusic, "search_qq", lambda query, limit: [])
    monkeypatch.setattr(
        service.netease, "search_netease", lambda query, limit: [_candidate("n1", "晴天")]
    )
    monkeypatch.setattr(
        service.bilibili,
        "search_bilibili",
        lambda query, limit: pytest.fail("auto must stop before bilibili"),
    )

    result = service.search_songs("晴天", 2, "auto")

    assert result[0].url.endswith("/n1")
