"""Layout factory tests: Protocol wiring, permissive-only registry, typed misconfig errors."""

from __future__ import annotations

from pathlib import Path

import pytest
from texora_engine.db import init_db
from texora_engine.layout import factory
from texora_engine.layout.base import LayoutDetector
from texora_engine.layout.factory import (
    LayoutStageNotConfigured,
    UnknownLayoutEngineError,
    build_layout_detector,
    known_layout_engine_ids,
)
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import PipelineConfig, Stages
from texora_engine.settings import Settings

from tests.conftest import prefetched_layout_models_dir


def _store(tmp_path: Path, models_dir: Path) -> ModelStore:
    conn = init_db(tmp_path / "texora.db")
    settings = Settings(models_dir=models_dir)
    return ModelStore(conn, settings)


def test_pp_doclayout_registered_and_structural() -> None:
    assert "pp_doclayout_onnx" in known_layout_engine_ids()
    entry = factory._REGISTRY["pp_doclayout_onnx"]
    assert entry.id == "pp_doclayout_onnx"
    assert entry.model_ids == ("pp_doclayout",)


def test_doclayout_yolo_is_not_registered() -> None:
    # AGPL opt-in engine is intentionally ABSENT from the permissive default registry.
    assert "doclayout_yolo" not in known_layout_engine_ids()


def test_build_returns_protocol_instance_and_id_matches_config(tmp_path: Path) -> None:
    models_dir = prefetched_layout_models_dir()
    if models_dir is None:
        pytest.skip("pp_doclayout ONNX weights absent; run model prefetch")
    store = _store(tmp_path, models_dir)
    settings = Settings(models_dir=models_dir, device="cpu")
    adapter = build_layout_detector(settings, store)
    assert isinstance(adapter, LayoutDetector)
    # built.id equals the configured pipeline.yaml id (stages.layout == pp_doclayout_onnx)
    assert adapter.id == "pp_doclayout_onnx"


def test_unknown_id_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_cfg = PipelineConfig(stages=Stages(layout="nope"))
    monkeypatch.setattr(factory, "load_pipeline_config", lambda: bad_cfg)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(UnknownLayoutEngineError) as exc:
        build_layout_detector(settings, store)
    assert exc.value.stage_id == "nope"
    assert "pp_doclayout_onnx" in exc.value.known
    # The AGPL engine is never offered as a known alternative.
    assert "doclayout_yolo" not in exc.value.known


def test_doclayout_yolo_id_as_config_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even if a user names the AGPL engine in pipeline.yaml, it is not a registered default.
    bad_cfg = PipelineConfig(stages=Stages(layout="doclayout_yolo"))
    monkeypatch.setattr(factory, "load_pipeline_config", lambda: bad_cfg)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(UnknownLayoutEngineError):
        build_layout_detector(settings, store)


def test_absent_layout_key_raises_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_cfg = PipelineConfig(stages=Stages(layout=None))
    monkeypatch.setattr(factory, "load_pipeline_config", lambda: empty_cfg)
    store = _store(tmp_path, tmp_path / "models")
    settings = Settings(models_dir=tmp_path / "models")
    with pytest.raises(LayoutStageNotConfigured):
        build_layout_detector(settings, store)
