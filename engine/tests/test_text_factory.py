"""Text factory tests: the single-owning fallback decision table (design §7.2.1).

Each row of the decision table is asserted deterministically by monkeypatching the two inputs the
decision depends on — ``require_ready`` (PP-OCRv5 weights present/absent) and
``_tesseract_available`` (Tesseract usable) — so the branch is covered with no real weights/binary.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from texora_engine.db import init_db
from texora_engine.models.errors import ModelNotReady
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import PipelineConfig, RecognizeStage, Stages
from texora_engine.recognizers import text_factory
from texora_engine.recognizers.base import TextRecognizer
from texora_engine.recognizers.text_factory import (
    TextStageNotConfigured,
    UnknownTextEngineError,
    build_text_recognizer,
    known_text_engine_ids,
)
from texora_engine.recognizers.text_tesseract import (
    TesseractTextRecognizer,
    TesseractUnavailable,
)
from texora_engine.settings import Settings


def _store(tmp_path: Path, models_dir: Path) -> ModelStore:
    conn = init_db(tmp_path / "texora.db")
    settings = Settings(models_dir=models_dir)
    return ModelStore(conn, settings)


def _cfg(text_id: str | None) -> PipelineConfig:
    return PipelineConfig(stages=Stages(recognize=RecognizeStage(text=text_id)))


def test_both_engines_registered() -> None:
    assert "pp_ocrv5_onnx" in known_text_engine_ids()
    assert "tesseract" in known_text_engine_ids()
    entry = text_factory._REGISTRY["pp_ocrv5_onnx"]
    assert entry.id == "pp_ocrv5_onnx"
    assert entry.model_ids == ("pp_ocrv5_det", "pp_ocrv5_rec")


def test_unknown_id_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("nope"))
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(UnknownTextEngineError) as exc:
        build_text_recognizer(settings, store)
    assert exc.value.stage_id == "nope"
    assert "pp_ocrv5_onnx" in exc.value.known


def test_absent_text_key_raises_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg(None))
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(TextStageNotConfigured):
        build_text_recognizer(settings, store)


# --- Decision table (design §7.2.1) -----------------------------------------------------------


def test_pp_present_builds_ppocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row 1: PP-OCRv5 weights present -> PP-OCRv5 adapter (no fallback)."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("pp_ocrv5_onnx"))

    class _FakeSpec:
        def file_path(self, name: str) -> Path:
            return tmp_path / name

    class _Store:
        def require_ready(self, model_id: str) -> object:
            return _FakeSpec()

    # Stub the PP-OCR ctor so the test needs no real ONNX weights.
    built: dict[str, object] = {}

    def _fake_ctor(**kwargs: object) -> TextRecognizer:
        built.update(kwargs)
        return TesseractTextRecognizer()  # structurally a TextRecognizer; id checked separately

    entry = text_factory._REGISTRY["pp_ocrv5_onnx"]
    monkeypatch.setattr(
        text_factory,
        "_REGISTRY",
        {
            **text_factory._REGISTRY,
            "pp_ocrv5_onnx": text_factory._Entry(
                id="pp_ocrv5_onnx", model_ids=entry.model_ids, ctor=_fake_ctor
            ),
        },
    )

    settings = Settings(models_dir=tmp_path / "models")
    build_text_recognizer(settings, _Store())  # type: ignore[arg-type]
    # Every declared model id was resolved + named paths passed.
    assert "det_onnx" in built and "rec_onnx" in built and "dict_path" in built
    assert built["langs"] == ("en", "id")


def test_pp_absent_fallback_usable_builds_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 2: PP absent + fallback on + Tesseract usable -> Tesseract adapter."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("pp_ocrv5_onnx"))
    monkeypatch.setattr(text_factory, "_tesseract_available", lambda s: True)

    class _Store:
        def require_ready(self, model_id: str) -> object:
            raise ModelNotReady(model_id)

    settings = Settings(models_dir=tmp_path / "models", text_fallback_to_tesseract=True)
    adapter = build_text_recognizer(settings, _Store())  # type: ignore[arg-type]
    assert adapter.id == "tesseract"


def test_pp_absent_fallback_unusable_raises_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 3: PP absent + fallback on + Tesseract NOT usable -> re-raise ModelNotReady (409)."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("pp_ocrv5_onnx"))
    monkeypatch.setattr(text_factory, "_tesseract_available", lambda s: False)

    class _Store:
        def require_ready(self, model_id: str) -> object:
            raise ModelNotReady(model_id)

    settings = Settings(models_dir=tmp_path / "models", text_fallback_to_tesseract=True)
    with pytest.raises(ModelNotReady):
        build_text_recognizer(settings, _Store())  # type: ignore[arg-type]


def test_pp_absent_no_fallback_raises_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row 4: PP absent + fallback off -> re-raise ModelNotReady (409)."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("pp_ocrv5_onnx"))

    class _Store:
        def require_ready(self, model_id: str) -> object:
            raise ModelNotReady(model_id)

    settings = Settings(models_dir=tmp_path / "models", text_fallback_to_tesseract=False)
    with pytest.raises(ModelNotReady):
        build_text_recognizer(settings, _Store())  # type: ignore[arg-type]


def test_explicit_tesseract_missing_binary_raises_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit text: tesseract with no usable binary -> TesseractUnavailable (API 409)."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("tesseract"))
    monkeypatch.setattr(text_factory, "_tesseract_available", lambda s: False)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(TesseractUnavailable):
        build_text_recognizer(settings, store)


def test_explicit_tesseract_usable_builds_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit text: tesseract with a usable binary -> Tesseract adapter (id matches config)."""

    monkeypatch.setattr(text_factory, "load_pipeline_config", lambda: _cfg("tesseract"))
    monkeypatch.setattr(text_factory, "_tesseract_available", lambda s: True)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    adapter = build_text_recognizer(settings, store)
    assert adapter.id == "tesseract"
