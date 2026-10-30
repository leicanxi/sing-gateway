#!/usr/bin/env python3
"""Re-point catalog entries whose upstream zip is broken.

Some scraped RVC zips ship an empty faiss index (``ntotal=0``). AICoverGen then
crashes with ``index -1 is out of bounds for axis 0 with size 0``. We host a
fixed copy (broken ``.index`` stripped) and override the URL here; overrides
survive the weekly re-scrape because the refresh script runs this afterwards.

Paths default to the deployment layout and can be overridden by env:
``SING_VOICES_CATALOG_FILE`` (catalog) and ``SING_VOICE_OVERRIDES_FILE``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = "/etc/octop/sing-voices-catalog.json"
DEFAULT_OVERRIDES = "/etc/octop/sing-voice-url-overrides.json"


def _path(env_name: str, default: str) -> Path:
    return Path(os.environ.get(env_name, "").strip() or default)


def main() -> int:
    overrides_path = _path("SING_VOICE_OVERRIDES_FILE", DEFAULT_OVERRIDES)
    catalog_path = _path("SING_VOICES_CATALOG_FILE", DEFAULT_CATALOG)
    with overrides_path.open(encoding="utf-8") as handle:
        overrides: dict[str, str] = json.load(handle)
    with catalog_path.open(encoding="utf-8") as handle:
        catalog: dict[str, Any] = json.load(handle)
    applied = 0
    for slug, url in overrides.items():
        entry = catalog.get(slug)
        if isinstance(entry, dict) and entry.get("url") != url:
            entry["url"] = url
            applied += 1
    if applied:
        with catalog_path.open("w", encoding="utf-8") as handle:
            json.dump(catalog, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    print(f"voice-url overrides applied: {applied}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
