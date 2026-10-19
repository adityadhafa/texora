"""Per-page failure-isolation tests (design §5, R-JOB-6): timeout, resource guard, retry-failed."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from texora_engine.db import init_db, pages_dao
from texora_engine.ingest.base import RenderedPage, SourceKind
from texora_engine.jobs.guard import PageResourceError, check_page_resources
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.pipeline import PageResult
from texora_engine.recognizers.base import RecognitionStatus
from texora_engine.settings import Settings

from tests._job_harness import make_stub_deps, write_minimal_pdf


def _settings(tmp_path: Path, **over: object) -> Settings:
    base = dict(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


def _manager(settings: Settings) -> JobManager:
    conn = init_db(settings.db_path)
    deps = make_stub_deps(settings)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    return JobManager(
        conn,
        settings=settings,
        app_state=app_state,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _s: deps,
    )


async def _await(manager: JobManager, job_id: str) -> None:
    h = manager.handle(job_id)
    assert h is not None and h.task is not None
    await asyncio.wait_for(h.task, timeout=90)


def test_resource_guard_rejects_oversize_page() -> None:
    rendered = RenderedPage(index=0, width=4000, height=4000, dpi=96, kind=SourceKind.IMAGE)
    with pytest.raises(PageResourceError):
        check_page_resources(rendered, max_pixels=1_000_000)
    # Within bound: no raise.
    check_page_resources(rendered, max_pixels=20_000_000)


@pytest.mark.asyncio
async def test_raising_page_fails_but_job_completes_and_retry_reruns_only_it(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 4)

    import texora_engine.jobs.runner as runner_mod

    real_assemble = runner_mod.assemble_page
    processed: list[int] = []
    poison = {"index": 2, "fail": True}

    def _assemble(rendered: RenderedPage, image: Image.Image, deps: object) -> PageResult:
        processed.append(rendered.index)
        if rendered.index == poison["index"] and poison["fail"]:
            raise RuntimeError("hostile page")
        return real_assemble(rendered, image, deps)

    monkeypatch.setattr(runner_mod, "assemble_page", _assemble)

    mgr = _manager(settings)
    job = mgr.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    await _await(mgr, job.id)

    counts = pages_dao.counts(mgr.conn, job.id)
    assert counts.total == 4
    assert counts.done == 3  # the other three pages complete
    assert counts.failed == 1  # the hostile page is isolated as failed
    # The job still finishes "done" (every page attempted), with a non-zero failed count.
    from texora_engine.db import jobs_dao

    assert jobs_dao.get_job(mgr.conn, job.id).status == "done"

    # Fix the poison and retry: ONLY the previously failed page is re-attempted.
    poison["fail"] = False
    processed.clear()
    mgr.retry_failed(job.id)
    await _await(mgr, job.id)

    assert processed == [2]  # only the failed index re-run; done pages untouched
    assert pages_dao.counts(mgr.conn, job.id).done == 4
    assert pages_dao.counts(mgr.conn, job.id).failed == 0


@pytest.mark.asyncio
async def test_page_timeout_marks_failed_not_reverted(tmp_path: Path, monkeypatch) -> None:
    # A page that runs right up to job_page_timeout_s is marked failed (never reverted / re-leased
    # while in flight — HIGH-3 timeout/TTL ordering). Use 2 page workers so the abandoned slow
    # thread on index 0 does not starve index 1 (the documented abandoned-thread trade-off, §5).
    settings = _settings(tmp_path, job_page_timeout_s=0.3, job_lease_ttl_s=30.0, job_page_workers=2)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 2)

    import texora_engine.jobs.runner as runner_mod

    def _fast_or_slow(rendered: RenderedPage, image: Image.Image, deps: object) -> PageResult:
        image.close()
        if rendered.index == 0:
            time.sleep(2.0)  # exceeds the 0.3s page timeout -> page 0 is force-failed
        return PageResult(
            index=rendered.index,
            width=rendered.width,
            height=rendered.height,
            dpi=rendered.dpi,
            kind=rendered.kind,
            contents=[],
            status=RecognitionStatus.OK,
        )

    monkeypatch.setattr(runner_mod, "assemble_page", _fast_or_slow)

    mgr = _manager(settings)
    job = mgr.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    await _await(mgr, job.id)

    page0 = next(p for p in pages_dao.list_pages(mgr.conn, job.id) if p.page_index == 0)
    assert page0.status == "failed"
    assert page0.error == "page timeout"
    # The job still completes; page 1 is fine.
    assert pages_dao.counts(mgr.conn, job.id).done == 1
