"""Born-digital structural layout tests.

These exercise the no-model structural detector over a typed pypdfium2 text layer. The spans are
real typed :class:`PdfTextSpan` inputs (the same contract ingest produces), NOT mocked OCR — the
detector derives structure from positions/fonts/math signals, it does not recognize glyphs.
"""

from __future__ import annotations

from PIL import Image
from texora_engine.ingest.base import PdfTextSpan, RenderedPage, SourceKind
from texora_engine.layout.base import RegionType
from texora_engine.layout.born_digital import BornDigitalLayoutDetector, span_is_mathish


def _page(spans: list[PdfTextSpan], width: int = 1000, height: int = 1400) -> RenderedPage:
    return RenderedPage(
        index=0,
        width=width,
        height=height,
        dpi=260,
        kind=SourceKind.PDF_BORN_DIGITAL,
        text_layer=spans,
    )


def _span(text: str, box: tuple[float, float, float, float], size: float, mathish: bool = False):
    return PdfTextSpan(text=text, bbox=box, font_size_pt=size, is_mathish=mathish)


def test_detects_title_paragraph_and_display_math_with_eqnum() -> None:
    spans = [
        # Large-font short centered line near the top -> TITLE
        _span("A Study of Energy", (350.0, 40.0, 650.0, 90.0), 24.0),
        # Normal paragraph line
        _span("This paragraph introduces the topic.", (40.0, 140.0, 900.0, 170.0), 11.0),
        # Isolated centered math-heavy line -> DISPLAY_MATH
        _span("E = m c² + ∑ α", (420.0, 300.0, 580.0, 340.0), 12.0, mathish=True),
        # Right-margin equation number on the same band
        _span("(1)", (930.0, 305.0, 970.0, 335.0), 11.0),
    ]
    detector = BornDigitalLayoutDetector()
    image = Image.new("RGB", (1000, 1400), "white")

    result = detector.detect(image, _page(spans))

    assert result.engine_id == "born_digital"
    types = [r.type for r in result.regions]
    # every region carries a bbox + a type + a structural confidence
    for r in result.regions:
        assert 0.0 <= r.confidence <= 1.0
        assert r.source == "born_digital"
        assert r.bbox.x1 >= r.bbox.x0 and r.bbox.y1 >= r.bbox.y0

    assert RegionType.TITLE in types
    assert RegionType.PARAGRAPH in types
    assert RegionType.DISPLAY_MATH in types
    assert RegionType.EQUATION_NUMBER in types


def test_is_mathish_signals_fire() -> None:
    # Font-flag signal from ingest.
    assert span_is_mathish(_span("x", (0, 0, 10, 10), 11.0, mathish=True))
    # Unicode math-block ratio signal (Greek + math operators dominate).
    assert span_is_mathish(_span("α+β=γ∑", (0, 0, 40, 10), 11.0))
    # Plain prose is not mathish.
    assert not span_is_mathish(_span("the quick brown fox", (0, 0, 100, 10), 11.0))


def test_inline_math_inside_text_line() -> None:
    # A line mixing prose with a mathish span classifies as INLINE_MATH (not plain paragraph).
    spans = [
        _span("the energy", (40.0, 200.0, 240.0, 230.0), 11.0),
        _span("E=mc²", (260.0, 200.0, 360.0, 230.0), 11.0, mathish=True),
        _span("is conserved", (380.0, 200.0, 600.0, 230.0), 11.0),
    ]
    detector = BornDigitalLayoutDetector()
    image = Image.new("RGB", (1000, 1400), "white")
    result = detector.detect(image, _page(spans))
    assert any(r.type == RegionType.INLINE_MATH for r in result.regions)


def _char_spans(text: str, x0: float, y0: float, size: float, mathish: bool = False):
    """Build per-character spans for ``text`` starting at ``x0`` (approximating pdfium output).

    Glyphs are ``0.55*size`` wide with ``0.12*size`` inter-letter gaps and a wider ``0.55*size``
    gap for an explicit space, so word boundaries are recoverable from geometry alone — the same
    signal the gap-based spacing + column split rely on. Space characters are dropped (pdfium does
    not emit them), only their positioning advance is kept.
    """

    spans: list[PdfTextSpan] = []
    x = x0
    glyph_w = 0.55 * size
    letter_gap = 0.12 * size
    space_gap = 0.55 * size
    for ch in text:
        if ch == " ":
            x += space_gap
            continue
        spans.append(_span(ch, (x, y0, x + glyph_w, y0 + size), size, mathish=mathish))
        x += glyph_w + letter_gap
    return spans


def test_two_column_body_splits_into_separate_regions() -> None:
    """A left- and right-column line on the SAME y-band become two regions, not one spanner.

    Built from per-character spans (pdfium's real primitive) at two x-origins separated by a wide
    gutter. The detector must split at the gutter so no body region straddles it (otherwise
    reading order interleaves the columns).
    """

    spans: list[PdfTextSpan] = []
    for row, (left, right) in enumerate(
        [
            ("the left column text", "the right column text"),
            ("continues down here", "continues over here"),
            ("and ends at the foot", "and ends on this side"),
        ]
    ):
        y = 200.0 + row * 60.0
        spans += _char_spans(left, 60.0, y, 11.0)
        spans += _char_spans(right, 560.0, y, 11.0)

    result = BornDigitalLayoutDetector().detect(
        Image.new("RGB", (1000, 1400), "white"), _page(spans)
    )
    # Every region sits entirely in the left OR the right column — none straddles the gutter.
    gutter_x = 500.0
    for r in result.regions:
        assert r.bbox.x1 <= gutter_x or r.bbox.x0 >= gutter_x, (r.bbox.x0, r.bbox.x1)
    # There are at least two regions on at least one shared y-band (the split happened).
    assert len(result.regions) >= 6


def test_per_character_equation_number_is_peeled() -> None:
    """A right-margin per-character ``(``,``1``,``)`` run is peeled into an EQUATION_NUMBER."""

    spans = _char_spans("E = mc2", 400.0, 300.0, 20.0, mathish=True)
    # The "(1)" sits far to the right after a wide gutter-sized gap, as per-character spans.
    spans += _char_spans("(1)", 900.0, 305.0, 11.0)
    result = BornDigitalLayoutDetector().detect(
        Image.new("RGB", (1000, 1400), "white"), _page(spans)
    )
    types = [r.type for r in result.regions]
    assert RegionType.EQUATION_NUMBER in types
    # The equation body region must NOT contain the "(1)" glyphs.
    non_eqnum = [r for r in result.regions if r.type != RegionType.EQUATION_NUMBER]
    assert non_eqnum and all(r.bbox.x1 < 900.0 for r in non_eqnum)


def test_empty_text_layer_yields_no_regions() -> None:
    detector = BornDigitalLayoutDetector()
    image = Image.new("RGB", (1000, 1400), "white")
    result = detector.detect(image, _page([]))
    assert result.regions == []
    assert result.engine_id == "born_digital"
