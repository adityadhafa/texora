"""Watch-folder intake tests (design §8, task 4.6) — settle/validate/dedupe/enqueue."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from texora_engine.db import init_db, jobs_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.watch import WatchFolderIngest
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
        watch_settle_s=0.05,
    )


def _manager(settings: Settings) -> JobManager:
    conn = init_db(settings.db_path)
    deps = make_stub_deps(settings)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    return JobManager(
        conn,
        app_state=app_state,
        settings=settings,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _s: deps,
    )


async def _drain(manager: JobManager, job_id: str) -> None:
    """Await the enqueued runner task so the test loop doesn't leave it pending at teardown."""

    handle = manager.handle(job_id)
    if handle is not None and handle.task is not None:
        await asyncio.wait_for(handle.task, timeout=60)


async def test_dropping_a_pdf_enqueues_a_queued_job(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    manager = _manager(settings)
    ingest = WatchFolderIngest(manager)

    pdf = write_minimal_pdf(watch_dir / "dropped.pdf", 1)
    job_id = ingest.process_candidate(str(pdf))
    assert job_id is not None
    job = jobs_dao.get_job(manager.conn, job_id)
    assert job is not None
    # The job exists (running/queued) and its source is the dropped file.
    assert job.source_name == "dropped.pdf"
    assert job.status in ("running", "queued", "done")
    await _drain(manager, job_id)


async def test_dedupe_same_file_mtime_enqueues_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    manager = _manager(settings)
    ingest = WatchFolderIngest(manager)
    pdf = write_minimal_pdf(watch_dir / "dup.pdf", 1)

    first = ingest.process_candidate(str(pdf))
    second = ingest.process_candidate(str(pdf))  # same path + mtime -> de-duped
    assert first is not None
    assert second is None
    await _drain(manager, first)


async def test_unsupported_file_is_skipped(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    manager = _manager(settings)
    ingest = WatchFolderIngest(manager)
    txt = watch_dir / "notes.txt"
    txt.write_text("hello", encoding="utf-8")
    assert ingest.process_candidate(str(txt)) is None
