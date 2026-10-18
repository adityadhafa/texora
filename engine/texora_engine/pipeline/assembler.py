"""Page assembler — ingest -> layout -> reading-order -> recognition -> PageResult (design §7.4).

``assemble_page(rendered, image, deps)`` is a pure function of its inputs (no cross-page state, so
M4's job runner can call it per page and free the bitmap for constant memory). It reuses the
committed FEAT-003 layout API (born-digital structural detector + configured ``LayoutDetector`` +
``reading_order.order``) and the M2 pix2tex ``FormulaRecognizer`` UNCHANGED for all math — it never
reimplements recognition.

Per-region recognition runs under a per-region timeout via a single-worker executor (design §7.5):
a slow/hostile region is marked ``failed`` and the page continues. Tables and handwriting are
detected but marked ``needs_review`` (deferred to M6) — never fabricated. Every unrecognized region
is ``needs_review``/``failed`` with a ``detail`` (``R-REC-8``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from PIL import Image

from texora_engine.ensemble import validate_and_normalize
from texora_engine.export import latex_to_mathml
from texora_engine.ingest.base import PdfTextSpan, RenderedPage, SourceKind
from texora_engine.ingest.preprocess import preprocess
from texora_engine.layout.base import BBox, LayoutDetector, LayoutResult, Region, RegionType
from texora_engine.layout.born_digital import BornDigitalLayoutDetector, span_is_mathish
from texora_engine.layout.reading_order import order as order_regions
from texora_engine.logging_config import get_logger
from texora_engine.pipeline.page_result import (
    InlineRun,
    PageResult,
    RegionContent,
    RunKind,
)
from texora_engine.pipeline_config import PipelineConfig
from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaRecognizer,
    RecognitionStatus,
    RegionContext,
    TextRecognizer,
)
from texora_engine.settings import Settings

logger = get_logger("pipeline.assembler")

_T = TypeVar("_T")

# Text-ish region types whose content is an ordered inline-run list (text + inline math).
_TEXT_ISH = frozenset(
    {
        RegionType.PARAGRAPH,
        RegionType.TITLE,
        RegionType.CAPTION,
        RegionType.FOOTNOTE,
        RegionType.LIST,
        RegionType.CODE,
        RegionType.HEADER,
        RegionType.FOOTER,
    }
)
# Block / standalone math region types — always re-recognized from the crop via pix2tex.
_MATH_TYPES = frozenset({RegionType.DISPLAY_MATH, RegionType.INLINE_MATH})

# Status severity for the worst-of page roll-up (failed > needs_review > ok).
_STATUS_RANK = {
    RecognitionStatus.OK: 0,
    RecognitionStatus.NEEDS_REVIEW: 1,
    RecognitionStatus.FAILED: 2,
}


@dataclass
class PipelineDeps:
    """The built engines + settings the assembler needs (cached once on ``app.state``)."""

    layout: LayoutDetector  # configured model-path detector (Protocol)
    text: TextRecognizer
    formula: FormulaRecognizer
    settings: Settings
    pipeline_config: PipelineConfig
    asset_dir: Path


def assemble_page(rendered: RenderedPage, image: Image.Image, deps: PipelineDeps) -> PageResult:
    """Assemble a single page into a typed :class:`PageResult`. Frees the bitmap before return."""

    executor = ThreadPoolExecutor(
        max_workers=max(1, deps.settings.region_concurrency), thread_name_prefix="region"
    )
    working = image
    try:
        # 1. Preprocess (born-digital pages are clean -> skip unless flags are forced on).
        if rendered.kind != SourceKind.PDF_BORN_DIGITAL:
            working = preprocess(image, deps.pipeline_config.ingest.preprocess, rendered.kind)

        # 2. Layout: born-digital structural fast-path, else the configured detector.
        layout_result = _detect_layout(rendered, working, deps)

        # 3. Reading order (block level).
        ordered = order_regions(layout_result.regions, rendered.width, rendered.height)

        # 4. Per-region recognition (bounded, timed).
        contents: list[RegionContent] = []
        for region in ordered:
            content = _run_region(region, rendered, working, deps, executor)
            contents.append(content)

        # 5. Worst-of status roll-up.
        status = _rollup_status(c.status for c in contents)
        return PageResult(
            index=rendered.index,
            width=rendered.width,
            height=rendered.height,
            dpi=rendered.dpi,
            kind=rendered.kind,
            contents=contents,
            status=status,
        )
    finally:
        # 6. Free the bitmap(s). Close our preprocessed copy and the caller's input.
        executor.shutdown(wait=True)
        if working is not image:
            working.close()
        image.close()


def _detect_layout(rendered: RenderedPage, image: Image.Image, deps: PipelineDeps) -> LayoutResult:
    """Pick the born-digital structural detector or the configured model detector."""

    if rendered.kind == SourceKind.PDF_BORN_DIGITAL:
        return BornDigitalLayoutDetector().detect(image, rendered)
    return deps.layout.detect(image, rendered)


def _rollup_status(statuses: Iterable[RecognitionStatus]) -> RecognitionStatus:
    """Return the worst (highest-rank) status across the page's regions (ok when empty)."""

    worst = RecognitionStatus.OK
    for st in statuses:
        if _STATUS_RANK[st] > _STATUS_RANK[worst]:
            worst = st
    return worst


def _timed(
    executor: ThreadPoolExecutor,
    timeout_s: float,
    fn: Callable[[], _T],
) -> _T | None:
    """Run ``fn`` in the executor under ``timeout_s``; return None on timeout (region failed)."""

    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout:
        future.cancel()
        return None


def _run_region(
    region: Region,
    rendered: RenderedPage,
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> RegionContent:
    """Recognize one region per its type, honoring per-region timeout + honesty rules."""

    if region.type == RegionType.TABLE:
        return RegionContent(
            region=region,
            status=RecognitionStatus.NEEDS_REVIEW,
            detail="table recognition is M6",
        )
    if region.type == RegionType.HANDWRITING:
        return RegionContent(
            region=region,
            status=RecognitionStatus.NEEDS_REVIEW,
            detail="handwriting path is M6",
        )
    if region.type == RegionType.FIGURE:
        return _figure_region(region, rendered, image, deps)
    if region.type == RegionType.EQUATION_NUMBER:
        return _equation_number_region(region, rendered)
    if region.type in _MATH_TYPES:
        return _math_region(region, image, deps, executor)
    if region.type in _TEXT_ISH:
        return _text_region(region, rendered, image, deps, executor)
    # UNKNOWN / unsupported: honest needs_review, never a guess.
    return RegionContent(
        region=region,
        status=RecognitionStatus.NEEDS_REVIEW,
        detail=f"unsupported region type {region.type.value}",
    )


def _crop(image: Image.Image, bbox: BBox) -> Image.Image:
    """Crop a region bbox from the page image, clamped to the image bounds."""

    x0 = max(0, int(bbox.x0))
    y0 = max(0, int(bbox.y0))
    x1 = min(image.width, int(round(bbox.x1)))
    y1 = min(image.height, int(round(bbox.y1)))
    if x1 <= x0 or y1 <= y0:
        return image.crop((x0, y0, min(image.width, x0 + 1), min(image.height, y0 + 1)))
    return image.crop((x0, y0, x1, y1))


def _recognize_formula_latex(
    crop: Image.Image,
    is_display: bool,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> tuple[str, str | None, RecognitionStatus, float, ConfidenceKind, str, str | None]:
    """Run the reused pix2tex engine + validate/normalize + MathML on a math crop.

    Returns ``(latex, mathml, status, confidence, confidence_kind, engine_id, detail)``. A failed
    or unvalidatable result yields an honest ``needs_review``/``failed`` with empty/partial LaTeX —
    never a confident guess.
    """

    ctx = RegionContext(is_display=is_display, device=deps.settings.device, source="page")
    result = _timed(
        executor,
        deps.settings.region_timeout_s,
        lambda: deps.formula.recognize(crop.copy(), ctx),
    )
    if result is None:
        return (
            "",
            None,
            RecognitionStatus.FAILED,
            0.0,
            ConfidenceKind.UNAVAILABLE,
            deps.formula.id,
            "recognition timed out",
        )
    if result.status == RecognitionStatus.FAILED or not result.latex.strip():
        return (
            "",
            None,
            RecognitionStatus.FAILED,
            result.confidence,
            result.confidence_kind,
            result.engine_id,
            result.detail or "could not recognize",
        )

    normalized, validation = validate_and_normalize(result.latex)
    if validation == RecognitionStatus.FAILED:
        return (
            "",
            None,
            RecognitionStatus.FAILED,
            result.confidence,
            result.confidence_kind,
            result.engine_id,
            "latex failed validation",
        )
    mathml = latex_to_mathml(normalized)
    status = validation if validation != RecognitionStatus.OK else result.status
    return (
        normalized,
        mathml,
        status,
        result.confidence,
        result.confidence_kind,
        result.engine_id,
        result.detail,
    )


def _math_region(
    region: Region,
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> RegionContent:
    """DISPLAY_MATH / standalone INLINE_MATH -> pix2tex -> validate -> MathML (always from crop)."""

    crop = _crop(image, region.bbox)
    try:
        latex, mathml, status, conf, conf_kind, engine_id, detail = _recognize_formula_latex(
            crop, region.type == RegionType.DISPLAY_MATH, deps, executor
        )
    finally:
        crop.close()
    return RegionContent(
        region=region,
        latex=latex or None,
        mathml=mathml,
        status=status,
        confidence=conf,
        confidence_kind=conf_kind,
        engine_id=engine_id,
        detail=detail,
    )


def _equation_number_region(region: Region, rendered: RenderedPage) -> RegionContent:
    """EQUATION_NUMBER -> plain text extraction from the born-digital text layer (if available)."""

    text = _text_from_layer(region, rendered)
    return RegionContent(
        region=region,
        inlines=[InlineRun(kind=RunKind.TEXT, text=text)] if text else [],
        text=text or None,
        status=RecognitionStatus.OK,
        engine_id="born_digital" if text else "",
    )


def _figure_region(
    region: Region, rendered: RenderedPage, image: Image.Image, deps: PipelineDeps
) -> RegionContent:
    """FIGURE -> crop saved to the output asset dir; referenced in export (design §7.4)."""

    asset_name = f"fig_p{rendered.index}_{int(region.bbox.x0)}_{int(region.bbox.y0)}.png"
    try:
        deps.asset_dir.mkdir(parents=True, exist_ok=True)
        crop = _crop(image, region.bbox)
        try:
            crop.save(deps.asset_dir / asset_name)
        finally:
            crop.close()
        detail = asset_name
        status = RecognitionStatus.OK
    except OSError as exc:  # saving a figure must not fail the page
        logger.warning("could not save figure crop: %s", exc)
        detail = f"figure crop not saved: {exc}"
        status = RecognitionStatus.NEEDS_REVIEW
    return RegionContent(region=region, text=None, status=status, engine_id="figure", detail=detail)


def _text_region(
    region: Region,
    rendered: RenderedPage,
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> RegionContent:
    """Text-ish region -> ordered inline runs (born-digital text layer or OCR + inline math)."""

    if rendered.kind == SourceKind.PDF_BORN_DIGITAL and rendered.text_layer is not None:
        inlines = _born_digital_inlines(region, rendered, image, deps, executor)
    else:
        inlines = _ocr_inlines(region, image, deps, executor)

    plain = " ".join(r.text for r in inlines if r.kind == RunKind.TEXT and r.text).strip()
    status = _rollup_status(r.status for r in inlines) if inlines else RecognitionStatus.OK
    engine_id = next((r.engine_id for r in inlines if r.engine_id), "")
    return RegionContent(
        region=region,
        inlines=inlines,
        text=plain or None,
        status=status,
        engine_id=engine_id,
    )


def _text_from_layer(region: Region, rendered: RenderedPage) -> str:
    """Join the born-digital text-layer spans whose centers fall inside ``region.bbox``."""

    spans = rendered.text_layer or []
    inside = [s for s in spans if _span_in_bbox(s, region)]
    inside.sort(key=lambda s: (round((s.bbox[1] + s.bbox[3]) / 2.0, 1), s.bbox[0]))
    return "".join(s.text for s in inside).strip()


def _span_in_bbox(span: PdfTextSpan, region: Region) -> bool:
    cx = (span.bbox[0] + span.bbox[2]) / 2.0
    cy = (span.bbox[1] + span.bbox[3]) / 2.0
    b = region.bbox
    return b.x0 <= cx <= b.x1 and b.y0 <= cy <= b.y1


def _born_digital_inlines(
    region: Region,
    rendered: RenderedPage,
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> list[InlineRun]:
    """Split a born-digital block's spans into consecutive TEXT / inline-MATH runs (design §6.5)."""

    spans = sorted(
        (s for s in (rendered.text_layer or []) if _span_in_bbox(s, region)),
        key=lambda s: (round((s.bbox[1] + s.bbox[3]) / 2.0, 1), s.bbox[0]),
    )
    if not spans:
        return []

    runs: list[InlineRun] = []
    buffer: list[PdfTextSpan] = []
    buffer_math = False

    def flush() -> None:
        nonlocal buffer, buffer_math
        if not buffer:
            return
        if buffer_math:
            runs.append(_inline_math_run(buffer, image, deps, executor))
        else:
            text = "".join(s.text for s in buffer).strip()
            if text:
                runs.append(InlineRun(kind=RunKind.TEXT, text=text, engine_id="born_digital"))
        buffer = []

    for span in spans:
        is_math = span_is_mathish(span)
        if buffer and is_math != buffer_math:
            flush()
        buffer_math = is_math
        buffer.append(span)
    flush()
    return runs


def _inline_math_run(
    spans: list[PdfTextSpan],
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> InlineRun:
    """Recognize a maximal run of mathish spans via pix2tex on their union crop (design §6.5)."""

    x0 = min(s.bbox[0] for s in spans)
    y0 = min(s.bbox[1] for s in spans)
    x1 = max(s.bbox[2] for s in spans)
    y1 = max(s.bbox[3] for s in spans)
    crop = _crop(image, BBox(x0=x0, y0=y0, x1=x1, y1=y1))
    try:
        latex, mathml, status, conf, conf_kind, engine_id, detail = _recognize_formula_latex(
            crop, False, deps, executor
        )
    finally:
        crop.close()
    return InlineRun(
        kind=RunKind.MATH,
        latex=latex or None,
        mathml=mathml,
        status=status if status != RecognitionStatus.OK else RecognitionStatus.OK,
        confidence=conf,
        confidence_kind=conf_kind,
        engine_id=engine_id,
        detail=detail,
    )


def _ocr_inlines(
    region: Region,
    image: Image.Image,
    deps: PipelineDeps,
    executor: ThreadPoolExecutor,
) -> list[InlineRun]:
    """Scanned/model path: OCR the region crop into a single TEXT run (design §6.5)."""

    crop = _crop(image, region.bbox)
    ctx = RegionContext(is_display=False, device=deps.settings.device, source="page")
    try:
        result = _timed(
            executor,
            deps.settings.region_timeout_s,
            lambda: deps.text.recognize(crop.copy(), ctx),
        )
    finally:
        crop.close()

    if result is None:
        return [
            InlineRun(
                kind=RunKind.TEXT,
                text="",
                status=RecognitionStatus.FAILED,
                engine_id=deps.text.id,
                detail="recognition timed out",
            )
        ]
    if result.status == RecognitionStatus.FAILED:
        return [
            InlineRun(
                kind=RunKind.TEXT,
                text="",
                status=RecognitionStatus.FAILED,
                engine_id=result.engine_id,
                detail=result.detail or "could not recognize",
            )
        ]
    text = " ".join(line.text for line in result.lines).strip()
    confidence = (
        sum(line.confidence for line in result.lines) / len(result.lines) if result.lines else 0.0
    )
    return [
        InlineRun(
            kind=RunKind.TEXT,
            text=text,
            status=RecognitionStatus.OK,
            confidence=confidence,
            confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
            engine_id=result.engine_id,
        )
    ]
