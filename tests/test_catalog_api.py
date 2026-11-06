"""Public catalog endpoint: paging, filters and hot sort."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from sing_gateway.server import sing


def _client() -> TestClient:
    return TestClient(sing.app, base_url="https://testserver")


def _setup(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "hatsune-miku": {
                    "label": "Hatsune Miku (Japanese) (RVC V2)",
                    "url": "https://huggingface.co/a/b/resolve/main/miku.zip",
                    "preview_url": "https://cdn.example/miku.mp3",
                    "favorites": 65,
                    "weights_id": 10,
                },
                "columbina": {
                    "label": "Columbina (Genshin Impact) (English)",
                    "url": "https://huggingface.co/a/b/resolve/main/c.zip",
                    "favorites": 21,
                    "weights_id": 30,
                },
                "drums": {
                    "label": "Drums (RVC v2)",
                    "url": "https://huggingface.co/a/b/resolve/main/d.zip",
                    "favorites": 1,
                    "weights_id": 20,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_VOICES_CATALOG_FILE", str(path))
    monkeypatch.setenv("SING_DB_PATH", str(tmp_path / "sing.db"))
    monkeypatch.setenv("SING_VOICE_REQUESTS_FILE", str(tmp_path / "requests.json"))
    monkeypatch.delenv("SING_VOICE_ALIASES_FILE", raising=False)


def test_catalog_endpoint_search_alias_and_page(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    response = _client().get("/v1/voices/catalog", params={"q": "初音", "limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "hatsune-miku"
    assert body["items"][0]["language"] == "ja"
    assert body["items"][0]["rvc_version"] == "v2"
    assert body["items"][0]["preview_url"] == "https://cdn.example/miku.mp3"
    assert body["next_offset"] is None


def test_catalog_endpoint_filters_and_type_alias(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    english = _client().get("/v1/voices/catalog", params={"lang": "en"}).json()
    assert [item["name"] for item in english["items"]] == ["columbina"]

    instruments = _client().get("/v1/voices/catalog", params={"type": "instrumental"}).json()
    assert [item["name"] for item in instruments["items"]] == ["drums"]


def test_catalog_endpoint_is_paginated(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    first = _client().get("/v1/voices/catalog", params={"sort": "label", "limit": 2}).json()
    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert first["next_offset"] == 2
    second = (
        _client()
        .get("/v1/voices/catalog", params={"sort": "label", "limit": 2, "offset": 2})
        .json()
    )
    assert len(second["items"]) == 1
    assert second["next_offset"] is None


def test_catalog_endpoint_hot_sort(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    from sing_gateway import submissions as subs

    subs.increment_usage("drums")
    subs.increment_usage("drums")
    response = _client().get("/v1/voices/catalog", params={"sort": "hot"})
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "drums"
    assert response.json()["items"][0]["uses"] == 2
