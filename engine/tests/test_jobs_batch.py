"""Batch intake tests (design §8, task 4.6) — POST /jobs/batch over files + folders."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from texora_engine.app import create_app
from texora_engine.jobs.manager import JobManager
from texora_engine.settings import Settings

from tests._job_harness import make_stub_deps, write_minimal_pdf

TOKEN = "batch-tok"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    settings = Settings(
        token=TOKEN,
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=tmp_path / "models",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        real = app.state.job_manager
        deps = make_stub_deps(settings)
        app.state.job_manager = JobManager(
            real.conn,
            app_state=app.state,
            settings=settings,
            loop=real._loop,
            deps_provider=lambda _s: deps,
        )
        yield client, tmp_path


def test_batch_folder_of_two_pdfs_enqueues_two_jobs(api: tuple[TestClient, Path]) -> None:
    client, tmp_path = api
    folder = tmp_path / "docs"
    folder.mkdir()
    write_minimal_pdf(folder / "a.pdf", 1)
    write_minimal_pdf(folder / "b.pdf", 1)
    resp = client.post(
        "/jobs/batch",
        headers=AUTH,
        json={"paths": [str(folder)], "options": {"dpi": 72}},
    )
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) == 2
    assert {j["source_name"] for j in jobs} == {"a.pdf", "b.pdf"}


def test_batch_mixes_files_and_dirs(api: tuple[TestClient, Path]) -> None:
    client, tmp_path = api
    folder = tmp_path / "d2"
    folder.mkdir()
    write_minimal_pdf(folder / "c.pdf", 1)
    single = write_minimal_pdf(tmp_path / "solo.pdf", 1)
    resp = client.post(
        "/jobs/batch",
        headers=AUTH,
        json={"paths": [str(folder), str(single)], "options": {"dpi": 72}},
    )
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 2


def test_batch_bad_path_is_422(api: tuple[TestClient, Path]) -> None:
    client, _ = api
    assert client.post("/jobs/batch", headers=AUTH, json={"paths": ["../x"]}).status_code == 422


def test_batch_non_recursive_by_default(api: tuple[TestClient, Path]) -> None:
    client, tmp_path = api
    folder = tmp_path / "d3"
    sub = folder / "nested"
    sub.mkdir(parents=True)
    write_minimal_pdf(folder / "top.pdf", 1)
    write_minimal_pdf(sub / "deep.pdf", 1)
    resp = client.post(
        "/jobs/batch", headers=AUTH, json={"paths": [str(folder)], "options": {"dpi": 72}}
    )
    assert len(resp.json()["jobs"]) == 1  # only top.pdf (non-recursive default)

    resp2 = client.post(
        "/jobs/batch",
        headers=AUTH,
        json={"paths": [str(folder)], "options": {"dpi": 72}, "recursive": True},
    )
    assert len(resp2.json()["jobs"]) == 2  # top.pdf + nested/deep.pdf
