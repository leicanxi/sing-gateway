"""Catalog scrape: --exclude-url drops dead voice links, including stored ones."""

from __future__ import annotations

from typing import Any

import pytest

from sing_gateway.tools import scrape_voice_catalog as scraper


def _item(name: str, url: str, weights_id: int) -> dict[str, Any]:
    return {"name": name, "url": url, "weightsId": weights_id, "stats": {"favoriteCount": 1}}


def test_scrape_skips_excluded_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        _item("A", "https://huggingface.co/Good/repo/resolve/main/a.zip", 1),
        _item("B", "https://huggingface.co/Gigrig/GigrigRVC/resolve/main/b.zip", 2),
    ]
    monkeypatch.setattr(scraper, "iter_items", lambda *args, **kwargs: iter(items))

    catalog, stats = scraper.scrape([], existing={}, exclude_urls=["gigrig/gigrigrvc"])

    assert list(catalog) == ["a"]
    assert stats["skipped_exclude"] == 1


def test_prune_excluded_drops_existing_entries() -> None:
    catalog = {
        "a": {"url": "https://huggingface.co/Good/repo/resolve/main/a.zip", "label": "A"},
        "b": {"url": "https://huggingface.co/Gigrig/GigrigRVC/resolve/main/b.zip", "label": "B"},
        "c": "https://example.com/legacy.zip",
    }

    pruned = scraper.prune_excluded(catalog, ["huggingface.co/gigrig/gigrigrvc"])

    assert set(pruned) == {"a", "c"}


def test_prune_excluded_is_noop_without_filters() -> None:
    catalog = {"a": {"url": "https://example.com/a.zip"}}

    assert scraper.prune_excluded(catalog, []) is catalog
