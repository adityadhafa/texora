"""Tesseract text adapter tests: honesty on failure + binary-gated real EN/ID recognition."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from texora_engine.recognizers.base import RecognitionStatus, RegionContext
from texora_engine.recognizers.text_tesseract import TesseractTextRecognizer

from tests.conftest import tesseract_available

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _ctx() -> RegionContext:
    return RegionContext(is_display=False, device="cpu", source="page")


def test_adapter_contract() -> None:
    adapter = TesseractTextRecognizer()
    assert adapter.id == "tesseract"
    assert adapter.model_ids == ()
    assert adapter.langs == ("en", "id")


def test_inference_error_returns_failed_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = TesseractTextRecognizer()

    def _boom(image: object) -> list[object]:
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(adapter, "_infer", _boom)
    result = adapter.recognize(Image.new("RGB", (40, 20), "white"), _ctx())
    assert result.status == RecognitionStatus.FAILED
    assert result.lines == []
    assert result.engine_id == "tesseract"
    assert result.detail


@pytest.mark.model
@pytest.mark.parametrize("fixture", ["text_en.png", "text_id.png"])
def test_real_recognition_sane_text(fixture: str) -> None:
    if not tesseract_available():
        pytest.skip("tesseract binary not installed on this host; fallback test is host-limited")
    adapter = TesseractTextRecognizer()
    with Image.open(_FIXTURES / fixture) as img:
        result = adapter.recognize(img.convert("RGB"), _ctx())
    assert result.status == RecognitionStatus.OK
    text = " ".join(line.text for line in result.lines).strip()
    assert text != ""
