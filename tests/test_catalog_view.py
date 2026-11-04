"""Catalog facets, search aliases, filtering and pagination."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from sing_gateway import catalog
from sing_gateway.voice_meta import derive_metadata


def _write_catalog(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "hatsune-miku": {
                    "label": "Hatsune Miku (RVC V2) (Japanese)",
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
                    "gender": "female",
                },
                "drums": {
                    "label": "100 Gecs - Doritos (Drums) (RVC v2, RMVPE)",
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
    monkeypatch.delenv(catalog.ALIASES_FILE_ENV, raising=False)


def test_derive_metadata_from_label() -> None:
    assert derive_metadata("Columbina (Genshin Impact) (English)") == {"language": "en"}
    assert derive_metadata("Female Character (Japanese)") == {
        "language": "ja",
        "gender": "female",
    }
    drums = derive_metadata("100 Gecs - Doritos (Drums) (RVC v2, RMVPE)")
    assert drums["type"] == "instrumental"
    assert drums["rvc_version"] == "v2"
    assert "RMVPE" in drums["tags"]
    assert "乐器" in drums["tags"]


def test_catalog_search_filter_and_pagination(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_catalog(tmp_path, monkeypatch)

    by_miku_alias = catalog.search_catalog(q="初音")
    assert by_miku_alias["total"] == 1
    assert by_miku_alias["items"][0]["name"] == "hatsune-miku"
    assert by_miku_alias["items"][0]["preview_url"] == "https://cdn.example/miku.mp3"

    english = catalog.search_catalog(language="en")
    assert [item["name"] for item in english["items"]] == ["columbina"]

    instruments = catalog.search_catalog(kind="instrumental")
    assert [item["name"] for item in instruments["items"]] == ["drums"]

    page = catalog.search_catalog(sort="label", limit=1, offset=1)
    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["next_offset"] == 2


def test_catalog_hot_sort_uses_usage_counts(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_catalog(tmp_path, monkeypatch)
    result = catalog.search_catalog(sort="hot", usage={"drums": 9})
    assert result["items"][0]["name"] == "drums"
    assert result["items"][0]["uses"] == 9


def test_catalog_alias_prefix_matches_while_typing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_catalog(tmp_path, monkeypatch)
    for query in ("初", "初音未"):
        result = catalog.search_catalog(q=query)
        assert [item["name"] for item in result["items"]][:1] == ["hatsune-miku"]


def test_catalog_uses_sidecar_query_aliases(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_catalog(tmp_path, monkeypatch)
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"原神": ["genshin"]}), encoding="utf-8")
    monkeypatch.setenv(catalog.ALIASES_FILE_ENV, str(aliases))
    result = catalog.search_catalog(q="原神")
    assert [item["name"] for item in result["items"]] == ["columbina"]
