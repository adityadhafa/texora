"""Integration tests for the model status/download routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_models_requires_token(client: TestClient) -> None:
    assert client.get("/models/pix2tex").status_code == 401


def test_get_model_status_shape(client: TestClient) -> None:
    resp = client.get("/models/pix2tex", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "pix2tex"
    assert body["state"] in {"downloading", "verifying", "ready", "corrupt", "error"}
    names = {f["name"] for f in body["files"]}
    assert names == {"weights.pth", "image_resizer.pth"}


def test_unknown_model_is_404(client: TestClient) -> None:
    assert client.get("/models/nope", headers=_auth()).status_code == 404


def test_download_trigger_returns_downloading_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stub the background download so the test never performs a real network transfer; we
    # are asserting the route returns `downloading` immediately (non-blocking), not the
    # download itself (that is covered by test_downloader.py against a local server).
    from texora_engine.models.store import ModelStore

    monkeypatch.setattr(ModelStore, "ensure_ready", lambda self, mid, on_progress=None: None)  # type: ignore[attr-defined]
    resp = client.post("/models/pix2tex/download", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "downloading"
    assert body["bytes_received"] == 0
    assert body["bytes_total"] > 0
