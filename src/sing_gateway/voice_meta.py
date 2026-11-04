"""Derive structured facets from noisy third-party catalog labels.

The scraped catalog only gives us a display name plus a download URL. Labels
usually carry language, RVC version, feature flags and instrument hints in
parentheses, e.g. ``Columbina (Genshin Impact) (English)`` or
``... (RVC V2, RMVPE)``. This module turns those hints into stable fields so
the plaza can filter and render chips without re-parsing labels in JavaScript.

Values are deliberately conservative: unknown means an empty value, never a
guess. ``derive_metadata`` returns only the keys it can fill.
"""

from __future__ import annotations

import re
from typing import Any

_LANGUAGE_VALUES = {
    "chinese": "zh",
    "mandarin": "zh",
    "cantonese": "zh",
    "japanese": "ja",
    "english": "en",
    "korean": "ko",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "russian": "ru",
    "portuguese": "pt",
    "italian": "it",
}
_GENDER_VALUES = {
    "female": "female",
    "girl": "female",
    "woman": "female",
    "male": "male",
    "boy": "male",
    "man": "male",
    "neutral": "neutral",
}
_LANGUAGE_RE = re.compile(
    r"\b(" + "|".join(_LANGUAGE_VALUES) + r")\b",
    re.IGNORECASE,
)
_GENDER_RE = re.compile(
    r"\b(" + "|".join(_GENDER_VALUES) + r")\b",
    re.IGNORECASE,
)
_INSTRUMENT_RE = re.compile(
    r"\b(drums?|guitar|bass|piano|instrumental|trumpet|violin|cello|flute|"
    r"saxophone|synth|ukulele)\b",
    re.IGNORECASE,
)
_RVC_V2_RE = re.compile(r"\b(?:rvc\s*v?2|v2)\b", re.IGNORECASE)
_RVC_V1_RE = re.compile(r"\b(?:rvc\s*v?1|v1)\b", re.IGNORECASE)
_FEATURE_TAGS = (
    ("RMVPE", re.compile(r"\brmvpe\b", re.IGNORECASE)),
    ("TITAN", re.compile(r"\btitan\b", re.IGNORECASE)),
    ("Kits.ai", re.compile(r"\bkits\.ai\b", re.IGNORECASE)),
    ("旧版", re.compile(r"\bobsolete\b", re.IGNORECASE)),
)


def derive_metadata(name: str) -> dict[str, Any]:
    """Return the facets that can be read reliably from *name*."""
    text = str(name or "")
    meta: dict[str, Any] = {}

    language = _LANGUAGE_RE.search(text)
    if language:
        meta["language"] = _LANGUAGE_VALUES[language.group(1).lower()]

    gender = _GENDER_RE.search(text)
    if gender:
        meta["gender"] = _GENDER_VALUES[gender.group(1).lower()]

    if _RVC_V2_RE.search(text):
        meta["rvc_version"] = "v2"
    elif _RVC_V1_RE.search(text):
        meta["rvc_version"] = "v1"

    tags = [label for label, pattern in _FEATURE_TAGS if pattern.search(text)]
    if _INSTRUMENT_RE.search(text):
        meta["type"] = "instrumental"
        tags.append("乐器")
    if tags:
        meta["tags"] = tags

    return meta
