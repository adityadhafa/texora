"""Progress WebSocket auth + emission tests (design §9.2, task 4.4)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from texora_engine.app import create_app
from texora_engine.jobs.manager import JobManager
from texora_engine.settings import Settings
from websockets.exceptions import ConnectionClosed

from tests._job_harness import make_stub_deps, write_minimal_pdf

TOKEN = "ws-tok"
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
        ws_token_timeout_s=0.5,
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
        yield client, settings


def _create_job(client: TestClient, settings: Settings, pages: int) -> str:
    pdf = write_minimal_pdf(Path(settings.log_dir).parent / "ws.pdf", pages)
    return client.post(
        "/jobs", headers=AUTH, json={"path": str(pdf), "options": {"dpi": 72}}
    ).json()["id"]


def test_header_mismatch_closes_4401_pre_accept(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    job_id = _create_job(client, settings, 1)
    with pytest.raises((ConnectionClosed, Exception)):
        with client.websocket_connect(
            f"/jobs/{job_id}/events", headers={"Authorization": "Bearer WRONG"}
        ) as ws:
            ws.receive_text()


def test_fallback_timeout_closes_4401(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    job_id = _create_job(client, settings, 1)
    # No Authorization header, no token frame sent -> the server times out and closes 4401.
    with pytest.raises((ConnectionClosed, Exception)):
        with client.websocket_connect(f"/jobs/{job_id}/events") as ws:
            time.sleep(0.8)  # exceed ws_token_timeout_s=0.5
            ws.receive_text()


def test_header_valid_token_receives_progress_event(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    job_id = _create_job(client, settings, 2)
    with client.websocket_connect(f"/jobs/{job_id}/events", headers=AUTH) as ws:
        # First message is the immediate snapshot; subsequent messages are per-page/terminal.
        first = json.loads(ws.receive_text())
        assert first["job_id"] == job_id
        assert "progress" in first
        # Drain until a terminal event arrives.
        terminal = first
        for _ in range(50):
            if terminal["terminal"]:
                break
            terminal = json.loads(ws.receive_text())
        assert terminal["terminal"] is True
        assert terminal["status"] in ("done", "failed", "canceled")


def test_fallback_valid_message_token_receives_event(api: tuple[TestClient, Settings]) -> None:
    client, settings = api
    job_id = _create_job(client, settings, 1)
    with client.websocket_connect(f"/jobs/{job_id}/events") as ws:
        ws.send_text(json.dumps({"token": TOKEN}))
        snapshot = json.loads(ws.receive_text())
        assert snapshot["job_id"] == job_id
