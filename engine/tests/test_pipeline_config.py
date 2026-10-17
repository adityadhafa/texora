"""pipeline.yaml typed-config tests."""

from __future__ import annotations

from texora_engine.pipeline_config import load_pipeline_config


def test_pipeline_yaml_configures_formula_pix2tex() -> None:
    cfg = load_pipeline_config()
    assert cfg.version == 1
    assert cfg.stages.recognize.formula == "pix2tex"
    # Other stages remain unconfigured in M2.
    assert cfg.stages.ingest is None
    assert cfg.stages.recognize.text is None
