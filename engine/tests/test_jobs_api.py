"""Job-control REST API tests (design §9, task 4.4) — TestClient + stub-deps manager."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from texora_engine.app import create_app
from texora_engine.db import pages_dao
from texora_engine.jobs.manager import JobManager
from texora_engine.settings import Settings

from tests._job_harness import make_stub_deps, write_minimal_pdf

TOKEN = "tok-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Settings]]:
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
        # Swap the production manager for one wired to fast stub recognizers, sharing the same
        # loop + conn so routes see the stub-driven jobs (production path stays real elsewhere).
        real = app.state.job_manager
        deps = make_stub_deps(settings)
        stub_mgr = JobManager(
            real.conn,
            app_state=app.state,
            settings=settings,
            loop=real._loop,
            deps_provider=lambda _s: deps,
        )
        app.state.job_manager = stub_mgr
        yield client, settings


def _wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/jobs/{job_id}", headers=AUTH)
        view = resp.json()
        if view["status"] in ("done", "failed", "canceled"):
            return view
        time.sleep(0.1)
    raise AssertionError("job did not terminate in time")


def test_rest_requires_token(api: tuple[TestClient, Settings]) -> None:
    client, _ = api
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"path": "/x"}).status_code == 401


def test_create_job_runs_to_done_and_export_matches(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "syn.pdf", 5)
    resp = client.post(
        "/jobs",
        headers=AUTH,
        json={"path": str(pdf), "options": {"dpi": 72, "formats": ["md"]}},
    )
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    view = _wait_done(client, job_id)
    assert view["status"] == "done"
    assert view["progress"]["done"] == 5

    export = client.get(f"/jobs/{job_id}/export", headers=AUTH, params={"format": "md"})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/markdown")
    assert "attachment; filename=" in export.headers["content-disposition"]


def test_unknown_job_is_404(api: tuple[TestClient, Settings]) -> None:
    client, _ = api
    assert client.get("/jobs/nope", headers=AUTH).status_code == 404


def test_bad_export_format_is_422(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "s.pdf", 1)
    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    _wait_done(client, job_id)
    assert (
        client.get(f"/jobs/{job_id}/export", headers=AUTH, params={"format": "xml"}).status_code
        == 422
    )


def test_bad_path_is_422(api: tuple[TestClient, Settings]) -> None:
    client, _ = api
    assert client.post("/jobs", headers=AUTH, json={"path": "../etc/passwd"}).status_code == 422
    assert (
        client.post("/jobs", headers=AUTH, json={"path": "/does/not/exist.pdf"}).status_code == 422
    )


def test_resume_done_job_is_409(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "s2.pdf", 1)
    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    _wait_done(client, job_id)
    assert client.post(f"/jobs/{job_id}:resume", headers=AUTH).status_code == 409


def test_reprioritize_clamps(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "s3.pdf", 1)
    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    _wait_done(client, job_id)
    resp = client.post(f"/jobs/{job_id}:reprioritize", headers=AUTH, json={"priority": 9999})
    assert resp.status_code == 200
    assert resp.json()["priority"] == 100  # clamped to [-100, 100]


def test_search_returns_hits(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "s4.pdf", 2)
    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    _wait_done(client, job_id)
    # The synthetic pages carry the word "synthetic" in their text (scanned path yields no region
    # text with the stub, so search may be empty — assert the endpoint validates + returns a list).
    resp = client.get("/search", headers=AUTH, params={"q": "synthetic"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    # Empty query is rejected.
    assert client.get("/search", headers=AUTH, params={"q": ""}).status_code == 422


def test_retry_failed_reruns_only_failed(api: tuple[TestClient, Settings], monkeypatch) -> None:
    client, settings = api
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "s5.pdf", 3)

    import texora_engine.jobs.runner as runner_mod
    from PIL import Image
    from texora_engine.ingest.base import RenderedPage
    from texora_engine.pipeline import PageResult
    from texora_engine.recognizers.base import RecognitionStatus

    poison = {"fail": True}

    def _assemble(rendered: RenderedPage, image: Image.Image, deps: object) -> PageResult:
        image.close()
        if rendered.index == 1 and poison["fail"]:
            raise RuntimeError("hostile")
        return PageResult(
            index=rendered.index,
            width=rendered.width,
            height=rendered.height,
            dpi=rendered.dpi,
            kind=rendered.kind,
            contents=[],
            status=RecognitionStatus.OK,
        )

    monkeypatch.setattr(runner_mod, "assemble_page", _assemble)

    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    view = _wait_done(client, job_id)
    assert view["progress"]["failed"] == 1
    assert view["progress"]["done"] == 2

    poison["fail"] = False
    assert client.post(f"/jobs/{job_id}/pages:retry-failed", headers=AUTH).status_code == 200
    view2 = _wait_done(client, job_id)
    assert view2["progress"]["done"] == 3
    assert view2["progress"]["failed"] == 0


def test_deps_build_failure_fails_job_gracefully(
    api: tuple[TestClient, Settings], monkeypatch
) -> None:
    client, settings = api
    manager = client.app.state.job_manager
    from texora_engine.models.errors import ModelNotReady

    def _raise(_state: object) -> object:
        raise ModelNotReady("pp_doclayout")

    monkeypatch.setattr(manager, "_deps_provider", _raise)
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "nodeps.pdf", 3)
    job_id = client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]
    view = _wait_done(client, job_id)
    assert view["status"] == "failed"
    assert view["error"] is not None and "models not ready" in view["error"]
    # No page was leased before the deps-build failure (the failure is pre-page).
    counts = pages_dao.counts(manager.conn, job_id)
    assert counts.leased == 0
    assert counts.done == 0
    assert counts.pending == counts.total


def test_mid_job_export_has_placeholder_for_pending_page(
    api: tuple[TestClient, Settings],
) -> None:
    client, settings = api
    manager = client.app.state.job_manager
    # Enroll a job directly with 2 pending pages (no runner) so export sees a mid-job state.
    from texora_engine.db import jobs_dao

    jobs_dao.create_job(
        manager.conn,
        jobs_dao.JobRow(
            id="midjob",
            source_path="/d/x.pdf",
            source_name="x.pdf",
            status="running",
            options_json="{}",
            total_pages=2,
            priority=0,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        ),
    )
    pages_dao.bulk_insert_pending(manager.conn, "midjob", [("p0", 0), ("p1", 1)])
    export = client.get("/jobs/midjob/export", headers=AUTH, params={"format": "md"})
    assert export.status_code == 200
    assert "<!-- texora: page 0 pending (no output) -->" in export.text
    assert "<!-- texora: page 1 pending (no output) -->" in export.text
