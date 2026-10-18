"""Ingest package: PDF rendering, image loading, detection, and preprocessing.

Public surface re-exported here so callers import from ``texora_engine.ingest`` without
reaching into submodules. Bitmaps are passed alongside :class:`RenderedPage` and freed by
the caller; the models themselves carry no PIL image (design §4.1).
"""

from __future__ import annotations

from texora_engine.ingest.base import (
    IngestError,
    PdfTextSpan,
    RenderedPage,
    SourceKind,
)
from texora_engine.ingest.detect import classify_pdf_page
from texora_engine.ingest.images import load_image_pages
from texora_engine.ingest.pdf import iter_pdf_pages, render_pdf_page
from texora_engine.ingest.preprocess import preprocess

__all__ = [
    "IngestError",
    "PdfTextSpan",
    "RenderedPage",
    "SourceKind",
    "classify_pdf_page",
    "iter_pdf_pages",
    "load_image_pages",
    "preprocess",
    "render_pdf_page",
]
