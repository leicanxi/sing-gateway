"""Song-title normalization shared by the music sources.

Anonymous searches rank unknown covers, remixes and live uploads above the
original (稻香 → 稻香(深情版) by an uploader), so each source scores the query
against the returned title instead of trusting the result order.
"""

from __future__ import annotations

import re

_TITLE_NOISE_RE = re.compile(r"[\s\-_·・,，。.、!！?？'\"“”‘’()（）\[\]【】《》]+")
# Decorations that mark a different arrangement rather than the master. Plain
# and 唱片版/原版/原唱-labelled hits are the recording the user asked for, so they
# are deliberately absent here.
_VARIANT_RE = re.compile(
    r"深情|治愈|伤感|史诗|史詩|女声|男声|男生|女生|童声|合唱|和声|钢琴|吉他|清唱|哼唱|"
    r"现场|加速|慢速|抖音|翻唱|伴奏|纯音乐|铃声|片段|串烧|medley|cover|live|remix|dj",
    re.IGNORECASE,
)


def normalized_title(value: str) -> str:
    return _stripped(value).casefold()


def _stripped(value: str) -> str:
    return _TITLE_NOISE_RE.sub("", value or "")


def title_match_score(query: str, title: str) -> float:
    """How well *title* answers *query*: 1.0 for an exact title, 0.2 unrelated.

    A title that only decorates the query stays usable but ranks below a
    plain-titled upload.
    """
    wanted = normalized_title(query)
    found = normalized_title(title)
    if not wanted or not found:
        return 0.0
    if found == wanted:
        return 1.0
    if found.startswith(wanted):
        base = 0.7
    elif wanted in found:
        base = 0.4
    else:
        base = 0.2
    return max(0.1, base - 0.2) if _VARIANT_RE.search(found) else base


def title_rank_key(query: str, title: str) -> tuple[float, int]:
    """Sort key for search hits: similarity, then exact capitalisation.

    Scoring is casefolded so a plainly typed query still matches the official
    stylisation. When two different songs differ only in case (``GReeeeN`` vs
    ``greeeen``) both reach 1.0; the caller's own capitalisation then decides,
    because the source's order alone cannot tell them apart.
    """
    wanted = _stripped(query)
    styled_match = int(bool(wanted) and wanted == _stripped(title))
    return title_match_score(query, title), styled_match
