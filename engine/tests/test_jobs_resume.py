"""Checkpoint/resume tests (design §6, DoD-2).

Covers the immediate boot-revert, kill-mid-job → resume with no lost/dup pages, and owned-only
PDF rendering on resume (MEDIUM-F1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from texora_engine.db import init_db, jobs_dao, pages_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.settings import Settings

from tests._job_harness import make_stub_deps, write_minimal_pdf

pytestmark = pytest.mark.asyncio

_FUTURE = "2099-01-01T00:00:00Z"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )


def _manager(settings: Settings) -> JobManager:
    conn = init_db(settings.db_path)
    deps = make_stub_deps(settings)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    return JobManager(
        conn,
        app_state,
        settings,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _s: deps,
    )


async def test_boot_revert_is_immediate_not_ttl_delayed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = init_db(settings.db_path)
    # Seed a crashed job: a running job with a page LEASED under a FUTURE lease_expires_at.
    jobs_dao.create_job(
        conn,
        jobs_dao.JobRow(
            id="crashed",
            source_path="/d/x.pdf",
            source_name="x.pdf",
            status="running",
            options_json=JobOptions().model_dump_json(),
            total_pages=2,
            priority=0,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        ),
    )
    pages_dao.bulk_insert_pending(conn, "crashed", [("p0", 0), ("p1", 1)])
    leased = pages_dao.lease_next(conn, "crashed", "tok", _FUTURE)
    assert leased is not None
    conn.close()

    # Reopen the SAME DB and apply the boot revert: a TTL-future lease is pending AT ONCE (not
    # waiting for its lease to expire). This is the immediate-resume determinism the design pins.
    conn2 = init_db(settings.db_path)
    try:
        reverted = pages_dao.revert_all_leased_for_active_jobs(conn2)
        assert reverted == 1
        page = pages_dao.get_page(conn2, leased.id)
        assert page is not None and page.status == "pending"
    finally:
        conn2.close()


async def test_kill_mid_job_then_resume_no_lost_no_dup(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 5)

    # Count how many times each PDF index is rendered across the whole run (fresh + resume).
    import texora_engine.jobs.runner as runner_mod

    render_counts: dict[int, int] = {}
    real_render = runner_mod.render_pdf_page

    def _counting_render(pdf_doc, index, cfg):  # type: ignore[no-untyped-def]
        render_counts[index] = render_counts.get(index, 0) + 1
        return real_render(pdf_doc, index, cfg)

    monkeypatch.setattr(runner_mod, "render_pdf_page", _counting_render)

    # --- Run 1: start the job, let a couple of pages complete, then simulate a crash. ---
    mgr1 = _manager(settings)
    job = mgr1.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    # Let the loop make progress but not finish (wait for at least one page, cap total pages < 5).
    for _ in range(600):
        await asyncio.sleep(0.05)
        done = pages_dao.counts(mgr1.conn, job.id).done
        if done >= 2 or (done >= 1 and pages_dao.counts(mgr1.conn, job.id).leased >= 1):
            break
    # Simulate a hard crash: cancel the task WITHOUT graceful shutdown; some pages may stay leased.
    handle = mgr1.handle(job.id)
    assert handle is not None and handle.task is not None
    handle.task.cancel()
    try:
        await handle.task
    except asyncio.CancelledError:
        pass
    done_before = pages_dao.counts(mgr1.conn, job.id).done
    assert 1 <= done_before < 5
    mgr1.conn.close()

    # --- Run 2: reopen, recover_on_boot (immediate revert + re-enqueue), finish. ---
    mgr2 = _manager(settings)
    mgr2.recover_on_boot()
    handle2 = mgr2.handle(job.id)
    assert handle2 is not None and handle2.task is not None
    await asyncio.wait_for(handle2.task, timeout=60)

    counts = pages_dao.counts(mgr2.conn, job.id)
    assert counts.total == 5
    assert counts.done == 5  # NO LOST pages: every index reached done
    assert counts.pending == 0
    # NO DUPLICATE done pages: each page_index appears exactly once in the page table and is done.
    pages = pages_dao.list_pages(mgr2.conn, job.id)
    assert sorted(p.page_index for p in pages) == [0, 1, 2, 3, 4]
    assert all(p.status == "done" for p in pages)
    # The already-DONE prefix is never re-rendered on resume (MEDIUM-F1). At most ONE index is
    # rendered twice — the page that was in flight when the crash interrupted it (it was never
    # marked done, so re-rendering it on resume is correct, not a duplicate completion).
    assert all(v in (1, 2) for v in render_counts.values())
    assert sum(1 for v in render_counts.values() if v == 2) <= 1
    assert sorted(render_counts.keys()) == [0, 1, 2, 3, 4]


async def test_resume_renders_only_owned_indices(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    pdf = write_minimal_pdf(tmp_path / "syn.pdf", 4)

    # Pre-mark indices 0 and 1 as done directly in the DB, enroll all 4, then run: only 2 and 3
    # should ever be rendered.
    conn = init_db(settings.db_path)
    jobs_dao.create_job(
        conn,
        jobs_dao.JobRow(
            id="j",
            source_path=str(pdf),
            source_name=pdf.name,
            status="running",
            options_json=JobOptions(dpi=72).model_dump_json(),
            total_pages=4,
            priority=0,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        ),
    )
    pages_dao.bulk_insert_pending(conn, "j", [(f"p{i}", i) for i in range(4)])
    for i in (0, 1):
        leased = pages_dao.lease_next(conn, "j", f"t{i}", _FUTURE)
        assert leased is not None
        pages_dao.mark_done(
            conn,
            leased.id,
            f"t{i}",
            rollup_status="ok",
            result_json="{}",
            avg_confidence=0.9,
            finished_at="2025-01-01T00:00:00Z",
        )
    conn.close()

    import texora_engine.jobs.runner as runner_mod

    rendered_indices: list[int] = []
    real_render = runner_mod.render_pdf_page

    def _counting_render(pdf_doc, index, cfg):  # type: ignore[no-untyped-def]
        rendered_indices.append(index)
        return real_render(pdf_doc, index, cfg)

    monkeypatch.setattr(runner_mod, "render_pdf_page", _counting_render)

    mgr = _manager(settings)
    mgr.recover_on_boot()
    handle = mgr.handle("j")
    assert handle is not None and handle.task is not None
    await asyncio.wait_for(handle.task, timeout=60)

    assert pages_dao.counts(mgr.conn, "j").done == 4
    # The already-done prefix (0,1) is never rendered on resume — only owned indices 2,3.
    assert sorted(rendered_indices) == [2, 3]
