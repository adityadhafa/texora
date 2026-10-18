"""Born-digital structural layout detector — NO model, NO download (design §3.1, §6.3).

This is the assembler-owned structural fast-path for born-digital PDF pages: regions are derived
directly from the pypdfium2 text layer (:class:`~texora_engine.ingest.base.PdfTextSpan`), so it is
permissive by construction (pypdfium2 is BSD/Apache) and needs no model inference at all. It is
**NOT** a registry id (no ``model_ids``, never written into ``pipeline.yaml``); it is always
available and selected by the assembler when a page is born-digital.

Confidence here is a documented **structural heuristic** score (span-count / signal strength), NOT
a model probability — it is honest about its provenance and must not be read as a calibrated model
confidence (design §6.3).

The minimal ``is_mathish`` signal set (design §6.3 math heuristic):
1. **math Unicode-block ratio** — fraction of characters in math/technical Unicode blocks;
2. **italic / math-font flag** — carried per span by ``PdfTextSpan.is_mathish`` from ingest;
3. **line isolation** — a short, horizontally-centered, isolated line (display-equation shape);
4. **right-margin ``(n)`` equation number** — a trailing parenthesized integer near the right edge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from texora_engine.ingest.base import PdfTextSpan, RenderedPage
from texora_engine.layout.base import BBox, LayoutResult, Region, RegionType
from texora_engine.logging_config import get_logger

logger = get_logger("layout.born_digital")

# A trailing parenthesized equation number, e.g. "(1)", "(3.2)", "(12a)".
_EQUATION_NUMBER_RE = re.compile(r"^\(\s*\d+[A-Za-z.\-]*\s*\)$")

# Fraction of a span's characters that must sit in math/technical Unicode blocks for the span to
# count as mathish by the block-ratio signal.
_MATH_BLOCK_RATIO_THRESHOLD = 0.30
# A line whose width is below this fraction of the page width AND is horizontally centered is a
# display-equation-shaped isolated line.
_ISOLATED_LINE_WIDTH_FRAC = 0.75
# Font-size percentile above which a block is treated as a TITLE.
_TITLE_FONT_PERCENTILE = 0.85
# Right-margin band (fraction of page width from the right edge) an equation number must sit in.
_RIGHT_MARGIN_FRAC = 0.80


def _is_math_char(ch: str) -> bool:
    """True if ``ch`` lives in a math/technical Unicode block (Greek, math operators, symbols)."""

    cp = ord(ch)
    return (
        0x0370 <= cp <= 0x03FF  # Greek and Coptic
        or 0x1D400 <= cp <= 0x1D7FF  # Mathematical Alphanumeric Symbols
        or 0x2200 <= cp <= 0x22FF  # Mathematical Operators
        or 0x2A00 <= cp <= 0x2AFF  # Supplemental Mathematical Operators
        or 0x2190 <= cp <= 0x21FF  # Arrows
        or 0x27C0 <= cp <= 0x27EF  # Misc Mathematical Symbols-A
        or 0x2980 <= cp <= 0x29FF  # Misc Mathematical Symbols-B
        or ch in "=±×÷∑∏∫√∞≈≠≤≥∂∇"
    )


def _math_block_ratio(text: str) -> float:
    """Fraction of ``text``'s non-space characters that are math/technical characters."""

    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if _is_math_char(c)) / len(chars)


def _is_equation_number(text: str) -> bool:
    """True if ``text`` is a standalone parenthesized equation number like ``(1)``."""

    return bool(_EQUATION_NUMBER_RE.match(text.strip()))


def span_is_mathish(span: PdfTextSpan) -> bool:
    """Whether a single span reads as math by the block-ratio or the ingest font flag.

    Line-isolation and the right-margin ``(n)`` signals are line-level and handled in
    :func:`_classify_line`; this covers the two per-span signals of the design's set.
    """

    return span.is_mathish or _math_block_ratio(span.text) >= _MATH_BLOCK_RATIO_THRESHOLD


@dataclass
class _Line:
    """A clustered line of spans with its union box and aggregate text."""

    spans: list[PdfTextSpan]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.spans).strip()

    @property
    def bbox(self) -> BBox:
        x0 = min(s.bbox[0] for s in self.spans)
        y0 = min(s.bbox[1] for s in self.spans)
        x1 = max(s.bbox[2] for s in self.spans)
        y1 = max(s.bbox[3] for s in self.spans)
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)

    @property
    def font_size_pt(self) -> float:
        return max((s.font_size_pt for s in self.spans), default=0.0)


def _cluster_lines(spans: list[PdfTextSpan]) -> list[_Line]:
    """Cluster spans into lines by vertical overlap, left-to-right within each line.

    Deterministic: spans are sorted by (y-center, x0) and a new line starts when a span's
    y-center falls outside the current line's vertical band (half the median span height).
    """

    if not spans:
        return []

    def ycenter(s: PdfTextSpan) -> float:
        return (s.bbox[1] + s.bbox[3]) / 2.0

    def height(s: PdfTextSpan) -> float:
        return s.bbox[3] - s.bbox[1]

    ordered = sorted(spans, key=lambda s: (round(ycenter(s), 1), s.bbox[0]))
    heights = sorted(height(s) for s in ordered)
    median_h = heights[len(heights) // 2] if heights else 1.0
    band = max(median_h * 0.5, 1.0)

    lines: list[list[PdfTextSpan]] = []
    current: list[PdfTextSpan] = []
    current_y: float | None = None
    for s in ordered:
        yc = ycenter(s)
        if current_y is None or abs(yc - current_y) <= band:
            current.append(s)
            # running mean of the line's y-center keeps clustering stable
            current_y = sum(ycenter(c) for c in current) / len(current)
        else:
            lines.append(current)
            current = [s]
            current_y = yc
    if current:
        lines.append(current)

    # left-to-right within each line
    return [_Line(sorted(line, key=lambda s: s.bbox[0])) for line in lines]


def _split_trailing_equation_number(
    line: _Line,
) -> tuple[list[PdfTextSpan], PdfTextSpan | None]:
    """Peel a trailing standalone ``(n)`` span off a line, if present.

    Returns ``(body_spans, eqnum_span_or_None)``. Only splits when there is more than one span
    and the last span is itself a standalone equation number — a line that is *only* ``(n)`` stays
    whole and is classified as EQUATION_NUMBER by :func:`_classify_line`.
    """

    if len(line.spans) > 1 and _is_equation_number(line.spans[-1].text):
        return line.spans[:-1], line.spans[-1]
    return list(line.spans), None


def _classify_line(line: _Line, page: RenderedPage, title_font_cutoff: float) -> RegionType:
    """Classify a single clustered line into a :class:`RegionType` (design §6.3)."""

    text = line.text
    if _is_equation_number(text):
        # Right-margin (n) => EQUATION_NUMBER; a centered/left (n) is still an equation number.
        return RegionType.EQUATION_NUMBER

    bbox = line.bbox
    width_frac = bbox.width / page.width if page.width else 1.0
    centered = (
        page.width > 0
        and abs(bbox.cx - page.width / 2.0) < page.width * 0.15
        and width_frac < _ISOLATED_LINE_WIDTH_FRAC
    )
    math_ratio = _math_block_ratio(text)
    any_math_span = any(span_is_mathish(s) for s in line.spans)

    # Display math: an isolated, short, centered line that is math-heavy (line-isolation signal).
    if (centered and (math_ratio >= _MATH_BLOCK_RATIO_THRESHOLD or any_math_span)) or (
        math_ratio >= 0.5 and width_frac < _ISOLATED_LINE_WIDTH_FRAC
    ):
        return RegionType.DISPLAY_MATH

    # Inline math: a text line that still carries mathish spans.
    if any_math_span or math_ratio >= _MATH_BLOCK_RATIO_THRESHOLD:
        return RegionType.INLINE_MATH

    # Title: a large-font short line near the page top.
    if line.font_size_pt >= title_font_cutoff and width_frac < _ISOLATED_LINE_WIDTH_FRAC:
        return RegionType.TITLE

    # List: a leading bullet/number marker.
    stripped = text.lstrip()
    if stripped[:1] in {"-", "•", "*", "·"} or re.match(r"^\(?\d+[.)]\s", stripped):
        return RegionType.LIST

    return RegionType.PARAGRAPH


def _confidence_for(rtype: RegionType, line: _Line) -> float:
    """A documented structural heuristic confidence (NOT a model probability, design §6.3).

    Scored from signal strength: more spans and a clear classification read as more confident;
    an UNKNOWN/ambiguous line is less confident. Bounded to [0, 1].
    """

    base = 0.6
    if rtype in {RegionType.DISPLAY_MATH, RegionType.EQUATION_NUMBER}:
        base = 0.8
    elif rtype in {RegionType.TITLE, RegionType.PARAGRAPH, RegionType.LIST}:
        base = 0.7
    span_bonus = min(len(line.spans) * 0.02, 0.15)
    return max(0.0, min(1.0, base + span_bonus))


class BornDigitalLayoutDetector:
    """Structural layout detector over a born-digital PDF page's text layer.

    Not a factory-registered engine id (no ``model_ids``). Always available; the assembler uses
    it for ``PDF_BORN_DIGITAL`` pages.
    """

    id = "born_digital"

    def detect(self, image: Image.Image, page: RenderedPage) -> LayoutResult:
        """Build structural regions from ``page.text_layer``; never raise, never fabricate."""

        try:
            regions = self._detect(page)
        except Exception as exc:  # structural pass must not crash the caller (R-REC-8)
            logger.warning("born_digital layout failed: %s", exc)
            return LayoutResult(regions=[], engine_id=self.id)
        return LayoutResult(regions=regions, engine_id=self.id)

    def _detect(self, page: RenderedPage) -> list[Region]:
        spans = page.text_layer or []
        if not spans:
            return []

        lines = _cluster_lines(list(spans))
        if not lines:
            return []

        sizes = sorted(line.font_size_pt for line in lines)
        idx = int(len(sizes) * _TITLE_FONT_PERCENTILE)
        idx = min(idx, len(sizes) - 1)
        title_font_cutoff = sizes[idx]

        regions: list[Region] = []
        for line in lines:
            # Peel a trailing standalone equation-number span (e.g. a display equation followed by
            # a right-margin "(1)") into its own EQUATION_NUMBER region so the number is bound to
            # its equation by reading_order, not folded into the equation's text.
            body_spans, eqnum_span = _split_trailing_equation_number(line)
            body_line = _Line(body_spans)
            rtype = _classify_line(body_line, page, title_font_cutoff)
            regions.append(
                Region(
                    type=rtype,
                    bbox=body_line.bbox,
                    confidence=_confidence_for(rtype, body_line),
                    source="born_digital",
                )
            )
            if eqnum_span is not None:
                eqnum_line = _Line([eqnum_span])
                regions.append(
                    Region(
                        type=RegionType.EQUATION_NUMBER,
                        bbox=eqnum_line.bbox,
                        confidence=_confidence_for(RegionType.EQUATION_NUMBER, eqnum_line),
                        source="born_digital",
                    )
                )
        return regions
