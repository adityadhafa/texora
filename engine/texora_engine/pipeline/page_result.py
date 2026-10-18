"""Typed page/document result models — the stable pipeline contract (design §7.3).

These Pydantic v2 models are what the exporters (M3 §8) and the UI consume. They carry region
types, bounding boxes, confidence, reading order, and — crucially — an ordered ``inlines`` run
list so inline math lands at its true position inside a paragraph (resolves F5). A region the
engine cannot recognize is ``needs_review``/``failed`` with a ``detail``, never a fabricated guess.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from texora_engine.ingest.base import SourceKind
from texora_engine.layout.base import Region
from texora_engine.recognizers.base import ConfidenceKind, RecognitionStatus


class RunKind(StrEnum):
    """Kind of an inline run within a text block's flow."""

    TEXT = "text"
    MATH = "math"  # inline math ($...$), recognized by the reused pix2tex engine


class InlineRun(BaseModel):
    """One ordered span inside a paragraph/title line (design §6.5, F5).

    The exporter concatenates runs in list order to reproduce true in-paragraph inline math.
    """

    kind: RunKind
    text: str | None = Field(default=None, description="Populated iff kind == TEXT.")
    latex: str | None = Field(default=None, description="Populated iff kind == MATH (validated).")
    mathml: str | None = Field(default=None, description="Populated iff kind == MATH.")
    status: RecognitionStatus = Field(default=RecognitionStatus.OK)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_kind: ConfidenceKind = Field(default=ConfidenceKind.UNAVAILABLE)
    engine_id: str = Field(default="")
    detail: str | None = Field(default=None)


class RegionContent(BaseModel):
    """A single region's recognized content in reading order (design §7.3)."""

    region: Region
    # Text-ish regions carry an ORDERED list of inline runs (text + inline-math) so inline math
    # sits at its true position within the paragraph. A plain paragraph is a single TEXT run.
    inlines: list[InlineRun] = Field(default_factory=list)
    text: str | None = Field(default=None, description="Flattened plain text of the TEXT runs.")
    latex: str | None = Field(default=None, description="For BLOCK math (DISPLAY_MATH), validated.")
    mathml: str | None = Field(default=None, description="For BLOCK math regions.")
    status: RecognitionStatus = Field(default=RecognitionStatus.OK)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_kind: ConfidenceKind = Field(default=ConfidenceKind.UNAVAILABLE)
    engine_id: str = Field(default="", description="Which recognizer produced this.")
    detail: str | None = Field(default=None)


class PageResult(BaseModel):
    """One page's assembled, reading-ordered content."""

    index: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    dpi: int = Field(gt=0)
    kind: SourceKind
    contents: list[RegionContent] = Field(default_factory=list)
    status: RecognitionStatus = Field(default=RecognitionStatus.OK)


class DocumentResult(BaseModel):
    """A whole document's pages (M3: synchronous, all pages in memory for one doc)."""

    source_name: str
    pages: list[PageResult] = Field(default_factory=list)
