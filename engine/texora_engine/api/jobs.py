"""Job-control REST API + bearer-protected progress WebSocket (design §9, task 4.4).

All routes sit on a ``jobs_router`` guarded by ``Depends(require_token)`` (bearer on every
non-health route). The WebSocket validates the same bearer token explicitly (header path pre-accept,
message-token fallback post-accept — design §9.2). All request/response bodies are Pydantic v2
models. SQLite is touched only through ``db/`` DAOs; the runner/manager own all scheduling.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from texora_engine.db import fts_dao, jobs_dao, pages_dao
from texora_engine.jobs import output
from texora_engine.jobs.manager import JobError, JobManager
from texora_engine.jobs.models import JobOptions, JobProgress, ProgressEvent
from texora_engine.jobs.output import PageOutcome
from texora_engine.jobs.paths import PathValidationError, is_supported_file, validate_source_path
from texora_engine.logging_config import get_logger
from texora_engine.security import require_token

logger = get_logger("api.jobs")

# REST routes are bearer-protected via the HTTP dependency. The WebSocket does its OWN explicit
# token validation (design §9.2), so it lives on a separate router WITHOUT the HTTP dependency
# (HTTPBearer cannot run on a WebSocket scope).
jobs_router = APIRouter(dependencies=[Depends(require_token)], tags=["jobs"])
jobs_ws_router = APIRouter(tags=["jobs"])

_EXPORT_FORMATS = {"md", "tex", "json"}
_CONTENT_TYPES = {"md": "text/markdown", "tex": "application/x-tex", "json": "application/json"}
_ACTIVE = set(jobs_dao.ACTIVE_JOB_STATUSES)
_PRIORITY_MIN, _PRIORITY_MAX = -100, 100
_WS_CLOSE_UNAUTHORIZED = 4401


# --- request / response models (design §9.1) -----------------------------------------------


class JobCreateRequest(BaseModel):
    """Create one job from a single file path + options."""

    path: str = Field(description="Absolute path to a local PDF or image file.")
    options: JobOptions = Field(default_factory=JobOptions)
    priority: int = Field(default=0, description="Scheduling priority (clamped to [-100, 100]).")


class BatchCreateRequest(BaseModel):
    """Create jobs from a list of files/directories."""

    paths: list[str] = Field(description="File or directory paths.")
    options: JobOptions = Field(default_factory=JobOptions)
    priority: int = Field(default=0, description="Scheduling priority (clamped to [-100, 100]).")
    recursive: bool = Field(default=False, description="Recurse into directories (default off).")


class ReprioritizeRequest(BaseModel):
    priority: int = Field(description="New scheduling priority (clamped to [-100, 100]).")


class JobView(BaseModel):
    """A job row + its live progress."""

    id: str
    source_name: str
    source_path: str
    status: str
    total_pages: int
    priority: int
    error: str | None
    created_at: str
    updated_at: str
    progress: JobProgress


class JobListView(BaseModel):
    jobs: list[JobView]


# --- helpers --------------------------------------------------------------------------------


def _manager(request: Request) -> JobManager:
    manager: JobManager | None = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="job manager not initialized",
        )
    return manager


def _job_view(manager: JobManager, job_id: str) -> JobView:
    job = jobs_dao.get_job(manager.conn, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown job id")
    return JobView(
        id=job.id,
        source_name=job.source_name,
        source_path=job.source_path,
        status=job.status,
        total_pages=job.total_pages,
        priority=job.priority,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        progress=manager.progress(job.id),
    )


def _require_job(manager: JobManager, job_id: str) -> jobs_dao.JobRow:
    job = jobs_dao.get_job(manager.conn, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown job id")
    return job


def _clamp_priority(value: int) -> int:
    return max(_PRIORITY_MIN, min(value, _PRIORITY_MAX))


def _validated_path(raw: str, *, allow_dir: bool = False) -> str:
    try:
        return str(validate_source_path(raw, allow_dir=allow_dir))
    except PathValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# --- routes ---------------------------------------------------------------------------------


@jobs_router.post("/jobs", response_model=JobView)
def create_job(req: JobCreateRequest, request: Request) -> JobView:
    manager = _manager(request)
    resolved = _validated_path(req.path)
    try:
        job = manager.create_job(
            resolved, _name_of(resolved), req.options, priority=_clamp_priority(req.priority)
        )
    except JobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _job_view(manager, job.id)


@jobs_router.post("/jobs/batch", response_model=JobListView)
def create_batch(req: BatchCreateRequest, request: Request) -> JobListView:
    manager = _manager(request)
    files: list[str] = []
    for raw in req.paths:
        resolved = validate_source_path_or_422(raw)
        files.extend(_expand(resolved, req.recursive))
    views: list[JobView] = []
    for file_path in files:
        try:
            job = manager.create_job(
                file_path, _name_of(file_path), req.options, priority=_clamp_priority(req.priority)
            )
        except JobError as exc:
            logger.warning("batch: skipping %s: %s", file_path, exc)
            continue
        views.append(_job_view(manager, job.id))
    return JobListView(jobs=views)


@jobs_router.get("/jobs", response_model=JobListView)
def list_jobs(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> JobListView:
    manager = _manager(request)
    rows = jobs_dao.list_jobs(manager.conn, status=status_filter, limit=limit, offset=offset)
    return JobListView(jobs=[_job_view(manager, r.id) for r in rows])


@jobs_router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, request: Request) -> JobView:
    return _job_view(_manager(request), job_id)


@jobs_router.post("/jobs/{job_id}:pause", response_model=JobView)
def pause_job(job_id: str, request: Request) -> JobView:
    manager = _manager(request)
    job = _require_job(manager, job_id)
    if job.status not in _ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"cannot pause a {job.status} job"
        )
    manager.pause(job_id)
    return _job_view(manager, job_id)


@jobs_router.post("/jobs/{job_id}:resume", response_model=JobView)
def resume_job(job_id: str, request: Request) -> JobView:
    manager = _manager(request)
    job = _require_job(manager, job_id)
    if job.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"cannot resume a {job.status} job"
        )
    manager.resume(job_id)
    return _job_view(manager, job_id)


@jobs_router.post("/jobs/{job_id}:cancel", response_model=JobView)
def cancel_job(job_id: str, request: Request) -> JobView:
    manager = _manager(request)
    job = _require_job(manager, job_id)
    if job.status not in _ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"cannot cancel a {job.status} job"
        )
    manager.cancel(job_id)
    return _job_view(manager, job_id)


@jobs_router.post("/jobs/{job_id}:reprioritize", response_model=JobView)
def reprioritize_job(job_id: str, req: ReprioritizeRequest, request: Request) -> JobView:
    manager = _manager(request)
    _require_job(manager, job_id)
    manager.reprioritize(job_id, _clamp_priority(req.priority))
    return _job_view(manager, job_id)


@jobs_router.post("/jobs/{job_id}/pages:retry-failed", response_model=JobView)
def retry_failed(job_id: str, request: Request) -> JobView:
    manager = _manager(request)
    _require_job(manager, job_id)
    manager.retry_failed(job_id)
    return _job_view(manager, job_id)


@jobs_router.get("/jobs/{job_id}/export")
def export_job(
    job_id: str,
    request: Request,
    export_format: str = Query(alias="format"),
) -> StreamingResponse:
    manager = _manager(request)
    job = _require_job(manager, job_id)
    if export_format not in _EXPORT_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported export format {export_format!r}",
        )
    outcomes = _page_outcomes(manager, job_id)
    body = _build_export(manager, job, export_format, outcomes)
    filename = f"{_stem(job.source_name)}.{export_format}"

    async def _stream() -> AsyncIterator[bytes]:
        yield body.encode("utf-8")

    return StreamingResponse(
        _stream(),
        media_type=_CONTENT_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@jobs_router.get("/search", response_model=list[fts_dao.FtsHit])
def search(
    request: Request,
    q: str = Query(min_length=1, max_length=256),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[fts_dao.FtsHit]:
    manager = _manager(request)
    return fts_dao.search(manager.conn, q, limit=limit, offset=offset)


# --- WebSocket progress (design §9.2) -------------------------------------------------------


@jobs_ws_router.websocket("/jobs/{job_id}/events")
async def job_events(ws: WebSocket, job_id: str) -> None:
    """Stream ``ProgressEvent`` JSON for a job (bearer-authenticated, design §9.2)."""

    manager: JobManager | None = getattr(ws.app.state, "job_manager", None)
    expected: str = getattr(ws.app.state, "engine_token", "")
    if not await _authorize_ws(ws, expected):
        return
    if manager is None:
        await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

    def _send(event: ProgressEvent) -> None:
        queue.put_nowait(event)

    manager.subscribe(job_id, _send)
    try:
        # Push an immediate snapshot so a late subscriber sees current state.
        job = jobs_dao.get_job(manager.conn, job_id)
        if job is not None:
            await ws.send_text(
                ProgressEvent(
                    job_id=job_id,
                    status=job.status,
                    progress=manager.progress(job_id),
                    terminal=job.status in jobs_dao.TERMINAL_JOB_STATUSES,
                ).model_dump_json()
            )
        while True:
            event = await queue.get()
            await ws.send_text(event.model_dump_json())
            if event.terminal:
                break
    except Exception:  # noqa: BLE001 - a dropped socket just ends the stream
        logger.debug("ws for job %s closed", job_id)
    finally:
        manager.unsubscribe(job_id, _send)


async def _authorize_ws(ws: WebSocket, expected: str) -> bool:
    """Validate the bearer token (header path pre-accept, message fallback post-accept)."""

    header = ws.headers.get("authorization")
    if header is not None:
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and expected and secrets.compare_digest(token, expected):
            await ws.accept()
            return True
        await ws.close(code=_WS_CLOSE_UNAUTHORIZED)
        return False

    # Fallback: accept, then read one {"token": "..."} frame under a bounded timeout.
    await ws.accept()
    timeout_s = getattr(ws.app.state.settings, "ws_token_timeout_s", 5.0)
    try:
        import json

        raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout_s)
        token = str(json.loads(raw).get("token", ""))
    except (TimeoutError, ValueError, KeyError):
        await ws.close(code=_WS_CLOSE_UNAUTHORIZED)
        return False
    if expected and secrets.compare_digest(token, expected):
        return True
    await ws.close(code=_WS_CLOSE_UNAUTHORIZED)
    return False


# --- small utilities ------------------------------------------------------------------------


def validate_source_path_or_422(raw: str) -> object:
    try:
        return validate_source_path(raw, allow_dir=True)
    except PathValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _expand(resolved: object, recursive: bool) -> list[str]:
    from pathlib import Path

    path = resolved if isinstance(resolved, Path) else Path(str(resolved))
    if path.is_file():
        return [str(path)]
    pattern = "**/*" if recursive else "*"
    return [str(p) for p in sorted(path.glob(pattern)) if is_supported_file(p)]


def _name_of(path_str: str) -> str:
    from pathlib import Path

    return Path(path_str).name


def _stem(name: str) -> str:
    from pathlib import Path

    return Path(name).stem or name


def _page_outcomes(manager: JobManager, job_id: str) -> list[PageOutcome]:
    rows = pages_dao.list_pages(manager.conn, job_id)
    return [PageOutcome(index=r.page_index, status=r.status, error=r.error) for r in rows]


def _build_export(
    manager: JobManager,
    job: jobs_dao.JobRow,
    fmt: str,
    outcomes: list[PageOutcome],
) -> str:
    settings = manager.settings
    if fmt == "md":
        return output.build_markdown(settings, job.id, outcomes)
    if fmt == "tex":
        return output.build_latex(settings, job.id, outcomes)
    return output.build_json(settings, job.id, job.source_name, outcomes)


# Re-export JobOptions so callers importing from api.jobs get the model (used by tests).
__all__ = [
    "jobs_router",
    "jobs_ws_router",
    "JobCreateRequest",
    "BatchCreateRequest",
    "JobView",
    "JobOptions",
]
