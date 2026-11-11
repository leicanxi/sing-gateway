"""In-process job queue for asynchronous song generation.

The gateway exposes a small submit/query API so every client (AstrBot, Octop,
DSH, plain HTTP) can hand off a multi-minute generation and poll for the
result instead of holding one long request open.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

JOB_TTL_SECONDS = float(os.environ.get("SING_JOB_TTL_SECONDS", "3600"))
MAX_CONCURRENCY = max(1, int(os.environ.get("SING_MAX_CONCURRENCY", "2")))

_DEDUPE_FIELDS = (
    "song",
    "url",
    "artist",
    "voice",
    "start",
    "duration",
    "pitch",
    "pitch_mode",
    "source",
    "instrumental_volume",
    "backup_vocals_volume",
)


def _dedupe_key(payload: dict[str, Any]) -> str:
    values = {key: payload.get(key) for key in _DEDUPE_FIELDS if payload.get(key) not in (None, "")}
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class Job:
    id: str
    payload: dict[str, Any]
    dedupe_key: str
    status: str = "queued"
    stage: str = "queued"
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobManager:
    """Run renders in the background, deduplicate identical submissions."""

    def __init__(self, render: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._render = render
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore: asyncio.Semaphore | None = None

    def submit(self, payload: dict[str, Any]) -> Job:
        self._prune()
        key = _dedupe_key(payload)
        existing_id = self._by_key.get(key)
        if existing_id:
            existing = self._jobs.get(existing_id)
            # Only merge requests that are still in flight (double-clicks,
            # retries while the first render runs). A finished job's audio URL
            # may already be stale, so repeat requests go through the render
            # path again and hit the gateway's own disk cache instead.
            if existing is not None and existing.status in {"queued", "running"}:
                return existing
        job = Job(id=f"job_{uuid.uuid4().hex}", payload=dict(payload), dedupe_key=key)
        self._jobs[job.id] = job
        self._by_key[key] = job.id
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        self._prune()
        return self._jobs.get(job_id)

    def view(self, job: Job) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": job.id,
            "status": job.status,
            "stage": job.stage,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        if job.status == "failed":
            data["error"] = job.error
        if job.status == "succeeded" and job.result:
            source = job.result.get("source")
            url = source.get("url") if isinstance(source, dict) else ""
            data.update(
                {
                    "audio_url": str(url or ""),
                    "filename": str(job.result.get("filename") or ""),
                    "title": str(job.result.get("title") or ""),
                    "artist": str(job.result.get("artist") or ""),
                    "duration_seconds": int(job.result.get("duration_seconds") or 0),
                    "cached": bool(job.result.get("cached")),
                }
            )
            if int(job.result.get("pitch") or 0):
                data["pitch"] = int(job.result.get("pitch") or 0)
            if job.result.get("pitch_auto"):
                data["pitch_auto"] = True
            if job.result.get("source_match"):
                data["source_match"] = str(job.result.get("source_match"))
            if job.result.get("original_artist"):
                data["original_artist"] = str(job.result.get("original_artist"))
            if job.result.get("engine"):
                data["engine"] = str(job.result.get("engine"))
        return data

    async def _run(self, job: Job) -> None:
        try:
            async with self._semaphore_for_jobs():
                job.status = "running"
                job.stage = "generating"
                job.updated_at = time.time()
                result = await asyncio.to_thread(self._render, job.payload)
        except Exception as exc:  # noqa: BLE001 - failures are reported to clients
            job.status = "failed"
            job.stage = "failed"
            job.error = str(exc).strip() or type(exc).__name__
        else:
            job.status = "succeeded"
            job.stage = "done"
            job.result = result
        finally:
            job.updated_at = time.time()

    def _semaphore_for_jobs(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        return self._semaphore

    def _prune(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status != "running" and job.updated_at < cutoff
        ]
        for job_id in expired:
            job = self._jobs.pop(job_id, None)
            if job is not None and self._by_key.get(job.dedupe_key) == job_id:
                self._by_key.pop(job.dedupe_key, None)
