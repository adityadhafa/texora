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
# A vertical gutter wider than this fraction of page width splits spans into separate columns
# BEFORE line clustering, so a body line in the left column is never merged with one in the right.
_COLUMN_GUTTER_FRAC = 0.06
# A horizontal gap between consecutive spans on one line wider than this fraction of the local
# glyph height is a word boundary: a single space is inserted (born-digital PDFs carry spaces as
# positioning, not as space glyphs, so the per-character text layer has none). Calibrated between
# the within-word gaps (<=~0.3x height) and the inter-word gaps (>=~0.45x height) of the standard
# Type1 metrics the ingest fixtures use, so words separate without splitting inside a word.
_WORD_GAP_FRAC = 0.38


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


def join_spans_with_spaces(spans: list[PdfTextSpan]) -> str:
    """Join left-to-right ordered spans, inserting a space on a word-sized horizontal gap.

    pdfium's text layer is per-character and drops space glyphs (spaces are positioning, not
    characters), so a naive ``"".join`` jams words together. Between consecutive spans we insert a
    single space when the horizontal gap ``next.x0 - prev.x1`` exceeds ``_WORD_GAP_FRAC`` of the
    local glyph height — the same signal a reader uses to see a word boundary. Shared by the line
    text here and by the assembler's born-digital inline/plain-text joins so prose reads correctly.
    """

    if not spans:
        return ""
    ordered = sorted(spans, key=lambda s: s.bbox[0])
    parts: list[str] = [ordered[0].text]
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        gap = cur.bbox[0] - prev.bbox[2]
        height = max(cur.bbox[3] - cur.bbox[1], prev.bbox[3] - prev.bbox[1], 1.0)
        if gap > _WORD_GAP_FRAC * height:
            parts.append(" ")
        parts.append(cur.text)
    return "".join(parts).strip()


@dataclass
class _Line:
    """A clustered line of spans with its union box and aggregate text."""

    spans: list[PdfTextSpan]

    @property
    def text(self) -> str:
        return join_spans_with_spaces(self.spans)

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


def _detect_column_gutters(lines: list[_Line], page_width: int) -> list[float]:
    """Find persistent vertical column gutters (x-positions) from the clustered line bands.

    A column gutter is a vertical band empty across MOST lines — not a wide gap on a single line
    (a large centred display equation) nor the margin outside the text block. We scan candidate
    x-positions and keep those crossed by only a small fraction of the lines: a real gutter splits
    the body, so the lines spanning it (a centred display equation, a title) are the minority. Each
    maximal run of "mostly empty" candidate x's wider than ``_COLUMN_GUTTER_FRAC`` of the page is
    one gutter; its center is returned. Empty when the page is single-column.
    """

    if not lines or page_width <= 0:
        return []
    # Per-line GLYPH intervals (the actual span boxes). A line's union bbox always straddles the
    # gutter in a two-column band, so we must test the individual span coverage, not the bbox — a
    # line "crosses" x only when one of its glyph boxes covers x, leaving the gutter visibly empty.
    line_intervals: list[list[tuple[float, float]]] = [
        [(s.bbox[0], s.bbox[2]) for s in ln.spans] for ln in lines if ln.spans
    ]
    if len(line_intervals) < 2:
        return []

    text_left = min(x0 for ivs in line_intervals for x0, _ in ivs)
    text_right = max(x1 for ivs in line_intervals for _, x1 in ivs)
    if text_right - text_left <= 0:
        return []

    step = max(1.0, page_width / 400.0)
    gutter_px = page_width * _COLUMN_GUTTER_FRAC

    def _crossing(x: float) -> int:
        return sum(1 for ivs in line_intervals if any(x0 < x < x1 for x0, x1 in ivs))

    def _straddling(x: float) -> int:
        # Lines with a glyph on BOTH sides of x — the signature of a real inter-column gutter
        # (a page margin has text on only one side, so it is never counted as a gutter).
        count = 0
        for ivs in line_intervals:
            left = any(x1 <= x for _, x1 in ivs)
            right = any(x0 >= x for x0, _ in ivs)
            if left and right:
                count += 1
        return count

    # A candidate gutter x is nearly empty — crossed only by the odd full-width spanner (a title
    # or a centred display equation), which we tolerate up to ``max_cross`` lines — yet has body
    # text straddling it on both sides. Scan for maximal x-runs meeting both conditions; keep a run
    # wider than the gutter threshold. This keeps a real column boundary while dropping a one-off
    # gap inside a line and a page margin (which has text on only one side).
    max_cross = max(2, len(line_intervals) // 3)
    boundaries: list[float] = []
    run_start: float | None = None

    def _flush(start: float | None, end: float) -> None:
        if start is not None and end - start >= gutter_px:
            mid = (start + end) / 2.0
            if _straddling(mid) >= 2:
                boundaries.append(mid)

    x = text_left
    while x <= text_right:
        if _crossing(x) <= max_cross:
            if run_start is None:
                run_start = x
        else:
            _flush(run_start, x)
            run_start = None
        x += step
    _flush(run_start, text_right)
    return boundaries


def _split_line_at_gutters(
    spans: list[PdfTextSpan], gutters: list[float], page_width: int
) -> list[list[PdfTextSpan]]:
    """Split one clustered line into column segments at the page's persistent column gutters.

    Uses the fixed gutter x-positions from :func:`_detect_column_gutters` (stable across the whole
    page), so a left-column body line and a right-column body line on the SAME y-band become two
    regions instead of one straddling the gutter. A line only splits at a gutter when the gap
    between the two consecutive glyphs straddling it is ITSELF at least the column-gutter width —
    so a full-width title or a centred display equation whose letters merely span the gutter with
    normal inter-letter spacing is kept WHOLE (a title has no gutter-sized hole in its glyph run).
    """

    if not spans:
        return []
    if not gutters or page_width <= 0:
        return [sorted(spans, key=lambda s: s.bbox[0])]

    gutter_px = page_width * _COLUMN_GUTTER_FRAC
    ordered = sorted(spans, key=lambda s: s.bbox[0])
    segments: list[list[PdfTextSpan]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        gap = cur.bbox[0] - prev.bbox[2]
        straddles = any(prev.bbox[2] <= g <= cur.bbox[0] for g in gutters)
        if straddles and gap >= gutter_px:
            segments.append([cur])
        else:
            segments[-1].append(cur)
    return segments


def _cluster_lines(spans: list[PdfTextSpan]) -> list[_Line]:
    """Cluster spans into line bands by vertical OVERLAP, left-to-right within each band.

    Born-digital spans are per-character and glyph bbox heights vary (ascenders/descenders, and a
    large display glyph beside a short operator), so their y-centers differ on the SAME line —
    a fixed y-center epsilon then over-splits a mixed-height line (e.g. a display equation). We
    greedily grow line bands top-to-bottom and place a span in the first band it vertically
    overlaps by >=50% of the smaller height (the same robust rule the assembler uses), which keeps
    a line with mixed glyph heights together. Deterministic (y-top sort; ties on x0).
    """

    if not spans:
        return []

    by_top = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
    bands: list[list[PdfTextSpan]] = []
    band_bottoms: list[float] = []
    for span in by_top:
        top, bottom = span.bbox[1], span.bbox[3]
        placed = False
        for i, band in enumerate(bands):
            band_top = min(s.bbox[1] for s in band)
            band_bottom = band_bottoms[i]
            overlap = min(bottom, band_bottom) - max(top, band_top)
            min_h = min(bottom - top, band_bottom - band_top)
            if min_h > 0 and overlap >= 0.5 * min_h:
                band.append(span)
                band_bottoms[i] = max(band_bottom, bottom)
                placed = True
                break
        if not placed:
            bands.append([span])
            band_bottoms.append(bottom)

    bands.sort(key=lambda b: min(s.bbox[1] for s in b))
    return [_Line(sorted(band, key=lambda s: s.bbox[0])) for band in bands]


def _split_trailing_equation_number(
    line: _Line, page_width: int
) -> tuple[list[PdfTextSpan], list[PdfTextSpan]]:
    """Peel a trailing right-margin ``(n)`` equation number off a display/math line.

    Returns ``(body_spans, eqnum_spans)``. Born-digital spans are per-character, so the number is a
    RUN of spans (``(``, ``1``, ``)``) after a wide right-margin gap, not one span. We find the
    widest inter-glyph gap in the right portion of the line; if the trailing glyphs after a
    gutter-sized gap spell a standalone ``(n)`` they are peeled into their own EQUATION_NUMBER
    region (bound to the equation by reading_order). A line that is *only* ``(n)`` stays whole and
    is classified EQUATION_NUMBER by :func:`_classify_line`.
    """

    spans = sorted(line.spans, key=lambda s: s.bbox[0])
    if len(spans) < 2 or page_width <= 0:
        return list(spans), []

    gutter_px = page_width * _COLUMN_GUTTER_FRAC
    # Find the last wide gap (a right-margin separation before the number).
    split_at = -1
    for i in range(1, len(spans)):
        if spans[i].bbox[0] - spans[i - 1].bbox[2] >= gutter_px:
            split_at = i
    if split_at == -1:
        return list(spans), []

    tail = spans[split_at:]
    tail_text = "".join(s.text for s in tail).strip()
    if _is_equation_number(tail_text):
        return spans[:split_at], tail
    return list(spans), []


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

        # Cluster into line bands, derive the page's persistent column gutters from those bands,
        # then split each band at the gutters so a region never straddles a column gutter —
        # otherwise reading_order interleaves the two columns. A centred display line crossing a
        # gutter stays whole when no span boundary lands in the gutter band; the per-column regions
        # are re-sequenced by reading_order.
        clustered_lines = _cluster_lines(list(spans))
        gutters = _detect_column_gutters(clustered_lines, page.width)
        lines: list[_Line] = []
        for clustered in clustered_lines:
            for segment in _split_line_at_gutters(clustered.spans, gutters, page.width):
                lines.append(_Line(segment))
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
            body_spans, eqnum_spans = _split_trailing_equation_number(line, page.width)
            if not body_spans:
                body_spans, eqnum_spans = eqnum_spans, []
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
            if eqnum_spans:
                eqnum_line = _Line(eqnum_spans)
                regions.append(
                    Region(
                        type=RegionType.EQUATION_NUMBER,
                        bbox=eqnum_line.bbox,
                        confidence=_confidence_for(RegionType.EQUATION_NUMBER, eqnum_line),
                        source="born_digital",
                    )
                )
        return regions
