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


def test_empty_text_layer_yields_no_regions() -> None:
    detector = BornDigitalLayoutDetector()
    image = Image.new("RGB", (1000, 1400), "white")
    result = detector.detect(image, _page([]))
    assert result.regions == []
    assert result.engine_id == "born_digital"
