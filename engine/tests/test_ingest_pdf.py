"""Tests for the pypdfium2 PDF renderer (ingest/pdf.py).

Uses the committed, reproducibly-generated ``born_digital_math.pdf`` fixture. Covers the
rendered-image size at the base DPI, the one-shot small-font raise firing at most once, and
the single pdfium point->pixel coordinate conversion against a known title span.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from texora_engine.ingest import SourceKind, iter_pdf_pages
from texora_engine.ingest.pdf import _pt_to_px_bbox, render_pdf_page
from texora_engine.pipeline_config import IngestConfig

# Fixture page is US Letter: 612 x 792 pt.
_PAGE_W_PT = 612.0
_PAGE_H_PT = 792.0


def _born_digital(fixtures_dir: Path) -> Path:
    return fixtures_dir / "born_digital_math.pdf"


def test_renders_page_at_expected_size(fixtures_dir: Path) -> None:
    cfg = IngestConfig()
    pairs = list(iter_pdf_pages(_born_digital(fixtures_dir), cfg))
    assert len(pairs) == 1
    rendered, image = pairs[0]
    try:
        # 612pt * 260/72 = 2210 px; 792pt * 260/72 = 2860 px.
        assert rendered.width == round(_PAGE_W_PT * cfg.base_dpi / 72.0)
        assert rendered.height == round(_PAGE_H_PT * cfg.base_dpi / 72.0)
        assert (image.width, image.height) == (rendered.width, rendered.height)
        assert image.mode == "RGB"
        assert rendered.kind == SourceKind.PDF_BORN_DIGITAL
        assert rendered.text_layer is not None and len(rendered.text_layer) > 0
    finally:
        image.close()


def test_small_font_raise_fires_at_most_once(fixtures_dir: Path, monkeypatch) -> None:
    """A tiny ``small_font_px`` forces the raise; it must re-render exactly one more time."""

    cfg = IngestConfig(small_font_px=1000)  # every glyph is "small" -> force the raise

    import texora_engine.ingest.pdf as pdf_mod

    calls: list[int] = []
    original = pdf_mod._render_rgb

    def _counting_render(page: pdfium.PdfPage, dpi: int) -> Image.Image:
        calls.append(dpi)
        return original(page, dpi)

    monkeypatch.setattr(pdf_mod, "_render_rgb", _counting_render)

    with pdf_mod.open_pdf(_born_digital(fixtures_dir)) as doc:
        rendered, image = render_pdf_page(doc, 0, cfg)
    try:
        # Exactly two renders: base DPI then the single raised DPI (no loop).
        assert len(calls) == 2
        assert calls[0] == cfg.base_dpi
        assert calls[1] == min(round(cfg.base_dpi * 1.5), cfg.max_dpi)
        assert rendered.dpi == calls[1]
    finally:
        image.close()


def test_no_raise_when_font_large_enough(fixtures_dir: Path, monkeypatch) -> None:
    cfg = IngestConfig(small_font_px=1)  # no glyph is that tiny -> no raise

    import texora_engine.ingest.pdf as pdf_mod

    calls: list[int] = []
    original = pdf_mod._render_rgb

    def _counting_render(page: pdfium.PdfPage, dpi: int) -> Image.Image:
        calls.append(dpi)
        return original(page, dpi)

    monkeypatch.setattr(pdf_mod, "_render_rgb", _counting_render)

    with pdf_mod.open_pdf(_born_digital(fixtures_dir)) as doc:
        rendered, image = render_pdf_page(doc, 0, cfg)
    try:
        assert len(calls) == 1
        assert rendered.dpi == cfg.base_dpi
    finally:
        image.close()


def test_point_to_pixel_conversion_matches_known_span(fixtures_dir: Path) -> None:
    """The first title char 'E' sits at a known pdfium point box; verify the pixel bbox."""

    cfg = IngestConfig()
    dpi = cfg.base_dpi
    scale = dpi / 72.0

    # Read the authoritative pdfium char box for char 0 directly from the fixture.
    with pdfium.PdfDocument(str(_born_digital(fixtures_dir))) as doc:
        page = doc[0]
        try:
            textpage = page.get_textpage()
            try:
                assert textpage.get_text_range(0, 1) == "E"
                left, bottom, right, top = textpage.get_charbox(0)
            finally:
                textpage.close()
        finally:
            page.close()

    expected = (
        left * scale,
        (_PAGE_H_PT - top) * scale,
        right * scale,
        (_PAGE_H_PT - bottom) * scale,
    )
    got = _pt_to_px_bbox((left, bottom, right, top), _PAGE_H_PT, dpi)
    for g, e in zip(got, expected, strict=True):
        assert abs(g - e) < 1e-6

    # And the renderer-produced span for that same char agrees within a sub-pixel tolerance.
    pairs = list(iter_pdf_pages(_born_digital(fixtures_dir), cfg))
    rendered, image = pairs[0]
    try:
        assert rendered.text_layer is not None
        first = rendered.text_layer[0]
        assert first.text == "E"
        for g, e in zip(first.bbox, expected, strict=True):
            assert abs(g - e) < 0.5
        # The span must fall within the rendered image bounds (top-left origin).
        assert 0.0 <= first.bbox[0] < rendered.width
        assert 0.0 <= first.bbox[1] < rendered.height
    finally:
        image.close()
