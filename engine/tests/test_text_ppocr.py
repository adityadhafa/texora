"""PP-OCRv5 ONNX text adapter tests: honesty on failure + model-gated real EN/ID recognition."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from texora_engine.models.errors import ModelNotReady
from texora_engine.recognizers.base import RecognitionStatus, RegionContext

from tests.conftest import prefetched_text_models_dir

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _ctx() -> RegionContext:
    return RegionContext(is_display=False, device="cpu", source="page")


def test_adapter_contract() -> None:
    from texora_engine.recognizers.text_ppocr_onnx import PpOcrV5TextRecognizer

    assert PpOcrV5TextRecognizer.id == "pp_ocrv5_onnx"
    assert PpOcrV5TextRecognizer.model_ids == ("pp_ocrv5_det", "pp_ocrv5_rec")
    assert PpOcrV5TextRecognizer.langs == ("en", "id")


def test_missing_weights_raise_model_not_ready(tmp_path: Path) -> None:
    from texora_engine.recognizers.text_ppocr_onnx import PpOcrV5TextRecognizer

    with pytest.raises(ModelNotReady):
        PpOcrV5TextRecognizer(
            det_onnx=tmp_path / "det.onnx",
            rec_onnx=tmp_path / "rec.onnx",
            dict_path=tmp_path / "rec_keys.txt",
        )


def _build_real() -> object:
    from texora_engine.recognizers.text_ppocr_onnx import PpOcrV5TextRecognizer

    base = prefetched_text_models_dir()
    assert base is not None
    return PpOcrV5TextRecognizer(
        det_onnx=base / "pp_ocrv5_det" / "det.onnx",
        rec_onnx=base / "pp_ocrv5_rec" / "rec.onnx",
        dict_path=base / "pp_ocrv5_rec" / "rec_keys.txt",
        langs=("en", "id"),
        device="cpu",
    )


@pytest.mark.model
def test_inference_error_returns_failed_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    if prefetched_text_models_dir() is None:
        pytest.skip("PP-OCRv5 ONNX weights absent; run model prefetch")
    adapter = _build_real()

    def _boom(image: object) -> list[object]:
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(adapter, "_infer", _boom)
    result = adapter.recognize(Image.new("RGB", (40, 20), "white"), _ctx())  # type: ignore[attr-defined]
    assert result.status == RecognitionStatus.FAILED
    assert result.lines == []


@pytest.mark.model
@pytest.mark.parametrize("fixture", ["text_en.png", "text_id.png"])
def test_real_recognition_sane_text(fixture: str) -> None:
    if prefetched_text_models_dir() is None:
        pytest.skip("PP-OCRv5 ONNX weights absent; run model prefetch")
    adapter = _build_real()
    with Image.open(_FIXTURES / fixture) as img:
        result = adapter.recognize(img.convert("RGB"), _ctx())  # type: ignore[attr-defined]
    assert result.status == RecognitionStatus.OK
    text = " ".join(line.text for line in result.lines).strip()
    assert text != ""
