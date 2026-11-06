"""Read-only catalog view for the plaza: search, filters and pagination.

The scraped catalog is a generated JSON file. Loading it in the browser meant
shipping several megabytes before the first card; this module reads it on the
gateway (mtime-cached), derives missing facets from the label, and returns one
page at a time. It also expands a small Chinese/English alias table so common
queries such as "初音" match "Hatsune Miku".
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sing_gateway.voice_meta import derive_metadata
from sing_gateway.voices import catalog_path

ALIASES_FILE_ENV = "SING_VOICE_ALIASES_FILE"

_NORMALIZE_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_MAX_TAGS = 8
_LANGUAGE_CODES = frozenset({"zh", "ja", "en", "ko", "es", "fr", "de", "ru", "pt", "it", "other"})
_GENDER_CODES = frozenset({"female", "male", "neutral"})
_TYPE_CODES = frozenset({"vocal", "instrumental"})
_RVC_CODES = frozenset({"v1", "v2"})

DEFAULT_QUERY_ALIASES: dict[str, list[str]] = {
    "初音未来": ["hatsune miku", "miku"],
    "初音": ["hatsune miku", "miku"],
    "邓紫棋": ["gem tang", "g.e.m."],
    "原神": ["genshin impact", "genshin"],
    "崩坏": ["honkai"],
    "星穹铁道": ["star rail"],
    "明日方舟": ["arknights"],
    "英雄联盟": ["league of legends"],
    "王者荣耀": ["honor of kings"],
    "周杰伦": ["jay chou"],
    "林俊杰": ["jj lin"],
    "泰勒": ["taylor swift"],
    "碧梨": ["billie eilish"],
    "爱莉希雅": ["elysia"],
    "雷电将军": ["raiden shogun"],
    "胡桃": ["hu tao"],
    "甘雨": ["ganyu"],
    "纳西妲": ["nahida"],
    "芙宁娜": ["furina"],
    "刻晴": ["keqing"],
    "可莉": ["klee"],
    "女声": ["female", "girl", "woman"],
    "男声": ["male", "boy", "man"],
    "乐器": ["instrumental"],
    "中文": ["chinese", "mandarin", "zh"],
    "日语": ["japanese", "ja"],
    "英语": ["english", "en"],
    "韩语": ["korean", "ko"],
}

_cache: dict[Path, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}
_alias_cache: dict[Path, tuple[tuple[int, int], dict[str, list[str]]]] = {}


def aliases_path() -> Path:
    override = os.environ.get(ALIASES_FILE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("OCTOP_HOME") or (Path.home() / ".octop"))
    return home / "sing-voice-aliases.json"


def normalize(text: str) -> str:
    return " ".join(_NORMALIZE_RE.sub(" ", str(text or "").casefold()).split())


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def _facet(value: Any, allowed: frozenset[str], derived: str) -> str:
    if derived:
        return derived
    text = str(value or "").strip().lower()
    if text in allowed:
        return text
    # Third-party feeds sometimes spell the facet out ("English", "Female").
    if allowed == _LANGUAGE_CODES:
        return str(derive_metadata(text).get("language") or "")
    if allowed == _GENDER_CODES:
        return str(derive_metadata(text).get("gender") or "")
    if allowed == _TYPE_CODES:
        return str(derive_metadata(text).get("type") or "")
    return str(derive_metadata(text).get("rvc_version") or "")


def _entry(slug: str, value: dict[str, Any]) -> dict[str, Any]:
    label = str(value.get("label") or slug).strip() or slug
    derived = derive_metadata(label or slug)
    language = _facet(value.get("language"), _LANGUAGE_CODES, str(derived.get("language") or ""))
    gender = _facet(value.get("gender"), _GENDER_CODES, str(derived.get("gender") or ""))
    kind = _facet(value.get("type"), _TYPE_CODES, str(derived.get("type") or ""))
    rvc_version = _facet(
        value.get("rvc_version"), _RVC_CODES, str(derived.get("rvc_version") or "")
    )

    raw_tags = value.get("tags")
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags: list[str] = []
    for raw in list(raw_tags or []) + list(derived.get("tags") or []):
        tag = str(raw or "").strip()
        if tag and tag not in tags:
            tags.append(tag)
    tags = tags[:_MAX_TAGS]

    raw_aliases = value.get("aliases")
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    aliases = [str(item).strip() for item in (raw_aliases or []) if str(item).strip()]

    search_text = normalize(
        " ".join([label, slug, *tags, *aliases, language, gender, kind, rvc_version])
    )
    return {
        "name": slug,
        "label": label,
        "url": _safe_url(str(value.get("url") or "")),
        "preview_url": _safe_url(str(value.get("preview_url") or "")),
        "favorites": _int(value.get("favorites")),
        "weights_id": _int(value.get("weights_id")),
        "language": language,
        "gender": gender,
        "type": kind,
        "rvc_version": rvc_version,
        "tags": tags,
        "search_text": search_text,
    }


def load_entries(path: Path | None = None) -> dict[str, dict[str, Any]]:
    target = Path(path or catalog_path()).expanduser()
    try:
        stat = target.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    cached = _cache.get(target)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    entries = {
        str(slug): _entry(str(slug), value)
        for slug, value in raw.items()
        if isinstance(value, dict)
    }
    _cache[target] = (stamp, entries)
    return entries


def load_query_aliases(path: Path | None = None) -> dict[str, list[str]]:
    target = Path(path or aliases_path()).expanduser()
    try:
        stat = target.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if stamp is not None:
        cached = _alias_cache.get(target)
        if cached is not None and cached[0] == stamp:
            return cached[1]

    aliases: dict[str, list[str]] = {
        normalize(key): list(values) for key, values in DEFAULT_QUERY_ALIASES.items()
    }
    if stamp is not None:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            for key, value in raw.items():
                values = [value] if isinstance(value, str) else value
                if not isinstance(values, (list, tuple)):
                    continue
                key_text = normalize(str(key))
                if not key_text:
                    continue
                merged = aliases.setdefault(key_text, [])
                for item in values:
                    text = str(item).strip()
                    if text and text not in merged:
                        merged.append(text)
        _alias_cache[target] = (stamp, aliases)
    return aliases


def _token_groups(query: str) -> list[list[str]]:
    tokens = normalize(query).split()
    if not tokens:
        return []
    aliases = load_query_aliases()
    groups: list[list[str]] = []
    for token in tokens:
        # Exact keys plus prefix keys: while a Chinese user is still typing
        # ("初" -> "初音" -> "初音未来"), the intermediate query should already
        # expand to the English label.
        values: list[str] = []
        for key, mapped in aliases.items():
            if key == token or key.startswith(token):
                values.extend(mapped)
        alternatives: list[str] = []
        for item in values:
            text = normalize(item)
            if text and text not in alternatives:
                alternatives.append(text)
        groups.append(alternatives or [token])
    return groups


def _sort_key(sort: str, usage: dict[str, int]) -> Callable[[dict[str, Any]], tuple[Any, ...]]:
    if sort == "hot":
        return lambda item: (
            -int(usage.get(item["name"], 0)),
            -item["favorites"],
            item["label"].casefold(),
            item["name"],
        )
    if sort == "label":
        return lambda item: (item["label"].casefold(), item["name"])
    if sort == "new":
        return lambda item: (-item["weights_id"], item["label"].casefold(), item["name"])
    return lambda item: (-item["favorites"], item["label"].casefold(), item["name"])


def search_catalog(
    *,
    q: str = "",
    language: str = "",
    gender: str = "",
    kind: str = "",
    sort: str = "favorites",
    limit: int = 60,
    offset: int = 0,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    usage = usage or {}
    language = str(language or "").strip().lower()
    gender = str(gender or "").strip().lower()
    kind = str(kind or "").strip().lower()
    groups = _token_groups(q)

    entries: list[dict[str, Any]] = []
    for entry in load_entries().values():
        if language and entry["language"] != language:
            continue
        if gender and entry["gender"] != gender:
            continue
        if kind and entry["type"] != kind:
            continue
        if groups:
            haystack = entry["search_text"]
            if not all(any(term in haystack for term in group) for group in groups):
                continue
        entries.append(entry)

    entries.sort(key=_sort_key(sort, usage))
    total = len(entries)
    page = entries[offset : offset + limit]
    items = [
        {
            "name": entry["name"],
            "label": entry["label"],
            "url": entry["url"],
            "preview_url": entry["preview_url"],
            "favorites": entry["favorites"],
            "uses": int(usage.get(entry["name"], 0)),
            "language": entry["language"],
            "gender": entry["gender"],
            "type": entry["type"],
            "rvc_version": entry["rvc_version"],
            "tags": entry["tags"],
            "source": "catalog",
        }
        for entry in page
    ]
    next_offset = offset + len(items)
    return {
        "total": total,
        "items": items,
        "next_offset": next_offset if next_offset < total else None,
    }
