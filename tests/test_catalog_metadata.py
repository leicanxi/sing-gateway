"""Scraper stores derived facets alongside the scraped label."""

from __future__ import annotations

from typing import Any

from pytest import MonkeyPatch

from sing_gateway.tools import scrape_voice_catalog as scraper


def _item(name: str, weights_id: int) -> dict[str, Any]:
    return {
        "name": name,
        "url": f"https://huggingface.co/a/b/resolve/main/{weights_id}.zip",
        "weightsId": weights_id,
        "stats": {"favoriteCount": 3},
    }


def test_scrape_adds_derived_metadata(monkeypatch: MonkeyPatch) -> None:
    items = [
        _item("Hatsune Miku (Japanese) (RVC V2) (RMVPE)", 1),
        _item("Drum Kit (Drums) (RVC v2)", 2),
    ]
    monkeypatch.setattr(scraper, "iter_items", lambda *args, **kwargs: iter(items))

    catalog, stats = scraper.scrape([], existing={})

    assert stats["kept"] == 2
    miku = catalog["hatsune-miku-japanese-rvc-v2-rmvpe"]
    assert miku["language"] == "ja"
    assert miku["rvc_version"] == "v2"
    assert "RMVPE" in miku["tags"]
    drums = catalog["drum-kit-drums-rvc-v2"]
    assert drums["type"] == "instrumental"
    assert "乐器" in drums["tags"]


def test_scrape_keeps_source_tags(monkeypatch: MonkeyPatch) -> None:
    item = _item("Some Voice (English)", 3)
    item["tags"] = ["soft"]
    monkeypatch.setattr(scraper, "iter_items", lambda *args, **kwargs: iter([item]))

    catalog, _ = scraper.scrape([], existing={})

    assert "soft" in catalog["some-voice-english"]["tags"]
