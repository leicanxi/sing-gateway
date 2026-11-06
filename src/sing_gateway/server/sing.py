"""OpenAI-compatible gateway for the ``sing-song`` new-api model.

Run it as its own service and point a new-api custom channel at ``/v1``:

    SING_GATEWAY_TOKEN=... REPLICATE_API_TOKEN=... \\
        sing-gateway --host 127.0.0.1 --port 9001

Clients either call the synchronous ``POST /v1/chat/completions`` or submit a
background job with ``POST /sing/v1/jobs`` and poll ``GET /sing/v1/jobs/{id}``;
the job form keeps multi-minute generations out of every client's HTTP timeout
and exposes ``duration_seconds`` / ``cached`` for per-second billing.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, RedirectResponse

from sing_gateway import (
    DEFAULT_REPLICATE_BASE,
    ClientSongError,
    SingConfig,
    load_voices,
    plaza_url,
    render_song,
    render_song_by_query,
    resolve_voice,
    search_songs,
)
from sing_gateway.catalog import search_catalog
from sing_gateway.config import VOLUME_MAX, VOLUME_MIN
from sing_gateway.jobs import JobManager
from sing_gateway.server.sso import (
    DEFAULT_NEXT,
    check_origin,
    clear_session_cookie,
    clear_sso_cookie,
    issue_session,
    jwt_secret,
    new_state,
    normalize_next,
    plaza_base,
    read_sso_cookie,
    require_identity,
    set_session_cookie,
    set_sso_cookie,
    sso_secret,
    sso_url,
    verify_sso_ticket,
)
from sing_gateway.submissions import (
    StateError,
    add_event,
    add_voice,
    build_request_record,
    generate_name,
    get_request,
    hf_delete,
    hf_upload,
    increment_usage,
    list_public_voices,
    list_requests_by_uid,
    llm_review,
    mark_deleted,
    modelscope_delete,
    modelscope_upload,
    new_request_id,
    reconcile_whitelist,
    review_archive,
    save_request,
    set_moderation,
    set_visibility,
    usage_map,
)
from sing_gateway.voices import remove_voice

app = FastAPI(title="sing-gateway", version="0.1.0")

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sing-song"
_VOICES_MODEL = "sing-voices"
_SEARCH_MODEL = "sing-search"
_VOICES_NOTE = (
    "音色列表已迁移到音色广场：打开 plaza_url 挑选音色，点歌时把音色名传给 voice。"
    "自有 RVC 音色可在广场页提交上传（自动审核），通过后会显示音色名。"
)


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class SongSearchRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=3, ge=1, le=5)
    source: str = ""


class ChatCompletionRequest(BaseModel):
    model: str = _DEFAULT_MODEL
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False


class JobRequest(BaseModel):
    model: str = _DEFAULT_MODEL
    song: str = ""
    url: str = ""
    voice: str = ""
    start: int | None = None
    duration: int | None = None
    pitch: int | None = None
    pitch_mode: str | None = None
    source: str = ""
    instrumental_volume: int | None = Field(
        default=None, description="Instrumental gain in dB, -60 (muted) to 0"
    )
    backup_vocals_volume: int | None = Field(
        default=None, description="Backup-vocal gain in dB, -60 (muted) to 0"
    )


class ModerationRequest(BaseModel):
    moderation: str = "ok"
    reason: str = ""


def _gateway_token() -> str:
    return os.environ.get("SING_GATEWAY_TOKEN", "").strip()


def _require_token(authorization: str | None = Header(default=None)) -> None:
    expected = _gateway_token()
    if not expected:
        raise HTTPException(status_code=503, detail="SING_GATEWAY_TOKEN is not configured")
    supplied = (authorization or "").strip()
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="invalid gateway token")


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _request_payload(body: ChatCompletionRequest) -> dict[str, Any]:
    user_messages = [message for message in body.messages if message.role == "user"]
    content = user_messages[-1].content.strip() if user_messages else ""
    if not content:
        raise HTTPException(status_code=400, detail="messages must contain a user message")
    if content.startswith("{"):
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {"song": content}


def _voice_url(payload: dict[str, Any]) -> str:
    requested = str(payload.get("voice") or "").strip()
    if requested:
        spec = resolve_voice(requested)
        if spec is None:
            # Never enumerate voice names here: custom whitelist entries rely on
            # staying unknown; the plaza is the only public browsable surface.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown voice {requested!r}; browse and pick a voice at "
                    f"{plaza_url()}, then pass its name as voice"
                ),
            )
        return spec.url
    configured = os.environ.get("SING_VOICE_URL", "").strip()
    if configured:
        return configured
    spec = resolve_voice("")
    if spec is None:
        raise HTTPException(status_code=503, detail="no voice model is configured")
    return spec.url


def _resolved_voice_name(payload: dict[str, Any]) -> str:
    """The catalog/whitelist name behind this request, for usage counters."""
    requested = str(payload.get("voice") or "").strip()
    if requested:
        spec = resolve_voice(requested)
        return spec.name if spec is not None else ""
    if os.environ.get("SING_VOICE_URL", "").strip():
        return ""
    spec = resolve_voice("")
    return spec.name if spec is not None else ""


def _config(payload: dict[str, Any]) -> SingConfig:
    return SingConfig(
        voice_model_url=_voice_url(payload),
        model=os.environ.get("SING_REPLICATE_MODEL", "zsxkib/realistic-voice-cloning"),
        model_version=os.environ.get("SING_REPLICATE_VERSION", ""),
        replicate_base_url=os.environ.get("SING_REPLICATE_BASE_URL", DEFAULT_REPLICATE_BASE),
        pitch=_as_int(
            payload.get("pitch"),
            _as_int(os.environ.get("SING_PITCH"), 2, minimum=-24, maximum=24),
            minimum=-24,
            maximum=24,
        ),
        pitch_mode=str(payload.get("pitch_mode") or "no-change"),
        start=_as_int(
            payload.get("start"),
            _as_int(os.environ.get("SING_START"), 60, minimum=0, maximum=3600),
            minimum=0,
            maximum=3600,
        ),
        duration=_as_int(
            payload.get("duration"),
            _as_int(os.environ.get("SING_DURATION"), 25, minimum=5, maximum=600),
            minimum=5,
            maximum=600,
        ),
        instrumental_volume=_as_int(
            payload.get("instrumental_volume"),
            _as_int(
                os.environ.get("SING_INSTRUMENTAL_VOLUME"),
                VOLUME_MIN,
                minimum=VOLUME_MIN,
                maximum=VOLUME_MAX,
            ),
            minimum=VOLUME_MIN,
            maximum=VOLUME_MAX,
        ),
        backup_vocals_volume=_as_int(
            payload.get("backup_vocals_volume"),
            _as_int(
                os.environ.get("SING_BACKUP_VOCALS_VOLUME"),
                VOLUME_MIN,
                minimum=VOLUME_MIN,
                maximum=VOLUME_MAX,
            ),
            minimum=VOLUME_MIN,
            maximum=VOLUME_MAX,
        ),
        music_source=str(
            payload.get("source") or os.environ.get("SING_MUSIC_SOURCE", "") or "bilibili"
        ).strip(),
        cache_ttl_hours=_as_float(
            os.environ.get("SING_CACHE_TTL_HOURS"), 168.0, minimum=0.0, maximum=8760.0
        ),
        cache_max_entries=_as_int(
            os.environ.get("SING_CACHE_MAX_ENTRIES"), 50, minimum=0, maximum=5000
        ),
        prediction_timeout=_as_float(
            os.environ.get("SING_PREDICTION_TIMEOUT"), 1800.0, minimum=60.0, maximum=3600.0
        ),
    )


def _render(payload: dict[str, Any]) -> dict[str, Any]:
    config = _config(payload)
    voice_name = _resolved_voice_name(payload)
    url = str(payload.get("url") or "").strip()
    song = str(payload.get("song") or "").strip()
    if url:
        result = render_song(url, config)
    elif song:
        result = render_song_by_query(song, config)
    else:
        raise HTTPException(status_code=400, detail="url or song is required")
    if voice_name:
        try:
            increment_usage(voice_name)
        except Exception:  # noqa: BLE001 - counters must never break a render
            logger.warning("voice usage counter failed", exc_info=True)
    return result.as_block()


def _job_payload(body: JobRequest) -> dict[str, Any]:
    return {
        key: value
        for key, value in body.model_dump().items()
        if key != "model" and value not in (None, "")
    }


# The lambda resolves ``_render`` at call time so tests can monkeypatch it.
_JOBS = JobManager(lambda payload: _render(payload))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models", dependencies=[Depends(_require_token)])
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": 0,
                "owned_by": "octop",
            }
            for model in (_DEFAULT_MODEL, _VOICES_MODEL, _SEARCH_MODEL)
        ],
    }


@app.post("/v1/songs/search", dependencies=[Depends(_require_token)])
async def search_song_candidates(body: SongSearchRequest) -> dict[str, Any]:
    """Search the configured music source; clients use this for the confirm step."""
    query = " ".join((body.query or "").split())
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    source = (body.source or os.environ.get("SING_MUSIC_SOURCE", "") or "bilibili").strip()
    try:
        candidates = await asyncio.to_thread(search_songs, query, body.limit, source)
    except ClientSongError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"object": "list", "query": query, "data": [item.as_dict() for item in candidates]}


@app.get("/v1/voices", dependencies=[Depends(_require_token)])
def list_voices() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [],
        "note": _VOICES_NOTE,
        "plaza_url": plaza_url(),
    }


def _voices_block() -> dict[str, Any]:
    return {
        "type": "guide",
        "text": _VOICES_NOTE,
        "plaza_url": plaza_url(),
    }


def _candidates_block(payload: dict[str, Any]) -> dict[str, Any]:
    query = " ".join(str(payload.get("query") or "").split())
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    limit = _as_int(payload.get("limit"), 3, minimum=1, maximum=5)
    source = str(
        payload.get("source") or os.environ.get("SING_MUSIC_SOURCE", "") or "bilibili"
    ).strip()
    candidates = search_songs(query, limit, source)
    return {
        "type": "candidates",
        "query": query,
        "data": [item.as_dict() for item in candidates],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(_require_token)])
async def chat_completions(body: ChatCompletionRequest) -> dict[str, Any]:
    model = (body.model or _DEFAULT_MODEL).strip()
    if model == _VOICES_MODEL:
        block: dict[str, Any] = _voices_block()
    elif model == _SEARCH_MODEL:
        try:
            block = await asyncio.to_thread(_candidates_block, _request_payload(body))
        except HTTPException:
            raise
        except ClientSongError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        payload = _request_payload(body)
        try:
            block = await asyncio.to_thread(_render, payload)
        except HTTPException:
            raise
        except ClientSongError as exc:
            # Song-level problems (VIP track, no results): 4xx so relays such as
            # new-api pass the message through instead of retrying the channel.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "id": f"chatcmpl-sing-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(block, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/sing/jobs", status_code=202, dependencies=[Depends(_require_token)])
@app.post("/sing/v1/jobs", status_code=202, dependencies=[Depends(_require_token)])
async def submit_sing_job(body: JobRequest) -> dict[str, Any]:
    payload = _job_payload(body)
    if not payload.get("url") and not payload.get("song"):
        raise HTTPException(status_code=400, detail="url or song is required")
    try:
        # Validate the voice and static config now; the long work runs in a job.
        _config(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _JOBS.view(_JOBS.submit(payload))


@app.get("/v1/sing/jobs/{job_id}", dependencies=[Depends(_require_token)])
@app.get("/sing/v1/jobs/{job_id}", dependencies=[Depends(_require_token)])
async def get_sing_job(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _JOBS.view(job)


UPLOAD_DIR_ENV = "SING_UPLOAD_DIR"
PUBLIC_BASE_ENV = "SING_PUBLIC_BASE_URL"
HF_REPO_ENV = "SING_HF_REPO"
HF_TOKEN_ENV = "SING_HF_TOKEN"
HF_PREFIX_ENV = "SING_HF_PREFIX"
MS_REPO_ENV = "SING_MS_REPO"
MS_TOKEN_ENV = "SING_MS_TOKEN"
MS_PREFIX_ENV = "SING_MS_PREFIX"
_RATE_WINDOW_SECONDS = 86400.0
_recent_submissions: dict[str, list[float]] = {}


def _upload_dir() -> Path | None:
    raw = os.environ.get(UPLOAD_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _public_base() -> str | None:
    raw = os.environ.get(PUBLIC_BASE_ENV, "").strip()
    return raw.rstrip("/") if raw else None


def _hf_repo() -> str | None:
    raw = os.environ.get(HF_REPO_ENV, "").strip()
    return raw or None


def _hf_token() -> str:
    return os.environ.get(HF_TOKEN_ENV, "").strip()


def _hf_prefix() -> str:
    raw = os.environ.get(HF_PREFIX_ENV, "").strip().strip("/")
    return raw or "uploads"


def _ms_repo() -> str | None:
    raw = os.environ.get(MS_REPO_ENV, "").strip()
    return raw or None


def _ms_token() -> str:
    return os.environ.get(MS_TOKEN_ENV, "").strip()


def _ms_prefix() -> str:
    raw = os.environ.get(MS_PREFIX_ENV, "").strip().strip("/")
    return raw or "uploads"


def _storage_ready() -> bool:
    """File uploads need an HF/ModelScope target or a local public dir."""
    if _hf_repo() and _hf_token():
        return True
    if _ms_repo() and _ms_token():
        return True
    return _upload_dir() is not None and _public_base() is not None


def _max_upload_mb() -> int:
    return _as_int(os.environ.get("SING_UPLOAD_MAX_MB"), 300, minimum=1, maximum=2048)


_LANGUAGE_VALUES = frozenset({"zh", "ja", "en", "ko", "other", "unknown"})
_GENDER_VALUES = frozenset({"female", "male", "neutral", "unknown"})
_RVC_VALUES = frozenset({"v1", "v2", "unknown"})
_TAG_SPLIT_RE = re.compile(r"[,，、\s]+")


def _choice(value: Any, allowed: frozenset[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else ""


def _parse_tags(value: Any) -> list[str]:
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
        tag = tag[:16]
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= 8:
            break
    return tags


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else ""


def _rate_ok(uid: int, ip: str) -> bool:
    limit = _as_int(os.environ.get("SING_UPLOAD_DAILY_LIMIT"), 5, minimum=0, maximum=1000)
    if limit <= 0:
        return True
    key = f"u{uid}" if uid else f"ip{ip}"
    now = time.time()
    stamps = [
        stamp for stamp in _recent_submissions.get(key, []) if now - stamp < _RATE_WINDOW_SECONDS
    ]
    if len(stamps) >= limit:
        _recent_submissions[key] = stamps
        return False
    stamps.append(now)
    _recent_submissions[key] = stamps
    return True


def _ensure_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http/https 链接")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("链接缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"无法解析链接域名：{host}") from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global:
            raise ValueError("链接指向非公网地址，已拒绝")


def _download_zip(url: str, dest: Path, max_bytes: int) -> None:
    try:
        _ensure_public_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise HTTPException(status_code=413, detail="文件超过大小限制")
            total = 0
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(status_code=413, detail="文件超过大小限制")
                    out.write(chunk)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"下载模型失败：{exc}") from exc


async def _save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> None:
    def _copy() -> None:
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("file too large")
                out.write(chunk)

    try:
        await asyncio.to_thread(_copy)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail="文件超过大小限制") from exc


def _review_submission(
    path: Path,
    *,
    label: str,
    flowbee_user: str,
    source_url: str,
    upload_dir: Path | None,
    public_base: str | None,
) -> dict[str, Any]:
    review = review_archive(path, max_bytes=_max_upload_mb() * 1024 * 1024)
    if not review.approved:
        return {"approved": False, "reason": review.reason, "name": "", "url": ""}
    llm_ok, llm_reason = llm_review(
        {
            **review.summary,
            "label": label,
            "flowbee_user": flowbee_user,
            "source": "link" if source_url else "upload",
            "source_host": urllib.parse.urlparse(source_url).netloc if source_url else "",
        }
    )
    if llm_ok is False:
        return {"approved": False, "reason": llm_reason, "name": "", "url": ""}
    name = generate_name(label, set(load_voices().keys()))
    if source_url:
        url = source_url
        source_kind = "link"
    elif _hf_repo() and _hf_token():
        path_in_repo = f"{_hf_prefix()}/{name}.zip"
        try:
            url = hf_upload(
                path,
                repo_id=_hf_repo() or "",
                path_in_repo=path_in_repo,
                token=_hf_token(),
            )
        except Exception as exc:  # noqa: BLE001 - surface operator-actionable reason
            logger.warning("huggingface upload failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="上传到 Hugging Face 失败，请稍后重试或改用模型直链",
            ) from exc
        source_kind = "hf"
    elif _ms_repo() and _ms_token():
        path_in_repo = f"{_ms_prefix()}/{name}.zip"
        try:
            url = modelscope_upload(
                path,
                repo_id=_ms_repo() or "",
                path_in_repo=path_in_repo,
                token=_ms_token(),
            )
        except Exception as exc:  # noqa: BLE001 - surface operator-actionable reason
            logger.warning("modelscope upload failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="上传到 ModelScope 失败，请稍后重试或改用模型直链",
            ) from exc
        source_kind = "ms"
    else:
        if upload_dir is None or public_base is None:
            raise HTTPException(status_code=503, detail="服务器未开启文件上传")
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{name}.zip"
        shutil.copyfile(path, dest)
        url = f"{public_base}/uploads/{dest.name}"
        source_kind = "upload"
    add_voice(
        name,
        label,
        url,
        extra={"added_by": flowbee_user, "source": source_kind, "added_at": int(time.time())},
    )
    return {
        "approved": True,
        "reason": f"{review.reason}；{llm_reason}",
        "name": name,
        "url": url,
    }


@app.post("/v1/voice-requests")
async def submit_voice_request(request: Request) -> dict[str, Any]:
    identity = require_identity(request)
    check_origin(request)
    ip = _client_ip(request)
    if not _rate_ok(identity.uid, ip):
        raise HTTPException(status_code=429, detail="提交过于频繁，请明天再试")
    content_type = (request.headers.get("content-type") or "").lower()
    label = ""
    source_url = ""
    tags_value: Any = []
    language = ""
    gender = ""
    rvc_version = ""
    description = ""
    upload: UploadFile | None = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        label = str(form.get("label") or "").strip()
        source_url = str(form.get("url") or "").strip()
        tags_value = form.get("tags") or []
        language = str(form.get("language") or "")
        gender = str(form.get("gender") or "")
        rvc_version = str(form.get("rvc_version") or "")
        description = str(form.get("description") or "")
        candidate = form.get("file")
        if isinstance(candidate, UploadFile) and candidate.filename:
            upload = candidate
    else:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail="请求体必须是 JSON 或 multipart 表单"
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
        label = str(body.get("label") or "").strip()
        source_url = str(body.get("url") or "").strip()
        tags_value = body.get("tags") or []
        language = str(body.get("language") or "")
        gender = str(body.get("gender") or "")
        rvc_version = str(body.get("rvc_version") or "")
        description = str(body.get("description") or "")
    label = " ".join(label.split())[:80]
    tags = _parse_tags(tags_value)
    language = _choice(language, _LANGUAGE_VALUES)
    gender = _choice(gender, _GENDER_VALUES)
    rvc_version = _choice(rvc_version, _RVC_VALUES)
    description = " ".join(description.split())[:500]
    if not label:
        raise HTTPException(status_code=400, detail="请填写音色显示名")
    if upload is None and not source_url:
        raise HTTPException(status_code=400, detail="请上传 zip 文件或提供模型直链")
    max_bytes = _max_upload_mb() * 1024 * 1024
    upload_dir = _upload_dir()
    public_base = _public_base()
    if upload is not None and not _storage_ready():
        raise HTTPException(
            status_code=503,
            detail="服务器未配置模型存储，请改用模型直链（huggingface / modelscope 等）",
        )
    descriptor, temp_name = tempfile.mkstemp(prefix="sing-voice-", suffix=".zip")
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        if upload is not None:
            await _save_upload(upload, temp, max_bytes)
        else:
            await asyncio.to_thread(_download_zip, source_url, temp, max_bytes)
        result = await asyncio.to_thread(
            _review_submission,
            temp,
            label=label,
            flowbee_user=identity.username,
            source_url=source_url,
            upload_dir=upload_dir,
            public_base=public_base,
        )
    finally:
        temp.unlink(missing_ok=True)
    request_id = new_request_id()
    record = build_request_record(
        request_id=request_id,
        name=str(result["name"]),
        label=label,
        url=str(result["url"]),
        flowbee_user=identity.username,
        source="link" if source_url else "upload",
        approved=bool(result["approved"]),
        reason=str(result["reason"]),
        flowbee_uid=identity.uid,
        tags=tags,
        language=language,
        gender=gender,
        rvc_version=rvc_version,
        description=description,
    )
    await asyncio.to_thread(save_request, record)
    await asyncio.to_thread(
        add_event,
        request_id,
        record["name"],
        record["status"],
        actor_uid=identity.uid,
        actor_role="system",
        reason=record["reason"],
    )
    return {
        "id": request_id,
        "status": record["status"],
        "label": label,
        "name": result["name"],
        "reason": result["reason"],
        "tags": tags,
        "language": language,
        "gender": gender,
        "rvc_version": rvc_version,
        "description": description,
        "visibility": record["visibility"],
        "status_path": f"/v1/voice-requests/{request_id}",
    }


def _delete_storage(record: dict[str, Any]) -> None:
    name = str(record.get("name") or "")
    source = str(record.get("source") or "")
    try:
        if source == "ms" and _ms_repo() and _ms_token():
            modelscope_delete(
                repo_id=_ms_repo() or "",
                token=_ms_token(),
                path_in_repo=f"{_ms_prefix()}/{name}.zip",
            )
        elif source == "hf" and _hf_repo() and _hf_token():
            hf_delete(
                repo_id=_hf_repo() or "",
                token=_hf_token(),
                path_in_repo=f"{_hf_prefix()}/{name}.zip",
            )
        elif source == "upload":
            upload_dir = _upload_dir()
            if upload_dir is not None:
                (upload_dir / f"{name}.zip").unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - best effort, record still gets deleted
        logger.warning("voice storage delete failed for %s: %s", name, exc)


@app.get("/v1/auth/login")
def auth_login(next_path: str = Query(DEFAULT_NEXT, alias="next")) -> RedirectResponse:
    if not sso_secret() or not jwt_secret():
        raise HTTPException(status_code=503, detail="登录服务未配置")
    state = new_state()
    target = f"{sso_url()}?state={urllib.parse.quote(state)}"
    response = RedirectResponse(target, status_code=302)
    set_sso_cookie(response, state, normalize_next(next_path))
    return response


@app.get("/v1/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    stored = read_sso_cookie(request)
    next_path = normalize_next(stored[1] if stored else DEFAULT_NEXT)

    def failure(reason: str) -> RedirectResponse:
        response = RedirectResponse(
            f"{plaza_base()}{next_path}?login=failed&reason={urllib.parse.quote(reason)}",
            status_code=302,
        )
        clear_sso_cookie(response)
        return response

    if stored is None:
        return failure("登录状态已过期，请重试")
    if not hmac.compare_digest(stored[0], state or ""):
        return failure("登录校验失败，请重试")
    try:
        identity = verify_sso_ticket(code)
        token = issue_session(identity)
    except HTTPException as exc:
        return failure(str(exc.detail))
    response = RedirectResponse(f"{plaza_base()}{next_path}", status_code=302)
    clear_sso_cookie(response)
    set_session_cookie(response, token)
    logger.info("sso login ok: uid=%s username=%s", identity.uid, identity.username)
    return response


@app.get("/v1/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    identity = require_identity(request)
    return {"uid": identity.uid, "username": identity.username, "name": identity.name}


@app.post("/v1/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    check_origin(request)
    response = JSONResponse({"ok": True})
    clear_session_cookie(response)
    return response


@app.get("/v1/voice-requests/mine")
def my_voice_requests(request: Request) -> dict[str, Any]:
    identity = require_identity(request)
    return {"submissions": list_requests_by_uid(identity.uid)}


def _set_publish_state(request: Request, request_id: str, visibility: str) -> dict[str, Any]:
    identity = require_identity(request)
    check_origin(request)
    record = get_request(request_id)
    if record is None or record.get("flowbee_uid") != identity.uid:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        updated = set_visibility(
            request_id,
            visibility,
            actor_uid=identity.uid,
            actor_role="user",
        )
    except StateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True, "submission": updated}


@app.post("/v1/voice-requests/{request_id}/publish")
def publish_voice_request(request: Request, request_id: str) -> dict[str, Any]:
    return _set_publish_state(request, request_id, "public")


@app.post("/v1/voice-requests/{request_id}/unpublish")
def unpublish_voice_request(request: Request, request_id: str) -> dict[str, Any]:
    return _set_publish_state(request, request_id, "private")


@app.post("/v1/voice-requests/{request_id}/moderate", dependencies=[Depends(_require_token)])
def moderate_voice_request(request_id: str, body: ModerationRequest) -> dict[str, Any]:
    record = get_request(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        updated = set_moderation(
            request_id,
            body.moderation,
            actor_role="admin",
            reason=body.reason[:200],
        )
    except StateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True, "submission": updated}


@app.delete("/v1/voice-requests/{request_id}")
def delete_voice_request(request: Request, request_id: str) -> dict[str, Any]:
    identity = require_identity(request)
    check_origin(request)
    record = get_request(request_id)
    if record is None or record.get("flowbee_uid") != identity.uid:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.get("status") == "deleted":
        return {"ok": True}
    name = str(record.get("name") or "")
    if name and record.get("status") == "approved":
        if remove_voice(name):
            logger.info("removed voice %s from whitelist", name)
        _delete_storage(record)
    mark_deleted(request_id, actor_uid=identity.uid, actor_role="user")
    return {"ok": True, "name": name}


@app.get("/v1/voices/public")
def public_voices(
    limit: int = Query(default=24, ge=1, le=100),
    sort: str = Query(default="new"),
) -> dict[str, Any]:
    normalized = "hot" if sort.strip().lower() == "hot" else "new"
    return {"voices": list_public_voices(limit=limit, sort=normalized)}


@app.get("/v1/voices/catalog")
def catalog_voices(
    q: str = Query(default=""),
    lang: str = Query(default=""),
    gender: str = Query(default=""),
    kind: str = Query(default="", alias="type"),
    sort: str = Query(default="favorites"),
    limit: int = Query(default=60, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    normalized = sort.strip().lower()
    if normalized not in {"favorites", "label", "hot", "new"}:
        normalized = "favorites"
    return search_catalog(
        q=q,
        language=lang,
        gender=gender,
        kind=kind,
        sort=normalized,
        limit=limit,
        offset=offset,
        usage=usage_map(),
    )


@app.get("/v1/voice-requests/{request_id}")
def voice_request_status(request_id: str) -> dict[str, Any]:
    record = get_request(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    return record


def main() -> None:
    try:
        reconcile_whitelist()
    except Exception:  # noqa: BLE001 - a failed repair must not stop the gateway
        logger.warning("resolver whitelist reconciliation failed", exc_info=True)
    uvicorn.run(
        "sing_gateway.server.sing:app",
        host=os.environ.get("SING_GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("SING_GATEWAY_PORT", "9001")),
        log_level=os.environ.get("SING_GATEWAY_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
