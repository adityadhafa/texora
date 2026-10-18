"""Page assembler tests (task 3.6).

Two layers:
1. **Structure tests** on the real ``born_digital_math.pdf`` fixture. Text comes from the pdfium
   text layer directly (no OCR), so these run without any downloaded weights; a tiny in-test
   *formula* double stands in for pix2tex to exercise the math-crop path and the TABLE/HANDWRITING
   needs_review + status roll-up branches deterministically. This double is test scaffolding for the
   ORCHESTRATION, not a mocked OCR result on a production path.
2. **Model-gated integration** (``@pytest.mark.model``) running the REAL pix2tex + text engines on
   the fixture; skip-with-reason when weights are absent (never mocked).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from texora_engine.ingest.base import SourceKind
from texora_engine.ingest.pdf import iter_pdf_pages
from texora_engine.layout.base import LayoutResult, Region, RegionType
from texora_engine.pipeline import PipelineDeps, assemble_page
from texora_engine.pipeline.page_result import RunKind
from texora_engine.pipeline_config import IngestConfig, load_pipeline_config
from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaResult,
    RecognitionStatus,
    RegionContext,
    TextResult,
)
from texora_engine.settings import Settings

from tests.conftest import prefetched_models_dir, prefetched_text_models_dir

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "born_digital_math.pdf"


class _StubFormula:
    """A trivial FormulaRecognizer double returning a fixed, valid LaTeX for the math path."""

    id = "stub_formula"
    model_ids = ("pix2tex",)

    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult:
        return FormulaResult(
            latex="E = mc^2",
            confidence=0.0,
            confidence_kind=ConfidenceKind.UNAVAILABLE,
            status=RecognitionStatus.OK,
            engine_id=self.id,
        )


class _StubText:
    """A trivial TextRecognizer double (unused on the born-digital text-layer path)."""

    id = "stub_text"
    model_ids: tuple[str, ...] = ()
    langs = ("en", "id")

    def recognize(self, image: Image.Image, ctx: RegionContext) -> TextResult:
        return TextResult(lines=[], status=RecognitionStatus.OK, engine_id=self.id)


class _StubLayout:
    """A layout double used only to inject TABLE/HANDWRITING regions for the branch test."""

    id = "stub_layout"
    model_ids: tuple[str, ...] = ()

    def __init__(self, regions: list[Region]) -> None:
        self._regions = regions

    def detect(self, image: Image.Image, page: object) -> LayoutResult:
        return LayoutResult(regions=self._regions, engine_id=self.id)


def _deps(tmp_path: Path, layout: object | None = None) -> PipelineDeps:
    settings = Settings(models_dir=tmp_path / "models", figure_asset_dir=tmp_path / "assets")
    return PipelineDeps(
        layout=layout or _StubLayout([]),
        text=_StubText(),
        formula=_StubFormula(),
        settings=settings,
        pipeline_config=load_pipeline_config(),
        asset_dir=tmp_path / "assets",
    )


def _first_page() -> tuple[object, Image.Image]:
    return next(iter_pdf_pages(_FIXTURE, IngestConfig()))


def test_structure_on_born_digital_fixture(tmp_path: Path) -> None:
    rendered, image = _first_page()
    assert rendered.kind == SourceKind.PDF_BORN_DIGITAL
    page = assemble_page(rendered, image, _deps(tmp_path))

    types = [c.region.type for c in page.contents]
    assert RegionType.TITLE in types
    assert RegionType.PARAGRAPH in types
    # reading_order is a non-decreasing sequence of unique ints (block-level order).
    orders = [c.region.reading_order for c in page.contents]
    assert orders == sorted(orders)

    # At least one display-math region carries validated LaTeX from the (stub) formula engine.
    math = [c for c in page.contents if c.region.type == RegionType.DISPLAY_MATH]
    assert math and math[0].latex and math[0].mathml

    # The page's inline math is re-recognized via the (stub) formula engine: either as a
    # standalone INLINE_MATH region carrying latex, or as a MATH run inside a text block's
    # ordered inlines (design §6.5 / §7.4 — both are valid representations).
    standalone_inline = [
        c for c in page.contents if c.region.type == RegionType.INLINE_MATH and c.latex
    ]
    inline_runs = [
        run for c in page.contents for run in c.inlines if run.kind == RunKind.MATH and run.latex
    ]
    assert standalone_inline or inline_runs, "expected inline math recognized on the page"


def test_born_digital_span_order_is_not_scrambled() -> None:
    """Regression: per-character born-digital spans order left-to-right within a line band.

    pdfium emits per-glyph spans whose bbox heights vary (ascenders/descenders), so their
    y-centers differ on the SAME line. Ordering by a rounded y-center then x scrambled the line
    (title rendered as "iEMEldnrnnaaaesseceuvqgy"); line-banding then x-order yields the real
    text. This guards the headline PDF->Markdown prose against silent re-scrambling.
    """

    from texora_engine.pipeline.assembler import _order_spans

    rendered, image = _first_page()
    try:
        spans = rendered.text_layer or []
        # The title band sits near the top of the page (well above the body columns).
        title_band = [s for s in spans if s.bbox[1] < 210.0]
        ordered = "".join(s.text for s in _order_spans(title_band))
        assert ordered == "EnergyandMassEquivalence"
    finally:
        image.close()


def test_born_digital_prose_is_word_spaced(tmp_path: Path) -> None:
    """Regression: born-digital prose reads as properly spaced words, not jammed glyphs.

    pdfium's text layer is per-character and drops space glyphs, so a naive join yields
    "Inspecialrelativitytheenergyofa". Gap-based spacing (``join_spans_with_spaces``) must restore
    word boundaries: the title and the opening left-column sentence read correctly.
    """

    rendered, image = _first_page()
    page = assemble_page(rendered, image, _deps(tmp_path))

    texts = [c.text for c in page.contents if c.text]
    assert "Energy and Mass Equivalence" in texts
    # The opening left-column sentence reads with spaces (no inter-column bleed, no jammed words).
    assert any("In special relativity the energy of a" == t for t in texts), texts


def test_born_digital_columns_read_left_then_right(tmp_path: Path) -> None:
    """Regression: the two-column body reads the LEFT column fully, then the RIGHT column.

    The old path merged left+right column text on each y-band into one region, so reading order
    interleaved the columns ("...energy of a The constant c is the speed of"). Column-aware line
    splitting + widest-gap XY-cut must now yield each column as a contiguous run.
    """

    rendered, image = _first_page()
    page = assemble_page(rendered, image, _deps(tmp_path))

    texts = [c.text for c in page.contents if c.text]
    joined = "\n".join(texts)
    # Left-column fragments appear, in order, before any right-column fragment.
    left_last = texts.index(next(t for t in texts if "single quantity" in t))
    right_first = texts.index(next(t for t in texts if "constant c is the speed" in t))
    assert left_last < right_first, joined
    # And the left column is not interleaved with the right on a single line.
    assert not any(
        "energy of a" in t and "constant c" in t for t in texts
    ), f"columns interleaved on one line: {joined}"


def test_table_and_handwriting_are_needs_review(tmp_path: Path) -> None:
    rendered, image = _first_page()
    regions = [
        Region(
            type=RegionType.TABLE, bbox={"x0": 10, "y0": 10, "x1": 100, "y1": 100}, confidence=0.9
        ),
        Region(
            type=RegionType.HANDWRITING,
            bbox={"x0": 10, "y0": 120, "x1": 100, "y1": 200},
            confidence=0.9,
        ),
    ]
    # Force the model path by pretending the page is scanned so the stub layout is used.
    rendered = rendered.model_copy(update={"kind": SourceKind.PDF_SCANNED, "text_layer": None})
    page = assemble_page(rendered, image, _deps(tmp_path, layout=_StubLayout(regions)))

    by_type = {c.region.type: c for c in page.contents}
    assert by_type[RegionType.TABLE].status == RecognitionStatus.NEEDS_REVIEW
    assert by_type[RegionType.TABLE].detail and "M6" in by_type[RegionType.TABLE].detail
    assert by_type[RegionType.HANDWRITING].status == RecognitionStatus.NEEDS_REVIEW
    assert by_type[RegionType.HANDWRITING].detail and "M6" in by_type[RegionType.HANDWRITING].detail
    # Worst-of roll-up: needs_review regions -> page needs_review.
    assert page.status == RecognitionStatus.NEEDS_REVIEW


@pytest.mark.model
def test_real_engine_integration(tmp_path: Path) -> None:
    if prefetched_models_dir() is None:
        pytest.skip("pix2tex weights absent; run model prefetch")
    from texora_engine.db import init_db
    from texora_engine.models.store import ModelStore
    from texora_engine.recognizers.factory import build_formula_recognizer
    from texora_engine.recognizers.text_factory import build_text_recognizer

    models_dir = prefetched_models_dir()
    assert models_dir is not None
    settings = Settings(models_dir=models_dir, figure_asset_dir=tmp_path / "assets")
    conn = init_db(tmp_path / "texora.db")
    store = ModelStore(conn, settings)

    formula = build_formula_recognizer(settings, store)
    # Text engine: PP-OCRv5 when prefetched, else the Tesseract fallback / skip handled by factory.
    if prefetched_text_models_dir() is None:
        pytest.skip("PP-OCRv5 text weights absent; real-text integration is model-gated")
    text = build_text_recognizer(settings, store)

    deps = PipelineDeps(
        layout=_StubLayout([]),
        text=text,
        formula=formula,
        settings=settings,
        pipeline_config=load_pipeline_config(),
        asset_dir=tmp_path / "assets",
    )
    rendered, image = _first_page()
    page = assemble_page(rendered, image, deps)
    types = [c.region.type for c in page.contents]
    assert RegionType.DISPLAY_MATH in types
    display = [c for c in page.contents if c.region.type == RegionType.DISPLAY_MATH][0]
    assert display.latex  # the REAL pix2tex produced LaTeX for the display equation
