"""Health-check and bearer-token authentication tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN


def test_healthz_is_open(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_route_without_token_is_401(client: TestClient) -> None:
    response = client.get("/engine/info")
    assert response.status_code == 401


def test_protected_route_with_wrong_token_is_401(client: TestClient) -> None:
    response = client.get("/engine/info", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_protected_route_with_correct_token_is_200(client: TestClient) -> None:
    response = client.get("/engine/info", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "texora-engine"
    assert body["version"]
