"""Interrupt/resume proof (design §12, DoD-2) — kill mid-job, recover, finish with no lost/dup.

Simulates a crash (cancel the task + drop the manager without graceful shutdown so some pages stay
``leased``), reopens the DB, runs ``recover_on_boot``, resumes, and asserts the final ``done`` set
== the full index set with no duplicates (a per-index render counter). Scaled locally; the full
5,000-page count is the nightly CI gate.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.make_synthetic_pdf import build_synthetic_pdf
from tests._job_harness import make_stub_deps
from texora_engine.db import init_db, pages_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.settings import Settings

_PAGES = int(os.environ.get("TEXORA_PROOF_RESUME_PAGES", "60"))


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )


def _manager(settings: Settings, deps: object) -> JobManager:
    conn = init_db(settings.db_path)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    return JobManager(
        conn,
        app_state=app_state,
        settings=settings,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _s: deps,
    )


@pytest.mark.asyncio
async def test_kill_mid_job_resumes_with_no_lost_or_dup(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    deps = make_stub_deps(settings)
    pdf = build_synthetic_pdf(tmp_path / "resume.pdf", _PAGES, seed=3)

    import texora_engine.jobs.runner as runner_mod

    render_counts: dict[int, int] = {}
    real_render = runner_mod.render_pdf_page

    def _counting_render(pdf_doc, index, cfg):  # type: ignore[no-untyped-def]
        render_counts[index] = render_counts.get(index, 0) + 1
        return real_render(pdf_doc, index, cfg)

    monkeypatch.setattr(runner_mod, "render_pdf_page", _counting_render)

    # Run 1: start, let ~a third of the pages complete, then hard-cancel (no graceful shutdown).
    mgr1 = _manager(settings, deps)
    job = mgr1.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    handle = mgr1.handle(job.id)
    assert handle is not None and handle.task is not None
    target = max(1, _PAGES // 3)
    for _ in range(2000):
        await asyncio.sleep(0.02)
        if pages_dao.counts(mgr1.conn, job.id).done >= target:
            break
    handle.task.cancel()
    try:
        await handle.task
    except asyncio.CancelledError:
        pass
    done_mid = pages_dao.counts(mgr1.conn, job.id).done
    assert 1 <= done_mid < _PAGES
    mgr1.conn.close()

    # Run 2: reopen + recover + finish.
    mgr2 = _manager(settings, deps)
    mgr2.recover_on_boot()
    handle2 = mgr2.handle(job.id)
    assert handle2 is not None and handle2.task is not None
    await asyncio.wait_for(handle2.task, timeout=120)

    counts = pages_dao.counts(mgr2.conn, job.id)
    assert counts.done == _PAGES  # NO LOST pages
    pages = pages_dao.list_pages(mgr2.conn, job.id)
    assert sorted(p.page_index for p in pages) == list(range(_PAGES))  # NO duplicate rows
    assert all(p.status == "done" for p in pages)
    # A done page is never re-rendered; at most the single in-flight page at crash renders twice.
    assert all(v in (1, 2) for v in render_counts.values())
    assert sum(1 for v in render_counts.values() if v == 2) <= 1
