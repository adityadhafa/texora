"""Formula recognizer factory tests (Protocol wiring + typed misconfig errors)."""

from __future__ import annotations

from pathlib import Path

import pytest
from texora_engine.db import init_db
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import PipelineConfig, RecognizeStage, Stages
from texora_engine.recognizers import factory
from texora_engine.recognizers.base import FormulaRecognizer
from texora_engine.recognizers.factory import (
    FormulaStageNotConfigured,
    UnknownEngineError,
    build_formula_recognizer,
)
from texora_engine.settings import Settings

from tests.conftest import prefetched_models_dir


def _store(tmp_path: Path, models_dir: Path) -> ModelStore:
    conn = init_db(tmp_path / "texora.db")
    settings = Settings(models_dir=models_dir)
    return ModelStore(conn, settings)


def test_pix2tex_ctor_is_registered_and_structural() -> None:
    assert "pix2tex" in factory.known_engine_ids()
    entry = factory._REGISTRY["pix2tex"]
    assert entry.id == "pix2tex"
    assert entry.model_ids == ("pix2tex",)


def test_build_returns_protocol_instance(tmp_path: Path) -> None:
    models_dir = prefetched_models_dir()
    if models_dir is None:
        pytest.skip("pix2tex weights absent; run model prefetch")
    store = _store(tmp_path, models_dir)
    settings = Settings(models_dir=models_dir, device="cpu")
    adapter = build_formula_recognizer(settings, store)
    assert isinstance(adapter, FormulaRecognizer)
    assert adapter.id == "pix2tex"


def test_unknown_id_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_cfg = PipelineConfig(stages=Stages(recognize=RecognizeStage(formula="nope")))
    monkeypatch.setattr(factory, "load_pipeline_config", lambda: bad_cfg)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(UnknownEngineError) as exc:
        build_formula_recognizer(settings, store)
    assert exc.value.stage_id == "nope"
    assert "pix2tex" in exc.value.known


def test_absent_formula_key_raises_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_cfg = PipelineConfig(stages=Stages(recognize=RecognizeStage(formula=None)))
    monkeypatch.setattr(factory, "load_pipeline_config", lambda: empty_cfg)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(FormulaStageNotConfigured):
        build_formula_recognizer(settings, store)
