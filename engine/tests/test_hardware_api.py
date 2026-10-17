"""Integration tests for the hardware routes (AC-7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_hardware_requires_token(client: TestClient) -> None:
    assert client.get("/hardware").status_code == 401


def test_get_hardware_reports_cpu(client: TestClient) -> None:
    resp = client.get("/hardware", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert "cpu" in body["devices"]
    assert body["selected"] in body["devices"]


def test_device_override_takes_effect(client: TestClient) -> None:
    # CPU is always available; overriding to it must succeed and be reported next call.
    resp = client.post("/hardware/device", headers=_auth(), json={"device": "cpu"})
    assert resp.status_code == 200
    assert resp.json()["selected"] == "cpu"

    again = client.get("/hardware", headers=_auth())
    assert again.json()["selected"] == "cpu"


def test_unknown_device_is_422(client: TestClient) -> None:
    resp = client.post("/hardware/device", headers=_auth(), json={"device": "tpu"})
    assert resp.status_code == 422


def test_cuda_override_when_monkeypatched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import texora_engine.api.hardware as hw

    monkeypatch.setattr(hw, "_detect_devices", lambda: ["cpu", "cuda"])
    resp = client.post("/hardware/device", headers=_auth(), json={"device": "cuda"})
    assert resp.status_code == 200
    assert resp.json()["selected"] == "cuda"
    assert "cuda" in client.get("/hardware", headers=_auth()).json()["devices"]
