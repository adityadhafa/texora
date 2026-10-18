"""Born-digital vs scanned classification for PDF pages (design §4.4, R-ING-3).

A PDF page can be either born-digital (reliable embedded text layer) or scanned (an image
with little or no extractable text). The distinction decides whether the assembler takes the
structural born-digital layout fast-path or runs the model layout detector, so it is a pure,
unit-tested function over the pdfium text page -- not a heuristic buried in the renderer.

A page is classified ``PDF_BORN_DIGITAL`` iff pdfium reports at least
``born_digital_char_threshold`` non-whitespace characters AND the union of their bounding
boxes covers at least ``born_digital_coverage`` of the page area; otherwise ``PDF_SCANNED``.
"""

from __future__ import annotations

import pypdfium2 as pdfium

from texora_engine.ingest.base import SourceKind
from texora_engine.pipeline_config import IngestConfig


def _text_coverage_fraction(
    textpage: pdfium.PdfTextPage,
    n_chars: int,
    page_area_pt: float,
) -> float:
    """Fraction of page area covered by the bounding box of all text (points space).

    Uses the union (overall bounding rectangle) of the char boxes rather than summing
    per-char areas, so sparse-but-spread text still registers meaningful coverage while a
    stray glyph on an otherwise-blank page does not. Coverage is axis-independent, so the
    point-space measure is identical to the pixel-space one -- no conversion needed here.
    """

    if n_chars == 0 or page_area_pt <= 0.0:
        return 0.0

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    found = False
    for i in range(n_chars):
        char = textpage.get_text_range(i, 1)
        if not char or char.isspace():
            continue
        left, bottom, right, top = textpage.get_charbox(i)
        min_x = min(min_x, left)
        min_y = min(min_y, bottom)
        max_x = max(max_x, right)
        max_y = max(max_y, top)
        found = True

    if not found:
        return 0.0
    covered = max(0.0, (max_x - min_x)) * max(0.0, (max_y - min_y))
    return min(1.0, covered / page_area_pt)


def _non_whitespace_char_count(textpage: pdfium.PdfTextPage, n_chars: int) -> int:
    """Count characters that are not whitespace (pdfium reports layout spaces too)."""

    count = 0
    for i in range(n_chars):
        char = textpage.get_text_range(i, 1)
        if char and not char.isspace():
            count += 1
    return count


def classify_pdf_page(
    page: pdfium.PdfPage,
    page_width_pt: float,
    page_height_pt: float,
    cfg: IngestConfig,
) -> SourceKind:
    """Classify a single PDF page as born-digital or scanned (pure over the text page)."""

    textpage = page.get_textpage()
    try:
        n_chars = textpage.count_chars()
        char_count = _non_whitespace_char_count(textpage, n_chars)
        if char_count < cfg.born_digital_char_threshold:
            return SourceKind.PDF_SCANNED
        page_area_pt = page_width_pt * page_height_pt
        coverage = _text_coverage_fraction(textpage, n_chars, page_area_pt)
        if coverage < cfg.born_digital_coverage:
            return SourceKind.PDF_SCANNED
        return SourceKind.PDF_BORN_DIGITAL
    finally:
        textpage.close()
