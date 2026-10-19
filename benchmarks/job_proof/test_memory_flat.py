"""Memory-flatness proof (design §12, R-JOB-1) — RSS stays bounded across a scaled synthetic PDF.

Run with the fast stub recognizers so the measurement reflects the RUNNER/STREAMING memory, not
model-load noise (the production path stays real elsewhere — honesty intact). A second
``@pytest.mark.model`` variant (host-gated) would use the real engines; it is skip-with-reason here
because the proof host has no prefetched weights. The full 5,000-page run is the CI nightly gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from scripts.make_synthetic_pdf import build_synthetic_pdf
from tests._job_harness import make_stub_deps
from texora_engine.db import init_db, pages_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.settings import Settings

# Scaled page count for the LOCAL proof (enough to see the RSS slope). The 5,000-page full count is
# the nightly CI gate (TEXORA_PROOF_PAGES overrides it there).
import os

_PAGES = int(os.environ.get("TEXORA_PROOF_PAGES", "200"))
_SAMPLE_EVERY = 20
# Per-page RSS growth bound (MiB/page). Streaming keeps memory ~flat; a true leak would grow
# linearly with pages. Generous to absorb allocator/CI noise while still catching a real leak.
_MAX_SLOPE_MIB_PER_PAGE = 0.5
_MAX_PEAK_MIB = 1500.0


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
        job_max_concurrent_pages=2,
    )


@pytest.mark.asyncio
async def test_memory_stays_flat_over_scaled_pdf(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    pdf = build_synthetic_pdf(tmp_path / "proof.pdf", _PAGES, seed=7)

    conn = init_db(settings.db_path)
    deps = make_stub_deps(settings)
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=None)
    manager = JobManager(
        conn,
        app_state=app_state,
        settings=settings,
        loop=asyncio.get_event_loop(),
        deps_provider=lambda _s: deps,
    )

    proc = psutil.Process()
    samples: list[tuple[int, float]] = []

    job = manager.create_job(str(pdf), pdf.name, JobOptions(dpi=72))
    handle = manager.handle(job.id)
    assert handle is not None and handle.task is not None

    last_done = -1
    while not handle.task.done():
        await asyncio.sleep(0.1)
        done = pages_dao.counts(conn, job.id).done
        if done != last_done and done % _SAMPLE_EVERY == 0 and done > 0:
            rss_mib = proc.memory_info().rss / (1024 * 1024)
            samples.append((done, rss_mib))
            last_done = done
    await handle.task

    counts = pages_dao.counts(conn, job.id)
    assert counts.done == _PAGES  # every page processed (streaming to completion)

    assert len(samples) >= 3, f"too few RSS samples ({len(samples)}) to fit a slope"
    peak = max(rss for _, rss in samples)
    assert peak < _MAX_PEAK_MIB, f"peak RSS {peak:.1f} MiB exceeded {_MAX_PEAK_MIB} MiB"

    # Least-squares slope of RSS (MiB) vs pages processed. Flat memory => slope ~ 0; a leak grows
    # linearly. Method + numbers are recorded in docs/m4-verification.md.
    slope = _linear_slope([float(p) for p, _ in samples], [r for _, r in samples])
    assert slope < _MAX_SLOPE_MIB_PER_PAGE, (
        f"RSS slope {slope:.4f} MiB/page exceeds {_MAX_SLOPE_MIB_PER_PAGE} " f"(samples: {samples})"
    )


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den else 0.0
