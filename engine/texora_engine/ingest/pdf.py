"""pypdfium2 PDF rendering: lazy per-page iteration, adaptive DPI, text-layer extraction.

This module owns the ONLY pdfium point->pixel coordinate conversion in the codebase. pdfium
reports char boxes as ``(left, bottom, right, top)`` in PDF canvas units (points, 1/72 inch,
origin bottom-left). Every :class:`PdfTextSpan` emitted here is already converted to
rendered-image pixels (top-left origin) at the page's effective DPI, so no other module has
to reason about PDF coordinate space.

Pages are yielded one bitmap at a time (never materializing the whole document) so M4 can
stream arbitrarily large PDFs with roughly constant memory. The caller receives a
``(RenderedPage, PIL.Image)`` pair and is responsible for closing the image when done.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from texora_engine.ingest.base import IngestError, PdfTextSpan, RenderedPage, SourceKind
from texora_engine.ingest.detect import classify_pdf_page
from texora_engine.logging_config import get_logger
from texora_engine.pipeline_config import IngestConfig

logger = get_logger("ingest.pdf")

_POINTS_PER_INCH = 72.0


def _scale_for_dpi(dpi: int) -> float:
    """Render scale factor: pdfium renders at 72 dpi * scale."""

    return dpi / _POINTS_PER_INCH


def _pt_to_px_bbox(
    box_pt: tuple[float, float, float, float],
    page_height_pt: float,
    dpi: int,
) -> tuple[float, float, float, float]:
    """Convert a pdfium char box to rendered-image pixels (top-left origin).

    ``box_pt`` is ``(left, bottom, right, top)`` in points, origin bottom-left. The rendered
    image has origin top-left and ``scale = dpi/72`` pixels per point, so::

        x_px = x_pt * scale
        y_px = (page_height_pt - y_pt) * scale      # flip the vertical axis

    which maps the PDF ``top`` edge to the smaller (upper) pixel-y. This is the single
    conversion site referenced throughout the design.
    """

    left, bottom, right, top = box_pt
    scale = _scale_for_dpi(dpi)
    x0 = left * scale
    x1 = right * scale
    # Flip: PDF 'top' (larger y) becomes the upper pixel row (smaller y).
    y0 = (page_height_pt - top) * scale
    y1 = (page_height_pt - bottom) * scale
    return (x0, y0, x1, y1)


def _extract_text_layer(
    page: pdfium.PdfPage,
    page_height_pt: float,
    dpi: int,
) -> list[PdfTextSpan]:
    """Build one :class:`PdfTextSpan` per character from the pdfium text page.

    Spans are per-character (the stable pdfium primitive); the born-digital layout detector
    clusters them into lines/blocks later. ``font_size_pt`` is approximated from the char
    box height in points (origin-independent, so no flip needed for the size).
    """

    textpage = page.get_textpage()
    try:
        spans: list[PdfTextSpan] = []
        n_chars = textpage.count_chars()
        for i in range(n_chars):
            char = textpage.get_text_range(i, 1)
            if not char or char.isspace():
                continue
            box_pt = textpage.get_charbox(i)  # (left, bottom, right, top) in points
            left, bottom, right, top = box_pt
            font_size_pt = max(0.0, top - bottom)
            spans.append(
                PdfTextSpan(
                    text=char,
                    bbox=_pt_to_px_bbox(box_pt, page_height_pt, dpi),
                    font_size_pt=font_size_pt,
                )
            )
        return spans
    finally:
        textpage.close()


def _render_rgb(page: pdfium.PdfPage, dpi: int) -> Image.Image:
    """Render a page to an RGB :class:`PIL.Image` at the given DPI, freeing the bitmap."""

    bitmap = page.render(scale=_scale_for_dpi(dpi))
    try:
        pil: Image.Image = bitmap.to_pil()
    finally:
        bitmap.close()
    if pil.mode != "RGB":
        converted: Image.Image = pil.convert("RGB")
        if converted is not pil:
            pil.close()
        return converted
    return pil


def _median_cap_height_px(spans: list[PdfTextSpan]) -> float | None:
    """Median glyph cap-height in pixels from the extracted text layer, or None if empty."""

    heights = sorted(s.bbox[3] - s.bbox[1] for s in spans if s.bbox[3] > s.bbox[1])
    if not heights:
        return None
    mid = len(heights) // 2
    if len(heights) % 2 == 1:
        return heights[mid]
    return (heights[mid - 1] + heights[mid]) / 2.0


def _needs_small_font_raise(median_cap_px: float | None, cfg: IngestConfig) -> bool:
    """A page re-renders once when its median glyph cap-height is below the threshold."""

    if median_cap_px is None:
        return False
    return median_cap_px < cfg.small_font_px


def _raised_dpi(cfg: IngestConfig) -> int:
    """The one-shot raised DPI, bounded by ``max_dpi`` (raise factor 1.5 per design N1)."""

    return min(int(round(cfg.base_dpi * 1.5)), cfg.max_dpi)


@contextmanager
def open_pdf(path: str | Path) -> Iterator[pdfium.PdfDocument]:
    """Open a PDF, raising :class:`IngestError` on a bad/corrupt file; always closed."""

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:  # corrupt / unsupported
        raise IngestError(f"could not open PDF {path!s}: {exc}") from exc
    except OSError as exc:  # missing / unreadable
        raise IngestError(f"could not read PDF {path!s}: {exc}") from exc
    try:
        yield pdf
    finally:
        pdf.close()


def render_pdf_page(
    pdf: pdfium.PdfDocument,
    index: int,
    cfg: IngestConfig,
) -> tuple[RenderedPage, Image.Image]:
    """Render a single page with adaptive DPI + one-shot small-font raise.

    Returns the ``(RenderedPage, PIL.Image)`` pair. The caller owns the image and MUST close
    it. The small-font raise re-renders at most once per page (bounded work, no loops).
    """

    page = pdf[index]
    try:
        page_width_pt, page_height_pt = page.get_size()
        kind = classify_pdf_page(page, page_width_pt, page_height_pt, cfg)

        dpi = cfg.base_dpi
        text_layer: list[PdfTextSpan] | None = None
        median_cap_px: float | None = None

        if kind == SourceKind.PDF_BORN_DIGITAL:
            text_layer = _extract_text_layer(page, page_height_pt, dpi)
            median_cap_px = _median_cap_height_px(text_layer)

        image = _render_rgb(page, dpi)

        if _needs_small_font_raise(median_cap_px, cfg):
            raised = _raised_dpi(cfg)
            if raised > dpi:
                logger.info(
                    "small-font raise: page %d median cap %.1fpx < %dpx -> re-render %d->%d dpi",
                    index,
                    median_cap_px or 0.0,
                    cfg.small_font_px,
                    dpi,
                    raised,
                )
                image.close()
                dpi = raised
                image = _render_rgb(page, dpi)
                if text_layer is not None:
                    text_layer = _extract_text_layer(page, page_height_pt, dpi)

        rendered = RenderedPage(
            index=index,
            width=image.width,
            height=image.height,
            dpi=dpi,
            kind=kind,
            text_layer=text_layer,
        )
        return rendered, image
    finally:
        page.close()


def iter_pdf_pages(
    path: str | Path,
    cfg: IngestConfig,
) -> Iterator[tuple[RenderedPage, Image.Image]]:
    """Lazily yield ``(RenderedPage, PIL.Image)`` for every page, one bitmap at a time.

    The caller MUST close each yielded image before requesting the next page to keep memory
    constant. Raises :class:`IngestError` if the document cannot be opened.
    """

    with open_pdf(path) as pdf:
        for index in range(len(pdf)):
            yield render_pdf_page(pdf, index, cfg)
