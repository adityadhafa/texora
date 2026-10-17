"""Shared pytest fixtures for engine tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from texora_engine.app import create_app
from texora_engine.settings import Settings

TEST_TOKEN = "test-token-abc123"

# Where prefetched pix2tex weights live for the real-model test. Overridable via env so CI
# can point at its gated prefetch. Defaults to the local dev prefetch under the venv.
_DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[1] / ".venv" / "pix2tex_models"


def prefetched_models_dir() -> Path | None:
    """Return the models dir containing prefetched weights, or None if unset/absent."""

    env = os.environ.get("TEXORA_TEST_MODELS_DIR")
    base = Path(env) if env else _DEFAULT_MODELS_DIR
    weights = base / "pix2tex" / "weights.pth"
    resizer = base / "pix2tex" / "image_resizer.pth"
    if weights.exists() and resizer.exists():
        return base
    return None


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings with a known token and an isolated log directory."""

    return Settings(host="127.0.0.1", port=8756, token=TEST_TOKEN, log_dir=tmp_path / "logs")


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient wrapping a freshly built app."""

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
