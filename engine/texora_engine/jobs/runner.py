"""The streaming per-page job runner — ``run_job`` (design §3.1).

One ``asyncio.Task`` per running job. The loop leases the next owned page, renders it (PDF: the
indexed ``render_pdf_page`` on a single ``open_pdf`` handle so a resumed job renders ONLY owned
indices; image: the lazy ``iter_image_pages``, pre-resume frames decoded-and-skipped), offloads
the reused M3 ``assemble_page`` to the bounded thread pool, writes the idempotent per-page export,
and marks the page ``done``/``failed`` — a failed page never kills the job. Recognition is reused
UNCHANGED; the runner only schedules it.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
from PIL import Image

from texora_engine.db import jobs_dao, pages_dao
from texora_engine.ingest.base import IngestError, RenderedPage
from texora_engine.ingest.images import iter_image_pages
from texora_engine.ingest.pdf import open_pdf, render_pdf_page
from texora_engine.jobs.models import JobOptions
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.pipeline import PageResult, PipelineDeps, assemble_page
from texora_engine.pipeline.page_result import RegionContent
from texora_engine.pipeline_config import IngestConfig
from texora_engine.recognizers.base import RecognitionStatus
from texora_engine.recognizers.text_tesseract import TesseractUnavailable

if TYPE_CHECKING:
    from texora_engine.jobs.manager import JobManager

logger = get_logger("jobs.runner")

_PDF_EXTS = {".pdf"}
_DEPS_ERRORS = (ModelNotReady, TesseractUnavailable)

# A render primitive produces the leased page's (metadata, bitmap); the caller closes the bitmap.
RenderFn = Callable[[], tuple[RenderedPage, Image.Image]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _lease_token() -> str:
    return uuid.uuid4().hex


def _lease_expiry(ttl_s: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=ttl_s)).isoformat()


def rollup_status(page: PageResult) -> str:
    """Roll content quality up from a :class:`PageResult` to ``ok|needs_review|failed``.

    Orthogonal to the lease lifecycle: a successfully recognized page is ``status='done'`` even
    when its content is ``needs_review`` (design §4.2, M4-ADR-9).
    """

    statuses = {page.status}
    for content in page.contents:
        statuses.add(content.status)
        for run in content.inlines:
            statuses.add(run.status)
    if RecognitionStatus.FAILED in statuses:
        return "failed"
    if RecognitionStatus.NEEDS_REVIEW in statuses:
        return "needs_review"
    return "ok"


def _avg_confidence(page: PageResult) -> float | None:
    """Mean region confidence for the page (None when the page has no regions)."""

    confs = [c.confidence for c in page.contents]
    if not confs:
        return None
    return sum(confs) / len(confs)


def content_text(content: RegionContent) -> str | None:
    """Best-effort searchable text/latex for a region (fed to FTS via the region DAO in 4.3)."""

    if content.text:
        return content.text
    if content.latex:
        return content.latex
    runs: list[str] = []
    for run in content.inlines:
        if run.text:
            runs.append(run.text)
        elif run.latex:
            runs.append(run.latex)
    joined = " ".join(runs).strip()
    return joined or None


def _ingest_config(deps: PipelineDeps, options: JobOptions) -> IngestConfig:
    """Resolve the IngestConfig with the job's optional DPI override applied (clamped)."""

    ingest = deps.pipeline_config.ingest
    if options.dpi is not None:
        clamped = max(72, min(options.dpi, ingest.max_dpi))
        ingest = ingest.model_copy(update={"base_dpi": clamped})
    return ingest


async def run_job(manager: JobManager, job_id: str) -> None:
    """Run (or resume) a job to completion. Never raises into the event loop."""

    try:
        await _run_job(manager, job_id)
    except asyncio.CancelledError:
        raise
    except (
        Exception
    ) as exc:  # noqa: BLE001 - a runner crash becomes a job failure, not a loop crash
        logger.exception("job %s crashed; marking failed", job_id)
        jobs_dao.set_status(
            manager.conn, job_id, "failed", updated_at=_now_iso(), error=f"runner error: {exc}"
        )
        manager.emit_progress(job_id, status="failed", error=str(exc), terminal=True)


async def _run_job(manager: JobManager, job_id: str) -> None:
    conn = manager.conn
    job = jobs_dao.get_job(conn, job_id)
    if job is None:
        logger.warning("run_job for missing job %s", job_id)
        return

    # Build deps once up-front; a deps-build failure fails the JOB gracefully (design §11).
    try:
        deps = manager.build_deps()
    except _DEPS_ERRORS as exc:
        _fail_job(manager, job_id, f"models not ready: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 - factory misconfig etc. fails the job, not the loop
        _fail_job(manager, job_id, f"pipeline misconfiguration: {exc}")
        return

    options = JobOptions.model_validate_json(job.options_json)
    cfg = _ingest_config(deps, options)
    source_path = job.source_path
    is_pdf = Path(source_path).suffix.lower() in _PDF_EXTS

    jobs_dao.set_status(conn, job_id, "running", updated_at=_now_iso())
    manager.emit_progress(job_id, status="running")

    if is_pdf:
        await _run_pdf(manager, job_id, source_path, cfg, deps)
    else:
        await _run_image(manager, job_id, source_path, deps)

    # Finalize (design §5): done when every page attempted; the retry path handles failures.
    counts = pages_dao.counts(conn, job_id)
    handle = manager.handle(job_id)
    if handle is not None and handle.cancel_requested:
        jobs_dao.set_status(conn, job_id, "canceled", updated_at=_now_iso())
        manager.emit_progress(job_id, status="canceled", terminal=True)
        return
    jobs_dao.set_status(conn, job_id, "done", updated_at=_now_iso())
    manager.emit_progress(job_id, status="done", terminal=True)
    logger.info(
        "job %s finished: done=%d failed=%d total=%d",
        job_id,
        counts.done,
        counts.failed,
        counts.total,
    )


async def _run_pdf(
    manager: JobManager,
    job_id: str,
    source_path: str,
    cfg: IngestConfig,
    deps: PipelineDeps,
) -> None:
    """PDF path: open once, render ONLY owned/pending indices (design §3.1 MEDIUM-F1)."""

    with open_pdf(source_path) as pdf:
        while True:
            leased = await _lease_next(manager, job_id)
            if leased is None:
                return
            if not await _gate(manager, job_id):
                return
            render = _pdf_render_fn(pdf, leased.page_index, cfg)
            await _process_leased(manager, job_id, leased, render, deps)


def _pdf_render_fn(pdf: pdfium.PdfDocument, index: int, cfg: IngestConfig) -> RenderFn:
    """Bind an indexed PDF render into a zero-arg render primitive."""

    def _render() -> tuple[RenderedPage, Image.Image]:
        return render_pdf_page(pdf, index, cfg)

    return _render


def _static_render_fn(rendered: RenderedPage, image: Image.Image) -> RenderFn:
    """Bind an already-decoded image frame into a zero-arg render primitive."""

    def _render() -> tuple[RenderedPage, Image.Image]:
        return rendered, image

    return _render


async def _run_image(
    manager: JobManager, job_id: str, source_path: str, deps: PipelineDeps
) -> None:
    """Image path: sequential lazy frames; frames before the owned index are skipped (§3.1).

    ``lease_next`` returns the lowest pending index; the frame iterator is advanced (closing each
    skipped frame immediately) until it reaches that index, so a resumed image job pays the cheap
    decode-and-skip for already-done frames but the expensive recognition only for owned frames,
    with exactly one frame bitmap in flight.
    """

    settings = manager.settings
    frames: Iterator[tuple[RenderedPage, Image.Image]] = iter_image_pages(source_path, settings)
    while True:
        leased = await _lease_next(manager, job_id)
        if leased is None:
            return
        if not await _gate(manager, job_id):
            return
        frame = _advance_to_index(frames, leased.page_index)
        if frame is None:
            return
        rendered, image = frame
        render = _static_render_fn(rendered, image)
        await _process_leased(manager, job_id, leased, render, deps)


def _advance_to_index(
    frames: Iterator[tuple[RenderedPage, Image.Image]],
    target: int,
) -> tuple[RenderedPage, Image.Image] | None:
    """Advance the frame iterator to ``target``, closing (skipping) earlier frames.

    Returns the ``(rendered, image)`` frame at ``target``, or ``None`` when the iterator is
    exhausted / over-shoots (a defensive guard — indices always align for a single producer whose
    ``lease_next`` returns the lowest pending index, which equals the next un-skipped frame).
    """

    while True:
        try:
            rendered, image = next(frames)
        except StopIteration:
            return None
        if rendered.index == target:
            return rendered, image
        if rendered.index > target:
            image.close()
            return None
        image.close()


async def _lease_next(manager: JobManager, job_id: str) -> pages_dao.LeasedPage | None:
    expires = _lease_expiry(manager.settings.job_lease_ttl_s)
    return pages_dao.lease_next(manager.conn, job_id, _lease_token(), expires)


async def _gate(manager: JobManager, job_id: str) -> bool:
    """Honor pause/cancel before processing a leased page. Returns False to stop the loop."""

    handle = manager.handle(job_id)
    if handle is None:
        return True
    await handle.pause_gate.wait()
    return not handle.cancel_requested


async def _process_leased(
    manager: JobManager,
    job_id: str,
    leased: pages_dao.LeasedPage,
    render: RenderFn,
    deps: PipelineDeps,
) -> None:
    """Render + recognize one leased page under the global semaphore (constant memory)."""

    conn = manager.conn
    loop = asyncio.get_event_loop()
    start = time.monotonic()
    token = _current_lease_token(conn, leased.id)

    async with manager.semaphore:
        try:
            rendered, image = render()
        except IngestError as exc:
            logger.warning("job %s page %d render failed: %s", job_id, leased.page_index, exc)
            pages_dao.mark_failed(conn, leased.id, token, error=str(exc), finished_at=_now_iso())
            _after_page(manager, job_id, leased.page_index, "failed", start)
            return

        try:
            result: PageResult = await loop.run_in_executor(
                manager.pool, assemble_page, rendered, image, deps
            )
            _commit_done(manager, job_id, leased, token, result)
            _after_page(manager, job_id, leased.page_index, "done", start)
        except Exception as exc:  # noqa: BLE001 - per-page isolation (R-JOB-6)
            logger.warning("job %s page %d recognition failed: %s", job_id, leased.page_index, exc)
            pages_dao.mark_failed(conn, leased.id, token, error=str(exc), finished_at=_now_iso())
            _after_page(manager, job_id, leased.page_index, "failed", start)
        finally:
            image.close()


def _current_lease_token(conn: sqlite3.Connection, page_id: str) -> str:
    page = pages_dao.get_page(conn, page_id)
    if page is None:
        return ""
    return page.lease_token or ""


def _commit_done(
    manager: JobManager,
    job_id: str,
    leased: pages_dao.LeasedPage,
    token: str,
    result: PageResult,
) -> None:
    """Persist the page result (the idempotent export writer is wired in task 4.3)."""

    pages_dao.mark_done(
        manager.conn,
        leased.id,
        token,
        rollup_status=rollup_status(result),
        result_json=result.model_dump_json(),
        avg_confidence=_avg_confidence(result),
        finished_at=_now_iso(),
    )


def _after_page(
    manager: JobManager,
    job_id: str,
    page_index: int,
    page_status: str,
    start: float,
) -> None:
    handle = manager.handle(job_id)
    if handle is not None:
        handle.rate.observe(time.monotonic() - start)
    manager.emit_progress(job_id, status="running", page_index=page_index, page_status=page_status)


def _fail_job(manager: JobManager, job_id: str, error: str) -> None:
    logger.error("job %s failed before leasing any page: %s", job_id, error)
    jobs_dao.set_status(manager.conn, job_id, "failed", updated_at=_now_iso(), error=error)
    manager.emit_progress(job_id, status="failed", error=error, terminal=True)
