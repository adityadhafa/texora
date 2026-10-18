"""Stable layout-detector Protocol + shared region types (design §6.1).

``LayoutDetector`` is the engine-agnostic seam that keeps the API/UI free of any specific
layout model, mirroring the M2 ``recognizers/base.py`` ``FormulaRecognizer`` pattern. Adapters
implement it; the layout factory selects one by id from ``pipeline.yaml``. Results are Pydantic
models (not bare dicts) so they serialize straight into the pipeline and are mypy-strict across
module boundaries.

**Honesty invariant (``R-REC-8``):** ``detect`` MUST catch its own inference errors and return an
empty :class:`LayoutResult` (``regions=[]``) with ``engine_id`` set — it NEVER raises and NEVER
fabricates a region. A failed detection downgrades the whole page to ``needs_review`` in the
assembler, never an invented layout.

All bounding boxes are expressed in **rendered-image pixels with a top-left origin**, the single
coordinate frame established by :mod:`texora_engine.ingest.pdf`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from PIL import Image
from pydantic import BaseModel, Field

from texora_engine.ingest.base import RenderedPage


class RegionType(StrEnum):
    """The full layout region taxonomy (``R-LAY-1``, design §6.1).

    Covers both the structural born-digital path and the PP-DocLayout model path; unknown/
    low-confidence detections collapse to :attr:`UNKNOWN` rather than being dropped or guessed.
    """

    TITLE = "title"
    PARAGRAPH = "paragraph"
    INLINE_MATH = "inline_math"
    DISPLAY_MATH = "display_math"
    EQUATION_NUMBER = "equation_number"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    LIST = "list"
    CODE = "code"
    HANDWRITING = "handwriting"
    UNKNOWN = "unknown"


class BBox(BaseModel):
    """An axis-aligned box in rendered-image pixels, top-left origin."""

    x0: float = Field(description="Left edge (px).")
    y0: float = Field(description="Top edge (px).")
    x1: float = Field(description="Right edge (px).")
    y1: float = Field(description="Bottom edge (px).")

    @property
    def width(self) -> float:
        """Box width in pixels (``x1 - x0``)."""

        return self.x1 - self.x0

    @property
    def height(self) -> float:
        """Box height in pixels (``y1 - y0``)."""

        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        """Horizontal center of the box (px)."""

        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        """Vertical center of the box (px)."""

        return (self.y0 + self.y1) / 2.0


class Region(BaseModel):
    """One detected layout region with its type, box, confidence, and ordering slot."""

    type: RegionType
    bbox: BBox
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detection confidence (model score, or a documented structural heuristic).",
    )
    reading_order: int = Field(
        default=-1,
        description="Filled by reading_order.order(); -1 means unset.",
    )
    source: str = Field(
        default="model",
        description="Provenance: 'model' | 'born_digital'.",
    )


class LayoutResult(BaseModel):
    """The typed result of a single page's layout detection."""

    regions: list[Region]
    engine_id: str = Field(description="Adapter id that produced this result.")


@runtime_checkable
class LayoutDetector(Protocol):
    """Stable, minimal, pure layout-detection interface (mirror of ``FormulaRecognizer``)."""

    id: str
    # Model registry id(s) this adapter needs, declared by the adapter rather than assuming
    # adapter.id == model.id (design §2.1).
    model_ids: tuple[str, ...]

    def detect(self, image: Image.Image, page: RenderedPage) -> LayoutResult:
        """Detect layout regions in ``image`` for the given ``page``.

        ``page`` is passed so a structural detector can read the born-digital text layer.
        Pure: no I/O beyond the model forward pass. Implementations MUST catch their own
        inference errors and return ``LayoutResult(regions=[], engine_id=self.id)`` rather than
        raising, and MUST NEVER fabricate a region.
        """
        ...
