"""The :class:`JobManager` — owns the concurrency primitives + the per-job handle registry.

One instance lives on ``app.state.job_manager``. It owns the single global
``asyncio.Semaphore`` (the memory valve across all jobs), the bounded ``ThreadPoolExecutor`` for
the CPU-bound ``assemble_page`` offload, and a ``dict[str, JobHandle]`` of running jobs. All SQLite
access runs on the engine's single asyncio loop (design §1 M4-ADR-1); worker threads never touch
``conn``.

Enrollment, job creation, and the control actions live here; the per-page streaming loop is
``runner._run_job``. Checkpoint/resume (``recover_on_boot`` + the sweeper), the retry path, and
graceful shutdown are added in tasks 4.3/4.5; the WS subscriber registry is used by 4.4.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from texora_engine.db import jobs_dao, pages_dao
from texora_engine.db.jobs_dao import JobRow
from texora_engine.ingest.base import IngestError
from texora_engine.ingest.images import image_frame_count
from texora_engine.ingest.pdf import open_pdf
from texora_engine.jobs.models import JobOptions, JobProgress, ProgressEvent
from texora_engine.logging_config import get_logger
from texora_engine.pipeline import PipelineDeps
from texora_engine.settings import Settings

logger = get_logger("jobs.manager")

_PDF_EXTS = {".pdf"}


class JobError(Exception):
    """A job-level error surfaced to the control API (bad options / enrollment failure)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class _RateTracker:
    """In-memory EWMA of per-page durations for pages/min + ETA (reset on resume)."""

    alpha: float = 0.3
    ewma_s: float | None = None

    def observe(self, duration_s: float) -> None:
        if self.ewma_s is None:
            self.ewma_s = duration_s
        else:
            self.ewma_s = self.alpha * duration_s + (1.0 - self.alpha) * self.ewma_s

    def pages_per_min(self) -> float | None:
        if self.ewma_s is None or self.ewma_s <= 0:
            return None
        return 60.0 / self.ewma_s


@dataclass
class JobHandle:
    """Runtime state for one active job (not persisted; rebuilt on resume)."""

    job_id: str
    task: asyncio.Task[None] | None = None
    pause_gate: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: bool = False
    rate: _RateTracker = field(default_factory=_RateTracker)
    subscribers: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        # A fresh job starts un-paused: the gate is "set" (open).
        self.pause_gate.set()


class JobManager:
    """Schedules reused ``assemble_page`` per page with bounded concurrency + checkpointing."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        app_state: Any,
        settings: Settings,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        deps_provider: Callable[[Any], Any] | None = None,
    ) -> None:
        self._conn = conn
        self._app_state = app_state
        self._settings = settings
        self._loop = loop
        self._semaphore = asyncio.Semaphore(settings.job_max_concurrent_pages)
        self._pool = ThreadPoolExecutor(
            max_workers=settings.job_page_workers, thread_name_prefix="job-page"
        )
        self._handles: dict[str, JobHandle] = {}
        self._sweeper_task: asyncio.Task[None] | None = None
        # Injected in tests to swap a fast stub pipeline; production uses get_or_build_deps.
        if deps_provider is None:
            from texora_engine.pipeline.deps import get_or_build_deps

            self._deps_provider: Callable[[Any], Any] = get_or_build_deps
        else:
            self._deps_provider = deps_provider

    # --- accessors used by the runner ------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    @property
    def pool(self) -> ThreadPoolExecutor:
        return self._pool

    @property
    def app_state(self) -> Any:
        return self._app_state

    def build_deps(self) -> PipelineDeps:
        """Build or fetch the cached PipelineDeps (may raise the typed deps errors)."""

        deps: PipelineDeps = self._deps_provider(self._app_state)
        return deps

    def handle(self, job_id: str) -> JobHandle | None:
        return self._handles.get(job_id)

    # --- enrollment + creation -------------------------------------------------------------

    def _count_source_pages(self, source_path: str) -> int:
        ext = Path(source_path).suffix.lower()
        if ext in _PDF_EXTS:
            with open_pdf(source_path) as pdf:
                return len(pdf)
        return image_frame_count(source_path, self._settings)

    def _owned_indices(self, total: int, options: JobOptions) -> list[int]:
        """Compute the owned 0-based index set from the options (design §6.1)."""

        if options.pages is not None:
            wanted = sorted({i for i in options.pages if 0 <= i < total})
            dropped = [i for i in options.pages if not (0 <= i < total)]
            if dropped:
                logger.info("dropping out-of-range page indices %s (total=%d)", dropped, total)
            return wanted
        start = options.page_start or 0
        end = options.page_end if options.page_end is not None else total - 1
        start = max(0, start)
        end = min(total - 1, end)
        if end < start:
            return []
        return list(range(start, end + 1))

    def create_job(
        self,
        source_path: str,
        source_name: str,
        options: JobOptions,
        *,
        priority: int = 0,
    ) -> JobRow:
        """Create + enroll a job in ONE transaction, then start its runner task.

        Enrollment runs exactly once here (design §6.1); ``recover_on_boot``/retry never re-enroll.
        """

        try:
            total = self._count_source_pages(source_path)
        except IngestError as exc:
            raise JobError(f"could not read source: {exc}") from exc

        indices = self._owned_indices(total, options)
        job_id = uuid.uuid4().hex
        now = _now_iso()
        job = JobRow(
            id=job_id,
            source_path=source_path,
            source_name=source_name,
            status="running",
            options_json=options.model_dump_json(),
            total_pages=total,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        jobs_dao.create_job(self._conn, job)
        pages_dao.bulk_insert_pending(
            self._conn, job_id, [(uuid.uuid4().hex, idx) for idx in indices]
        )
        self._start_job_task(job_id)
        return jobs_dao.get_job(self._conn, job_id) or job

    def _start_job_task(self, job_id: str) -> None:
        from texora_engine.jobs.runner import run_job

        handle = JobHandle(job_id=job_id)
        self._handles[job_id] = handle
        loop = self._loop or asyncio.get_event_loop()
        handle.task = loop.create_task(run_job(self, job_id))

    # --- progress --------------------------------------------------------------------------

    def progress(self, job_id: str) -> JobProgress:
        counts = pages_dao.counts(self._conn, job_id)
        handle = self._handles.get(job_id)
        rate = handle.rate.pages_per_min() if handle else None
        remaining = counts.pending + counts.leased
        eta = (remaining / rate * 60.0) if (rate and rate > 0) else None
        return JobProgress(
            total=counts.total,
            pending=counts.pending,
            leased=counts.leased,
            done=counts.done,
            failed=counts.failed,
            needs_review=counts.needs_review,
            pages_per_min=rate,
            eta_seconds=eta,
        )

    # --- progress delivery (subscribers wired in task 4.4) ---------------------------------

    def emit_progress(
        self,
        job_id: str,
        *,
        status: str,
        page_index: int | None = None,
        page_status: str | None = None,
        error: str | None = None,
        terminal: bool = False,
    ) -> ProgressEvent:
        """Build a :class:`ProgressEvent` and fan it out to the job's WS subscribers."""

        event = ProgressEvent(
            job_id=job_id,
            status=status,
            page_index=page_index,
            page_status=page_status,
            progress=self.progress(job_id),
            error=error,
            terminal=terminal,
        )
        handle = self._handles.get(job_id)
        if handle:
            self._fan_out(handle, event)
        return event

    def _fan_out(self, handle: JobHandle, event: ProgressEvent) -> None:
        # Subscribers are async send callables registered by the WS route (task 4.4). Best-effort:
        # a slow/broken subscriber never blocks the runner.
        for send in list(handle.subscribers):
            try:
                result = send(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:  # noqa: BLE001 - a broken subscriber must not break the runner
                logger.debug("dropping a broken progress subscriber for job %s", handle.job_id)
