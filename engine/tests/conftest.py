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

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    """Absolute path to the committed test fixtures directory."""

    return FIXTURES_DIR


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


def prefetched_layout_models_dir() -> Path | None:
    """Return the models dir with the prefetched PP-DocLayout ONNX weights, or None if absent.

    Mirrors :func:`prefetched_models_dir` for the M3 layout model-gated test: the
    ``@pytest.mark.model`` PP-DocLayout test runs only when ``doclayout.onnx`` + ``label_map.txt``
    are prefetched (never mocked), otherwise it skips with reason. Overridable via
    ``TEXORA_TEST_MODELS_DIR``.
    """

    env = os.environ.get("TEXORA_TEST_MODELS_DIR")
    base = Path(env) if env else _DEFAULT_MODELS_DIR
    onnx = base / "pp_doclayout" / "doclayout.onnx"
    labels = base / "pp_doclayout" / "label_map.txt"
    if onnx.exists() and labels.exists():
        return base
    return None


def prefetched_text_models_dir() -> Path | None:
    """Return the models dir with the prefetched PP-OCRv5 det+rec ONNX weights, or None if absent.

    Mirrors :func:`prefetched_models_dir` for the M3 text model-gated test (``@pytest.mark.model``):
    PP-OCRv5 runs only when ``pp_ocrv5_det/det.onnx`` + ``pp_ocrv5_rec/rec.onnx`` +
    ``pp_ocrv5_rec/rec_keys.txt`` are prefetched (never mocked), otherwise it skips with reason.
    Overridable via ``TEXORA_TEST_MODELS_DIR``.
    """

    env = os.environ.get("TEXORA_TEST_MODELS_DIR")
    base = Path(env) if env else _DEFAULT_MODELS_DIR
    det = base / "pp_ocrv5_det" / "det.onnx"
    rec = base / "pp_ocrv5_rec" / "rec.onnx"
    keys = base / "pp_ocrv5_rec" / "rec_keys.txt"
    if det.exists() and rec.exists() and keys.exists():
        return base
    return None


def tesseract_available() -> bool:
    """Whether the Tesseract binary is usable on this host (gates the fallback real test)."""

    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings with a known token and isolated log/db/models directories.

    When prefetched pix2tex weights exist they are used so the snip integration test can run
    the real model; otherwise ``models_dir`` points at an empty tmp dir and the snip test
    skips (never mocks).
    """

    models_dir = prefetched_models_dir() or (tmp_path / "models")
    return Settings(
        host="127.0.0.1",
        port=8756,
        token=TEST_TOKEN,
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "texora.db",
        models_dir=models_dir,
    )


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient wrapping a freshly built app."""

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
