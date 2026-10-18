"""Integration tests for ``POST /pages/recognize`` (design §7.6).

The error-mapping + auth + structure tests run WITHOUT any weights; the 200 + DocumentResult path
is model-gated (skips with reason when weights are absent, never mocked).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TEST_TOKEN,
    prefetched_models_dir,
    prefetched_text_models_dir,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "born_digital_math.pdf"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_requires_token(client: TestClient) -> None:
    resp = client.post("/pages/recognize", json={"path": str(_FIXTURE)})
    assert resp.status_code == 401


def test_nonexistent_path_is_422(client: TestClient) -> None:
    resp = client.post("/pages/recognize", headers=_auth(), json={"path": str(_FIXTURE) + ".nope"})
    assert resp.status_code == 422


def test_path_traversal_is_422(client: TestClient) -> None:
    resp = client.post("/pages/recognize", headers=_auth(), json={"path": "../../etc/passwd"})
    assert resp.status_code == 422


def test_unsupported_extension_is_422(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    resp = client.post("/pages/recognize", headers=_auth(), json={"path": str(bad)})
    assert resp.status_code == 422


def test_bad_page_range_is_422(client: TestClient) -> None:
    resp = client.post(
        "/pages/recognize",
        headers=_auth(),
        json={"path": str(_FIXTURE), "page_start": 5, "page_end": 1},
    )
    assert resp.status_code == 422


def test_model_absent_is_409(client: TestClient) -> None:
    # The default `settings` fixture points models_dir at an empty tmp dir when weights are not
    # prefetched: building the layout/formula/text deps raises ModelNotReady -> 409.
    if prefetched_models_dir() is not None and prefetched_text_models_dir() is not None:
        pytest.skip("all weights prefetched; the model-absent 409 branch cannot be exercised here")
    resp = client.post("/pages/recognize", headers=_auth(), json={"path": str(_FIXTURE)})
    assert resp.status_code == 409


@pytest.mark.model
def test_real_document_returns_200(client: TestClient) -> None:
    if prefetched_models_dir() is None or prefetched_text_models_dir() is None:
        pytest.skip("pix2tex/PP-OCRv5 weights absent; the 200 path is model-gated")
    resp = client.post("/pages/recognize", headers=_auth(), json={"path": str(_FIXTURE)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_name"] == _FIXTURE.name
    assert isinstance(body["pages"], list) and body["pages"]
    first = body["pages"][0]
    assert set(first) >= {"index", "width", "height", "dpi", "kind", "contents", "status"}
