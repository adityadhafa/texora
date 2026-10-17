"""Integration tests for ``POST /recognize/snip`` (AC-6)."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import TEST_TOKEN, prefetched_models_dir

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "formula_frac_ab.png"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def _fixture_b64() -> str:
    return base64.b64encode(_FIXTURE.read_bytes()).decode("ascii")


def test_snip_requires_token(client: TestClient) -> None:
    resp = client.post("/recognize/snip", json={"image_base64": _fixture_b64()})
    assert resp.status_code == 401


def test_snip_malformed_base64_is_422(client: TestClient) -> None:
    resp = client.post(
        "/recognize/snip",
        headers=_auth(),
        json={"image_base64": "!!!not base64!!!"},
    )
    assert resp.status_code == 422


def test_snip_oversized_image_is_422(client: TestClient) -> None:
    # A valid PNG whose decoded dimensions exceed max_snip_edge (5000).
    big = Image.new("RGB", (6000, 10), color="white")
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    resp = client.post("/recognize/snip", headers=_auth(), json={"image_base64": b64})
    assert resp.status_code == 422


def test_snip_real_model_returns_valid_result(client: TestClient) -> None:
    if prefetched_models_dir() is None:
        pytest.skip("pix2tex weights absent; run model prefetch")
    resp = client.post(
        "/recognize/snip",
        headers=_auth(),
        json={"image_base64": _fixture_b64(), "is_display": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Contract shape (AC-6).
    assert set(body) >= {
        "latex",
        "confidence",
        "confidence_kind",
        "status",
        "validation",
        "mathml",
        "asciimath",
    }
    # asciimath is always null in M2 (deferred to M6).
    assert body["asciimath"] is None
    # Confidence branch recorded in docs/m2-verification.md: unavailable on pinned pix2tex.
    assert body["confidence"] == 0.0
    assert body["confidence_kind"] == "unavailable"
    # The real model produced a non-empty LaTeX string that validated.
    assert body["status"] in {"ok", "needs_review"}
    assert body["latex"].strip() != ""
    assert body["mathml"]
