"""Tests for born-digital vs scanned classification (ingest/detect.py).

Positive on the generated born-digital math PDF, negative on the generated image-only
``scanned.pdf`` (a text-layer-free PDF -- the detector's negative fixture).
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from texora_engine.ingest import SourceKind, classify_pdf_page
from texora_engine.pipeline_config import IngestConfig


def _classify(path: Path, cfg: IngestConfig) -> SourceKind:
    with pdfium.PdfDocument(str(path)) as doc:
        page = doc[0]
        try:
            width_pt, height_pt = page.get_size()
            return classify_pdf_page(page, width_pt, height_pt, cfg)
        finally:
            page.close()


def test_born_digital_pdf_is_positive(fixtures_dir: Path) -> None:
    kind = _classify(fixtures_dir / "born_digital_math.pdf", IngestConfig())
    assert kind == SourceKind.PDF_BORN_DIGITAL


def test_image_only_pdf_is_scanned(fixtures_dir: Path) -> None:
    kind = _classify(fixtures_dir / "scanned.pdf", IngestConfig())
    assert kind == SourceKind.PDF_SCANNED


def test_char_threshold_gates_classification(fixtures_dir: Path) -> None:
    """Raising the char threshold above the fixture's count flips it to scanned."""

    strict = IngestConfig(born_digital_char_threshold=100_000)
    kind = _classify(fixtures_dir / "born_digital_math.pdf", strict)
    assert kind == SourceKind.PDF_SCANNED


def test_coverage_threshold_gates_classification(fixtures_dir: Path) -> None:
    """Requiring near-full page coverage flips the sparse fixture to scanned."""

    strict = IngestConfig(born_digital_coverage=0.99)
    kind = _classify(fixtures_dir / "born_digital_math.pdf", strict)
    assert kind == SourceKind.PDF_SCANNED
