"""Typed pipeline configuration loaded from ``pipeline.yaml``.

``recognize`` is a MAP of sub-stages (formula/text/table/handwriting) so each recognizer
type selects its engine id independently; M3+ fill the other keys. The top-level ``ingest``
block carries DPI + preprocess toggles as a typed :class:`IngestConfig`. Config lives in
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
    """Engine ids per pipeline stage.

    ``ingest`` and ``layout`` become live engine ids in M3 (e.g. ``pypdfium2`` /
    ``pp_doclayout_onnx``); ``recognize.text`` selects the M3 text adapter. A ``None`` value
    still means "not configured" so the factory raises a typed error rather than defaulting.
    """

    ingest: str | None = None  # M3 — e.g. "pypdfium2"
    layout: str | None = None  # M3 — e.g. "pp_doclayout_onnx"
    recognize: RecognizeStage = Field(default_factory=RecognizeStage)
    ensemble: str | None = None  # M5
    export: str | None = None  # M3 — e.g. "markdown"


class PreprocessSettings(BaseModel):
    """Individually toggleable ingest preprocessing steps (M3, design §5).

    Each step is a no-op when its flag is false, so a page can opt out of any single step
    without touching the others. Born-digital pages default to no preprocessing unless a
    flag is forced on by the caller.
    """

    deskew: bool = True
    denoise: bool = True
    binarize: bool = False  # off by default: PP-OCRv5/pix2tex prefer grayscale/color input
    perspective: bool = False  # off by default: only helps photographed pages
    auto_crop: bool = True


class IngestConfig(BaseModel):
    """Typed ingest configuration (M3, design §4/§5/N5).

    ``pipeline.yaml``'s top-level ``ingest:`` block is the source of truth for these values;
    they are mirrored into engine settings. DPI values live in the 220--400 band so scanned
    math stays legible; a one-shot small-font raise re-renders a page whose median glyph
    height falls below ``small_font_px``.
    """

    base_dpi: int = Field(default=260, ge=72, description="Default render DPI for PDF pages.")
    max_dpi: int = Field(
        default=400,
        ge=72,
        description="Upper bound for the one-shot small-font DPI raise.",
    )
    small_font_px: int = Field(
        default=12,
        ge=1,
        description="Median glyph cap-height (px) below which a page is re-rendered once.",
    )
    born_digital_char_threshold: int = Field(
        default=20,
        ge=0,
        description="Minimum extractable characters for a page to count as born-digital.",
    )
    born_digital_coverage: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Minimum fraction of page area covered by text bboxes for born-digital.",
    )
    preprocess: PreprocessSettings = Field(default_factory=PreprocessSettings)


class PipelineConfig(BaseModel):
    """Top-level pipeline config."""

    version: int = 1
    stages: Stages = Field(default_factory=Stages)
    ingest: IngestConfig = Field(default_factory=IngestConfig)


def load_pipeline_config(path: Path | None = None) -> PipelineConfig:
    """Parse ``pipeline.yaml`` into a typed :class:`PipelineConfig`."""

    cfg_path = path or _PIPELINE_YAML
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return PipelineConfig.model_validate(raw)
