"""SQLite store for voice submissions, publication state and usage counters.

The scraped catalog and the resolver whitelist stay in JSON. This module owns
only mutable user state:

* ``voice_requests`` — current submission/publication state (source of truth)
* ``voice_events``   — append-only lifecycle audit
* ``voice_stats``    — per-voice usage counters for the hot list

``SING_DB_PATH`` selects the database file (default ``~/.octop/sing.db``).
The legacy ``sing-voice-requests.json`` file is imported once when the database
is first created; afterwards the JSON file is left untouched.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DB_PATH_ENV = "SING_DB_PATH"
SCHEMA_VERSION = 1

_TAG_SPLIT_RE = re.compile(r"[,，、\s]+")
_MAX_TAGS = 8
_MAX_TAG_CHARS = 16

_lock = threading.Lock()
_initialized: set[Path] = set()

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS voice_requests (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL DEFAULT '',
        label          TEXT NOT NULL DEFAULT '',
        url            TEXT NOT NULL DEFAULT '',
        flowbee_uid    INTEGER NOT NULL DEFAULT 0,
        flowbee_user   TEXT NOT NULL DEFAULT '',
        source         TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL DEFAULT 'rejected',
        visibility     TEXT NOT NULL DEFAULT 'private'
                       CHECK (visibility IN ('private', 'public')),
        moderation     TEXT NOT NULL DEFAULT 'ok'
                       CHECK (moderation IN ('ok', 'blocked')),
        reason         TEXT NOT NULL DEFAULT '',
        author_display TEXT NOT NULL DEFAULT '',
        language       TEXT NOT NULL DEFAULT '',
        gender         TEXT NOT NULL DEFAULT '',
        rvc_version    TEXT NOT NULL DEFAULT '',
        tags_json      TEXT NOT NULL DEFAULT '[]',
        description    TEXT NOT NULL DEFAULT '',
        created_at     INTEGER NOT NULL,
        updated_at     INTEGER NOT NULL,
        published_at   INTEGER
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_requests_name
        ON voice_requests(name) WHERE name <> ''
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_voice_requests_owner
        ON voice_requests(flowbee_uid, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_voice_requests_public
        ON voice_requests(status, visibility, moderation, published_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS voice_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id  TEXT NOT NULL,
        name        TEXT NOT NULL DEFAULT '',
        action      TEXT NOT NULL,
        actor_uid   INTEGER,
        actor_role  TEXT NOT NULL DEFAULT 'system',
        reason      TEXT NOT NULL DEFAULT '',
        created_at  INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_voice_events_request
        ON voice_events(request_id, id)
    """,
    """
    CREATE TABLE IF NOT EXISTS voice_stats (
        name       TEXT PRIMARY KEY,
        uses       INTEGER NOT NULL DEFAULT 0,
        last_used  INTEGER
    )
    """,
)


class StateError(RuntimeError):
    """The requested publication transition is not allowed in the current state."""


def _home() -> Path:
    return Path(os.environ.get("OCTOP_HOME") or (Path.home() / ".octop"))


def db_path() -> Path:
    override = os.environ.get(DB_PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return _home() / "sing.db"


def _target(path: Path | None = None) -> Path:
    return Path(path or db_path()).expanduser().resolve()


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = _target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path | None = None, legacy_requests: Path | None = None) -> None:
    """Create the schema and import the legacy JSON file once."""
    target = _target(path)
    with _lock:
        if target in _initialized:
            return
        with connect(target) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _SCHEMA_STATEMENTS:
                    conn.execute(statement)
                if legacy_requests is not None and _is_empty(conn):
                    _import_legacy(conn, legacy_requests)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        _initialized.add(target)


def _is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS count FROM voice_requests").fetchone()
    return int(row["count"] if row else 0) == 0


def _import_legacy(conn: sqlite3.Connection, path: Path) -> None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    for record in raw.values():
        if not isinstance(record, dict) or not record.get("id"):
            continue
        data = _normalize_record(record)
        _upsert_conn(conn, data)
        _add_event_conn(
            conn,
            data["id"],
            data["name"],
            "imported",
            None,
            "system",
            "legacy JSON import",
        )


def _clean_tags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    else:
        raw = _TAG_SPLIT_RE.split(str(value or ""))
    tags: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = " ".join(str(item).replace("#", " ").split()).strip()
        if not tag:
            continue
        tag = tag[:_MAX_TAG_CHARS]
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= _MAX_TAGS:
            break
    return tags


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    try:
        created_at = int(record.get("created_at") or now)
    except (TypeError, ValueError):
        created_at = now
    try:
        updated_at = int(record.get("updated_at") or created_at)
    except (TypeError, ValueError):
        updated_at = created_at
    try:
        flowbee_uid = int(record.get("flowbee_uid") or 0)
    except (TypeError, ValueError):
        flowbee_uid = 0
    published_at = record.get("published_at")
    try:
        published_at = int(published_at) if published_at else None
    except (TypeError, ValueError):
        published_at = None
    status = str(record.get("status") or "rejected").strip().lower()
    visibility = str(record.get("visibility") or "private").strip().lower()
    if visibility not in {"private", "public"}:
        visibility = "private"
    moderation = str(record.get("moderation") or "ok").strip().lower()
    if moderation not in {"ok", "blocked"}:
        moderation = "ok"
    name = str(record.get("name") or "").strip().lower()
    label = str(record.get("label") or "").strip() or name
    return {
        "id": str(record.get("id") or ""),
        "name": name,
        "label": label,
        "url": str(record.get("url") or "").strip(),
        "flowbee_uid": flowbee_uid,
        "flowbee_user": str(record.get("flowbee_user") or "").strip(),
        "source": str(record.get("source") or "").strip(),
        "status": status,
        "visibility": visibility,
        "moderation": moderation,
        "reason": str(record.get("reason") or "").strip(),
        "author_display": str(record.get("author_display") or "").strip()[:40],
        "language": str(record.get("language") or "").strip().lower()[:16],
        "gender": str(record.get("gender") or "").strip().lower()[:16],
        "rvc_version": str(record.get("rvc_version") or "").strip().lower()[:16],
        "tags_json": json.dumps(_clean_tags(record.get("tags")), ensure_ascii=False),
        "description": " ".join(str(record.get("description") or "").split())[:500],
        "created_at": created_at,
        "updated_at": updated_at,
        "published_at": published_at,
    }


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["tags"] = json.loads(data.pop("tags_json") or "[]")
    except ValueError:
        data["tags"] = []
    return data


def _upsert_conn(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO voice_requests (
            id, name, label, url, flowbee_uid, flowbee_user, source, status,
            visibility, moderation, reason, author_display, language, gender,
            rvc_version, tags_json, description, created_at, updated_at, published_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            label = excluded.label,
            url = excluded.url,
            flowbee_uid = excluded.flowbee_uid,
            flowbee_user = excluded.flowbee_user,
            source = excluded.source,
            status = excluded.status,
            reason = excluded.reason,
            author_display = excluded.author_display,
            language = excluded.language,
            gender = excluded.gender,
            rvc_version = excluded.rvc_version,
            tags_json = excluded.tags_json,
            description = excluded.description,
            updated_at = excluded.updated_at
        """,
        (
            data["id"],
            data["name"],
            data["label"],
            data["url"],
            data["flowbee_uid"],
            data["flowbee_user"],
            data["source"],
            data["status"],
            data["visibility"],
            data["moderation"],
            data["reason"],
            data["author_display"],
            data["language"],
            data["gender"],
            data["rvc_version"],
            data["tags_json"],
            data["description"],
            data["created_at"],
            data["updated_at"],
            data["published_at"],
        ),
    )


def upsert_request(record: dict[str, Any]) -> None:
    data = _normalize_record(record)
    if not data["id"]:
        raise ValueError("voice request id is required")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _upsert_conn(conn, data)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def get_request(request_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM voice_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_record(row) if row else None


def list_requests() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_requests ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def list_requests_by_uid(uid: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM voice_requests
            WHERE flowbee_uid = ? AND status <> 'deleted'
            ORDER BY created_at DESC, id DESC
            """,
            (int(uid),),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def _add_event_conn(
    conn: sqlite3.Connection,
    request_id: str,
    name: str,
    action: str,
    actor_uid: int | None,
    actor_role: str,
    reason: str,
) -> None:
    conn.execute(
        """
        INSERT INTO voice_events (request_id, name, action, actor_uid, actor_role, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            name or "",
            action,
            int(actor_uid) if actor_uid is not None else None,
            actor_role or "system",
            reason or "",
            int(time.time()),
        ),
    )


def add_event(
    request_id: str,
    name: str,
    action: str,
    *,
    actor_uid: int | None = None,
    actor_role: str = "system",
    reason: str = "",
) -> None:
    with connect() as conn:
        _add_event_conn(conn, request_id, name, action, actor_uid, actor_role, reason)


def list_events(request_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_events WHERE request_id = ? ORDER BY id ASC",
            (request_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_deleted(
    request_id: str, *, actor_uid: int | None = None, actor_role: str = "user"
) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM voice_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            if row["status"] != "deleted":
                now = int(time.time())
                conn.execute(
                    """
                    UPDATE voice_requests
                    SET status = 'deleted', visibility = 'private', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, request_id),
                )
                _add_event_conn(
                    conn,
                    request_id,
                    row["name"],
                    "deleted",
                    actor_uid,
                    actor_role,
                    "",
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        row = conn.execute("SELECT * FROM voice_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_record(row) if row else None


def set_visibility(
    request_id: str,
    visibility: str,
    *,
    actor_uid: int | None = None,
    actor_role: str = "user",
    reason: str = "",
) -> dict[str, Any] | None:
    if visibility not in {"private", "public"}:
        raise ValueError("visibility must be 'private' or 'public'")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM voice_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            if row["visibility"] == visibility:
                conn.execute("COMMIT")
                return _row_to_record(row)
            if visibility == "public":
                if row["status"] != "approved":
                    raise StateError("只有审核通过的音色才能公开")
                if row["moderation"] != "ok":
                    raise StateError("该音色已被下架，无法公开")
            now = int(time.time())
            published_at = now if visibility == "public" else row["published_at"]
            conn.execute(
                """
                UPDATE voice_requests
                SET visibility = ?, published_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (visibility, published_at, now, request_id),
            )
            _add_event_conn(
                conn,
                request_id,
                row["name"],
                "published" if visibility == "public" else "unpublished",
                actor_uid,
                actor_role,
                reason,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        row = conn.execute("SELECT * FROM voice_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_record(row) if row else None


def set_moderation(
    request_id: str,
    moderation: str,
    *,
    actor_uid: int | None = None,
    actor_role: str = "admin",
    reason: str = "",
) -> dict[str, Any] | None:
    if moderation not in {"ok", "blocked"}:
        raise ValueError("moderation must be 'ok' or 'blocked'")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM voice_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            if row["moderation"] == moderation:
                conn.execute("COMMIT")
                return _row_to_record(row)
            now = int(time.time())
            visibility = "private" if moderation == "blocked" else row["visibility"]
            conn.execute(
                """
                UPDATE voice_requests
                SET moderation = ?, visibility = ?, updated_at = ?
                WHERE id = ?
                """,
                (moderation, visibility, now, request_id),
            )
            _add_event_conn(
                conn,
                request_id,
                row["name"],
                "blocked" if moderation == "blocked" else "unblocked",
                actor_uid,
                actor_role,
                reason,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        row = conn.execute("SELECT * FROM voice_requests WHERE id = ?", (request_id,)).fetchone()
    return _row_to_record(row) if row else None


def increment_usage(name: str) -> int:
    key = (name or "").strip().lower()
    if not key:
        return 0
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO voice_stats (name, uses, last_used)
            VALUES (?, 1, ?)
            ON CONFLICT(name) DO UPDATE SET
                uses = voice_stats.uses + 1,
                last_used = excluded.last_used
            """,
            (key, int(time.time())),
        )
        row = conn.execute("SELECT uses FROM voice_stats WHERE name = ?", (key,)).fetchone()
    return int(row["uses"]) if row else 0


def get_usage(name: str) -> int:
    key = (name or "").strip().lower()
    if not key:
        return 0
    with connect() as conn:
        row = conn.execute("SELECT uses FROM voice_stats WHERE name = ?", (key,)).fetchone()
    return int(row["uses"]) if row else 0


def usage_map() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT name, uses FROM voice_stats").fetchall()
    return {str(row["name"]): int(row["uses"]) for row in rows}


def _public_row(row: sqlite3.Row) -> dict[str, Any]:
    record = _row_to_record(row)
    return {
        "name": record["name"],
        "label": record["label"],
        "url": record["url"],
        "source": "community",
        "tags": record["tags"],
        "language": record["language"],
        "gender": record["gender"],
        "rvc_version": record["rvc_version"],
        "description": record["description"],
        "author": record["author_display"] or "社区投稿",
        "published_at": record["published_at"],
        "uses": int(row["uses"] or 0),
    }


def list_public(limit: int = 24, sort: str = "new") -> list[dict[str, Any]]:
    limit = max(1, min(100, int(limit)))
    if sort == "hot":
        order = "COALESCE(s.uses, 0) DESC, r.published_at DESC, r.id DESC"
    else:
        order = "r.published_at DESC, r.id DESC"
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, COALESCE(s.uses, 0) AS uses
            FROM voice_requests AS r
            LEFT JOIN voice_stats AS s ON s.name = r.name
            WHERE r.status = 'approved'
              AND r.visibility = 'public'
              AND r.moderation = 'ok'
            ORDER BY {order}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_public_row(row) for row in rows]
