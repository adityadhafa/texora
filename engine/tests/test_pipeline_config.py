"""pipeline.yaml typed-config tests."""

from __future__ import annotations

from texora_engine.pipeline_config import (
    IngestConfig,
    PipelineConfig,
    PreprocessSettings,
    load_pipeline_config,
)


def test_pipeline_yaml_configures_formula_pix2tex() -> None:
    cfg = load_pipeline_config()
    assert cfg.version == 1
    assert cfg.stages.recognize.formula == "pix2tex"


def test_pipeline_yaml_configures_m3_stage_ids() -> None:
    cfg = load_pipeline_config()
    assert cfg.stages.ingest == "pypdfium2"
    assert cfg.stages.layout == "pp_doclayout_onnx"
    assert cfg.stages.recognize.text == "pp_ocrv5_onnx"
    assert cfg.stages.export == "markdown"
    # ensemble is still unconfigured until M5.
    assert cfg.stages.ensemble is None
    # table / handwriting are set in M6.
    assert cfg.stages.recognize.table is None
    assert cfg.stages.recognize.handwriting is None


def test_pipeline_yaml_no_agpl_default_id() -> None:
    """Permissive-first: the AGPL DocLayout-YOLO id must never be a configured default."""
    cfg = load_pipeline_config()
    assert cfg.stages.layout != "doclayout_yolo"


def test_pipeline_yaml_ingest_block_loads() -> None:
    cfg = load_pipeline_config()
    assert cfg.ingest.base_dpi == 260
    assert cfg.ingest.max_dpi == 400
    assert cfg.ingest.small_font_px == 12
    assert cfg.ingest.born_digital_char_threshold == 20
    assert cfg.ingest.born_digital_coverage == 0.05
    assert cfg.ingest.preprocess.deskew is True
    assert cfg.ingest.preprocess.denoise is True
    assert cfg.ingest.preprocess.binarize is False
    assert cfg.ingest.preprocess.perspective is False
    assert cfg.ingest.preprocess.auto_crop is True


def test_ingest_config_defaults() -> None:
    cfg = IngestConfig()
    assert cfg.base_dpi == 260
    assert cfg.max_dpi == 400
    assert cfg.small_font_px == 12
    assert cfg.born_digital_char_threshold == 20
    assert cfg.born_digital_coverage == 0.05
    assert isinstance(cfg.preprocess, PreprocessSettings)


def test_preprocess_defaults() -> None:
    p = PreprocessSettings()
    assert p.deskew is True
    assert p.denoise is True
    assert p.binarize is False
    assert p.perspective is False
    assert p.auto_crop is True


def test_pipeline_config_default_has_ingest_block() -> None:
    cfg = PipelineConfig()
    assert isinstance(cfg.ingest, IngestConfig)
    assert cfg.ingest.base_dpi == 260
