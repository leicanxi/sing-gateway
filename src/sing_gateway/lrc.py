"""Shared LRC parsing for the NetEase and QQ Music lyric timelines.

Both services return standard LRC. The first lines are a credit block
(作词/作曲/编曲 …) rather than sung lyrics, so the window check skips them.
"""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
CREDIT_RE = re.compile(
    r"^(作词|作曲|编曲|制作人|监制|出品|录音|混音|母带|吉他|贝斯|鼓|键盘|和声|弦乐|词|曲|OP|SP)"
    r"\s*[:：]",
    re.IGNORECASE,
)


def parse_lrc(lrc: str) -> list[tuple[float, str]]:
    """Return ``(seconds, text)`` for every timestamped line, in file order."""
    lines: list[tuple[float, str]] = []
    for raw in (lrc or "").splitlines():
        line = raw.strip()
        match = _TIME_RE.match(line)
        if match is None:
            continue
        timestamp = int(match.group(1)) * 60 + float(match.group(2))
        lines.append((timestamp, line[match.end() :].strip()))
    return lines


def is_credit(text: str) -> bool:
    return bool(CREDIT_RE.match(text or ""))
