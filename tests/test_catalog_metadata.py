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


def test_sample_preview_url_prefers_female_and_encodes() -> None:
    item = {
        "sample": {
            "available": True,
            "name": "abc def",
            "hasFemale": True,
            "hasMale": True,
        }
    }
    assert (
        scraper.sample_preview_url(item)
        == f"{scraper.SAMPLE_BASE_URL}samples2/abc%20def.mp3"
    )


def test_sample_preview_url_male_and_unavailable() -> None:
    male = {"sample": {"available": True, "name": "m1", "hasMale": True}}
    assert scraper.sample_preview_url(male).endswith("/samples/m1.mp3")
    assert scraper.sample_preview_url({"sample": {"available": False, "name": "x"}}) == ""
    assert scraper.sample_preview_url({"sample": {"available": True, "name": "x"}}) == ""


def test_scrape_stores_preview_url(monkeypatch: MonkeyPatch) -> None:
    item = _item("Some Voice (English)", 4)
    item["sample"] = {"available": True, "name": "sample-id", "hasFemale": True}
    monkeypatch.setattr(scraper, "iter_items", lambda *args, **kwargs: iter([item]))

    catalog, _ = scraper.scrape([], existing={})

    assert catalog["some-voice-english"]["preview_url"].endswith(
        "/samples2/sample-id.mp3"
    )


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
