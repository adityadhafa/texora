"""Streaming job runner tests (design §13, task 4.2) — stub recognizers, REAL synthetic PDF."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from texora_engine.db import init_db, pages_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.settings import Settings

from tests._job_harness import make_stub_deps, write_minimal_pdf

pytestmark = pytest.mark.asyncio


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )


def _manager(tmp_path: Path, settings: Settings) -> JobManager:
    conn = init_db(settings.db_path)
    deps = make_stub_deps(settings)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    return JobManager(
        conn,
        app_state,
        settings,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _state: deps,
    )


async def _await_job(manager: JobManager, job_id: str) -> None:
    handle = manager.handle(job_id)
    assert handle is not None and handle.task is not None
    await asyncio.wait_for(handle.task, timeout=60)


async def test_small_pdf_job_reaches_all_pages_done(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = _manager(tmp_path, settings)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 5)
    job = manager.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    await _await_job(manager, job.id)

    counts = pages_dao.counts(manager.conn, job.id)
    assert counts.total == 5
    assert counts.done == 5
    assert counts.pending == 0
    assert counts.failed == 0


async def test_range_option_enrolls_only_the_range(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = _manager(tmp_path, settings)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 6)
    job = manager.create_job(str(pdf), pdf.name, JobOptions(dpi=72, page_start=2, page_end=4))
    await _await_job(manager, job.id)

    pages = pages_dao.list_pages(manager.conn, job.id)
    assert [p.page_index for p in pages] == [2, 3, 4]
    assert all(p.status == "done" for p in pages)


async def test_explicit_pages_list_drops_out_of_range(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = _manager(tmp_path, settings)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 3)
    job = manager.create_job(str(pdf), pdf.name, JobOptions(dpi=72, pages=[0, 2, 99]))
    await _await_job(manager, job.id)

    pages = pages_dao.list_pages(manager.conn, job.id)
    assert [p.page_index for p in pages] == [0, 2]  # 99 dropped (out of range)


async def test_semaphore_caps_in_flight_pages(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings = settings.model_copy(update={"job_max_concurrent_pages": 2})
    manager = _manager(tmp_path, settings)

    # Instrument the semaphore to record the peak concurrent holders.
    peak = {"n": 0, "cur": 0}
    orig_acquire = manager.semaphore.acquire
    orig_release = manager.semaphore.release

    async def _acquire() -> bool:
        r = await orig_acquire()
        peak["cur"] += 1
        peak["n"] = max(peak["n"], peak["cur"])
        return r

    def _release() -> None:
        peak["cur"] -= 1
        orig_release()

    manager.semaphore.acquire = _acquire  # type: ignore[method-assign]
    manager.semaphore.release = _release  # type: ignore[method-assign]

    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 6)
    job = manager.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    await _await_job(manager, job.id)

    assert pages_dao.counts(manager.conn, job.id).done == 6
    # With a single page producer loop + page_workers=1 the peak is 1, and never exceeds the cap.
    assert peak["n"] <= 2


async def test_image_job_streams_tiff_frames(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = _manager(tmp_path, settings)
    tiff = Path(__file__).resolve().parent / "fixtures" / "multipage.tiff"
    job = manager.create_job(str(tiff), tiff.name, JobOptions())
    await _await_job(manager, job.id)

    counts = pages_dao.counts(manager.conn, job.id)
    assert counts.total == 2
    assert counts.done == 2
