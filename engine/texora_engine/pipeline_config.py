"""Typed pipeline configuration loaded from ``pipeline.yaml``.

``recognize`` is a MAP of sub-stages (formula/text/table/handwriting) so each recognizer
type selects its engine id independently; M3+ fill the other keys. Config lives in
``pipeline.yaml`` + Pydantic — no magic constants scattered in code.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Repo-root pipeline.yaml, resolved relative to this file:
# <repo>/engine/texora_engine/pipeline_config.py -> <repo>/pipeline.yaml
_PIPELINE_YAML = Path(__file__).resolve().parents[2] / "pipeline.yaml"


class RecognizeStage(BaseModel):
    """Engine ids for each recognizer sub-stage (None = not configured yet)."""

    formula: str | None = None
    text: str | None = None  # M3
    table: str | None = None  # M6
    handwriting: str | None = None  # M6


class Stages(BaseModel):
    """Engine ids per pipeline stage."""

    ingest: str | None = None  # M3
    layout: str | None = None  # M3
    recognize: RecognizeStage = Field(default_factory=RecognizeStage)
    ensemble: str | None = None  # M5
    export: str | None = None


class PipelineConfig(BaseModel):
    """Top-level pipeline config."""

    version: int = 1
    stages: Stages = Field(default_factory=Stages)


def load_pipeline_config(path: Path | None = None) -> PipelineConfig:
    """Parse ``pipeline.yaml`` into a typed :class:`PipelineConfig`."""

    cfg_path = path or _PIPELINE_YAML
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return PipelineConfig.model_validate(raw)
