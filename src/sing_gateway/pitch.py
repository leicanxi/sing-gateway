"""Automatic key selection for covers.

``pitch_mode="auto"`` derives the whole-mix semitone shift from the song's
artist and the chosen voice: the same gender keeps the original key, a
cross-gender cover moves one octave (male artist → female voice is +12, the
reverse is -12). The gateway shifts the vocal and the accompaniment by the
same amount, so the result stays in key instead of only transposing the singer.

Genders come from four places, in trust order:

1. the ``gender`` field of a voice entry in the voices JSON (authored by us),
2. the gender word in the voice label (``voice_meta``), a deterministic guess,
3. ``SING_GENDER_CACHE_FILE`` (hand-editable; LLM verdicts are cached there),
4. a chat model, when ``SING_GENDER_LLM_*`` or the review model is configured.

Anything unresolved falls back to the configured default pitch, so auto mode
degrades to today's behaviour instead of failing a render.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from sing_gateway.voice_meta import derive_metadata
from sing_gateway.voices import normalize_gender

logger = logging.getLogger(__name__)

GENDER_CACHE_ENV = "SING_GENDER_CACHE_FILE"
LLM_BASE_ENV = "SING_GENDER_LLM_BASE_URL"
LLM_KEY_ENV = "SING_GENDER_LLM_API_KEY"
LLM_MODEL_ENV = "SING_GENDER_LLM_MODEL"
# Deployments that already run the submission reviewer need no extra config.
REVIEW_BASE_ENV = "SING_REVIEW_BASE_URL"
REVIEW_KEY_ENV = "SING_REVIEW_API_KEY"
REVIEW_MODEL_ENV = "SING_REVIEW_MODEL"
DEFAULT_REVIEW_MODEL = "deepseek-chat"
LLM_TIMEOUT_SECONDS = 6.0

_GENDERS = frozenset({"male", "female"})

_lock = threading.Lock()
_cache_stamp: tuple[int, int] | None = None
_cache: dict[str, dict[str, str]] = {"artists": {}, "voices": {}}


def gender_cache_path() -> Path:
    override = os.environ.get(GENDER_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("OCTOP_HOME") or (Path.home() / ".octop"))
    return home / "sing-gender-cache.json"


def _load_cache() -> dict[str, dict[str, str]]:
    global _cache, _cache_stamp

    target = gender_cache_path()
    try:
        stat = target.stat()
        stamp: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return _cache
    with _lock:
        if _cache_stamp == stamp:
            return _cache
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    parsed: dict[str, dict[str, str]] = {"artists": {}, "voices": {}}
    if isinstance(raw, dict):
        for scope in ("artists", "voices"):
            entries = raw.get(scope)
            if not isinstance(entries, dict):
                continue
            for name, value in entries.items():
                gender = normalize_gender(value)
                key = str(name).strip().lower()
                if key and gender:
                    parsed[scope][key] = gender
    with _lock:
        _cache = parsed
        _cache_stamp = stamp
    return parsed


def _remember(scope: str, name: str, gender: str) -> None:
    """Persist one LLM verdict so later renders skip the call."""
    global _cache, _cache_stamp

    key = (name or "").strip().lower()
    if not key or gender not in _GENDERS:
        return
    current = _load_cache()
    data = {
        "artists": dict(current["artists"]),
        "voices": dict(current["voices"]),
    }
    data[scope][key] = gender
    path = gender_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.debug("could not persist gender cache", exc_info=True)
        return
    with _lock:
        _cache = data
        _cache_stamp = None


def _llm_settings() -> tuple[str, str, str]:
    base = (os.environ.get(LLM_BASE_ENV) or os.environ.get(REVIEW_BASE_ENV) or "").strip()
    key = (os.environ.get(LLM_KEY_ENV) or os.environ.get(REVIEW_KEY_ENV) or "").strip()
    model = (
        os.environ.get(LLM_MODEL_ENV) or os.environ.get(REVIEW_MODEL_ENV) or DEFAULT_REVIEW_MODEL
    ).strip()
    return base, key, model


def _parse_answer(content: Any) -> str:
    text = str(content or "").strip().lower()
    # "female" contains "male", so the female patterns must be tested first.
    if re.search(r"female|\bf\b|女", text):
        return "female"
    if re.search(r"male|\bm\b|男", text):
        return "male"
    return ""


def _ask_llm(scope: str, name: str) -> str:
    base, key, model = _llm_settings()
    if not base or not key:
        return ""
    # Search results are untrusted text; keep the prompt one short line.
    subject_name = " ".join(name.split())[:80]
    if scope == "artists":
        subject = f"歌手或组合「{subject_name}」的主唱"
    else:
        subject = f"AI 翻唱音色「{subject_name}」所模拟的角色"
    prompt = f"判断{subject}是男性还是女性。只回答 male 或 female，不要输出其他内容。"
    try:
        response = httpx.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 8,
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - a cover must never fail on this
        logger.info("gender lookup failed for %s %r: %s", scope, name, exc)
        return ""
    gender = _parse_answer(content)
    if not gender:
        logger.info("gender lookup gave no verdict for %s %r: %r", scope, name, content)
    return gender


def artist_gender(artist: str) -> str:
    name = (artist or "").strip()
    if not name:
        return ""
    cached = _load_cache()["artists"].get(name.lower())
    if cached:
        return cached
    gender = _ask_llm("artists", name)
    if gender:
        _remember("artists", name, gender)
    return gender


def voice_gender(label: str) -> str:
    name = (label or "").strip()
    if not name:
        return ""
    cached = _load_cache()["voices"].get(name.lower())
    if cached:
        return cached
    gender = _ask_llm("voices", name)
    if gender:
        _remember("voices", name, gender)
    return gender


def label_gender(label: str) -> str:
    """Gender spelled out in the label, e.g. ``... (RVC V2, Female)``."""
    return normalize_gender(derive_metadata(label).get("gender"))


def semitones_for(source: str, target: str) -> int | None:
    """Semitones that move a source-gender song into a target-gender voice."""
    if source not in _GENDERS or target not in _GENDERS:
        return None
    if source == target:
        return 0
    return 12 if source == "male" else -12


def resolve_pitch(
    artist: str,
    voice_label: str,
    declared_voice_gender: str,
    fallback: int,
) -> tuple[int, bool]:
    """Return ``(semitones, resolved)`` for an auto-pitch request.

    ``resolved`` is False when either gender is unknown; the caller then keeps
    the configured fallback pitch so behaviour is unchanged.
    """
    # Authored value first; the label guess is deterministic, so it beats a
    # cached or LLM verdict, which are machine guesses too.
    target = (
        normalize_gender(declared_voice_gender)
        or label_gender(voice_label)
        or voice_gender(voice_label)
    )
    semitones = semitones_for(artist_gender(artist), target)
    if semitones is None:
        return fallback, False
    return semitones, True
