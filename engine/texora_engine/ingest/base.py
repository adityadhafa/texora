"""Typed ingest models + the ingest-specific error type.

These models are the stable, JSON-serializable contract the layout stage and the page
assembler consume. Deliberately NO ``PIL.Image`` is stored on :class:`RenderedPage`: the
bitmap travels alongside the model inside the assembler and is freed promptly, keeping
memory roughly constant for M4's streaming (design §4.1).

All bounding boxes in this package are expressed in **rendered-image pixels with a top-left
origin**. The single conversion from pdfium's point coordinates (bottom-left origin, 72 dpi)
to this frame lives in :mod:`texora_engine.ingest.pdf` and nowhere else.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    """How a page's pixels originated -- drives detection and preprocessing defaults."""

    PDF_BORN_DIGITAL = "pdf_born_digital"
    PDF_SCANNED = "pdf_scanned"
    IMAGE = "image"


class IngestError(Exception):
    """A page/image could not be loaded or decoded (bad file, over-bounds, corrupt).

    Raised by the loaders so the API layer can map it to a 422 per-image without crashing a
    multi-page or multi-document run. It is NOT a recognition failure (those are modelled as
    ``needs_review``/``failed`` results downstream), it is an ingest-time input rejection.
    """


class PdfTextSpan(BaseModel):
    """One positioned text run extracted from the pdfium text layer (born-digital PDFs).

    ``bbox`` is already converted to rendered-image pixels (top-left origin) at the page's
    effective DPI, so downstream code never re-does the point->pixel math.
    """

    text: str
    bbox: tuple[float, float, float, float] = Field(
        description="x0,y0,x1,y1 in rendered-image pixels, top-left origin.",
    )
    font_size_pt: float = Field(ge=0.0, description="Approx. glyph height in PDF points.")
    is_mathish: bool = Field(
        default=False,
        description="Set by the born-digital math heuristic; unused by the loaders themselves.",
    )


class RenderedPage(BaseModel):
    """A single rendered page's metadata (no bitmap -- see module docstring).

    ``text_layer`` is present only for born-digital PDF pages; it is ``None`` for scanned PDF
    pages and for standalone images.
    """

    index: int = Field(ge=0, description="0-based page index within the source document.")
    width: int = Field(gt=0, description="Rendered pixel width.")
    height: int = Field(gt=0, description="Rendered pixel height.")
    dpi: int = Field(gt=0, description="Effective DPI used (after any one-shot small-font raise).")
    kind: SourceKind
    text_layer: list[PdfTextSpan] | None = Field(
        default=None,
        description="Positioned spans for born-digital PDF pages; None otherwise.",
    )
