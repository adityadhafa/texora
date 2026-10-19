"""Shared fixed DocumentResult for the golden-file export tests (design §8.3, task 3.7).

This is DETERMINISTIC TEST DATA — a hand-constructed :class:`DocumentResult` built from known
regions, NOT a mocked production OCR result. It deliberately includes a paragraph with inline math
so the golden ``.md``/``.tex`` byte-assert that ``$...$`` lands mid-paragraph (resolves F5), plus a
numbered display equation, a figure, a table placeholder, and a needs_review run.
"""

from __future__ import annotations

from texora_engine.ingest.base import SourceKind
from texora_engine.layout.base import BBox, Region, RegionType
from texora_engine.pipeline.page_result import (
    DocumentResult,
    InlineRun,
    PageResult,
    RegionContent,
    RunKind,
)
from texora_engine.recognizers.base import ConfidenceKind, RecognitionStatus


def _region(rtype: RegionType, order: int, x0: float = 0.0) -> Region:
    return Region(
        type=rtype,
        bbox=BBox(x0=x0, y0=float(order * 50), x1=x0 + 200.0, y1=float(order * 50 + 40)),
        confidence=0.9,
        reading_order=order,
        source="born_digital",
    )


def build_sample_document() -> DocumentResult:
    """Return the fixed sample document rendered by the golden tests."""

    title = RegionContent(
        region=_region(RegionType.TITLE, 0),
        inlines=[InlineRun(kind=RunKind.TEXT, text="Energy and Mass Equivalence")],
        text="Energy and Mass Equivalence",
        status=RecognitionStatus.OK,
        engine_id="born_digital",
    )

    # Paragraph with inline math mid-sentence: text -> MATH -> text (the F5 proof).
    para = RegionContent(
        region=_region(RegionType.PARAGRAPH, 1),
        inlines=[
            InlineRun(kind=RunKind.TEXT, text="In special relativity the energy is "),
            InlineRun(
                kind=RunKind.MATH,
                latex="E = mc^2",
                mathml=None,
                status=RecognitionStatus.OK,
                confidence=0.98,
                confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
                engine_id="pix2tex",
            ),
            InlineRun(kind=RunKind.TEXT, text=" which binds mass and energy."),
        ],
        text="In special relativity the energy is  which binds mass and energy.",
        status=RecognitionStatus.OK,
        engine_id="pix2tex",
    )

    display = RegionContent(
        region=_region(RegionType.DISPLAY_MATH, 2),
        latex="E = m c^2",
        mathml=None,
        status=RecognitionStatus.OK,
        confidence=0.97,
        confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
        engine_id="pix2tex",
    )
    eqnum = RegionContent(
        region=_region(RegionType.EQUATION_NUMBER, 3, x0=500.0),
        inlines=[InlineRun(kind=RunKind.TEXT, text="(1)")],
        text="(1)",
        status=RecognitionStatus.OK,
        engine_id="born_digital",
    )

    figure = RegionContent(
        region=_region(RegionType.FIGURE, 4),
        status=RecognitionStatus.OK,
        engine_id="figure",
        detail="fig_p0_10_10.png",
    )

    table = RegionContent(
        region=_region(RegionType.TABLE, 5),
        status=RecognitionStatus.NEEDS_REVIEW,
        detail="table recognition is M6",
    )

    # A paragraph whose inline math could not be recognized -> honest needs_review marker.
    unsure = RegionContent(
        region=_region(RegionType.PARAGRAPH, 6),
        inlines=[
            InlineRun(kind=RunKind.TEXT, text="An unresolved fragment "),
            InlineRun(
                kind=RunKind.MATH,
                latex="",
                status=RecognitionStatus.NEEDS_REVIEW,
                engine_id="pix2tex",
                detail="low confidence",
            ),
            InlineRun(kind=RunKind.TEXT, text=" remains."),
        ],
        text="An unresolved fragment  remains.",
        status=RecognitionStatus.NEEDS_REVIEW,
        engine_id="pix2tex",
    )

    page = PageResult(
        index=0,
        width=612,
        height=792,
        dpi=260,
        kind=SourceKind.PDF_BORN_DIGITAL,
        contents=[title, para, display, eqnum, figure, table, unsure],
        status=RecognitionStatus.NEEDS_REVIEW,
    )
    return DocumentResult(source_name="doc_sample", pages=[page])


def build_empty_page(index: int) -> PageResult:
    """A committed page that renders ZERO blocks (a blank page) — exercises the empty-fragment
    filter (design §7.1 MEDIUM-1): its md/tex body fragment is ``""`` and must contribute no
    separator at concat, byte-identical to the whole-document exporter."""

    return PageResult(
        index=index,
        width=612,
        height=792,
        dpi=260,
        kind=SourceKind.PDF_BORN_DIGITAL,
        contents=[],
        status=RecognitionStatus.OK,
    )


def build_multipage_document_with_empty() -> DocumentResult:
    """A multi-page document: a content page, an EMPTY page, then another content page (indices
    0,1,2). Used by the M4 fragment-concat golden to prove the empty-fragment filter + the
    committed-subset byte-equivalence against the whole-document exporters."""

    base = build_sample_document().pages[0]
    p0 = base.model_copy(update={"index": 0})
    p1 = build_empty_page(1)
    p2 = base.model_copy(update={"index": 2})
    return DocumentResult(source_name="doc_sample", pages=[p0, p1, p2])
