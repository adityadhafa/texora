"""Shared test harness for the M4 job runner/manager (design §13).

Provides FAST STUB recognizers + a real :class:`PipelineDeps` so a job runs end-to-end over a REAL
synthetic PDF without loading any ML model. This is in-harness test wiring only — the production
recognition path stays real (honesty invariant). Stubs return explicit, non-fabricated results.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from texora_engine.ingest.base import RenderedPage
from texora_engine.layout.base import LayoutResult
from texora_engine.pipeline.assembler import PipelineDeps
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaResult,
    RecognitionStatus,
    RegionContext,
    TextResult,
)
from texora_engine.settings import Settings


class StubFormulaRecognizer:
    """A deterministic in-harness formula stub (never loads pix2tex)."""

    id = "stub-formula"
    model_ids: tuple[str, ...] = ()

    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult:
        return FormulaResult(
            latex="x = 1",
            confidence=0.99,
            confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
            status=RecognitionStatus.OK,
            engine_id=self.id,
        )


class StubTextRecognizer:
    """A deterministic in-harness text stub (never loads PP-OCR / Tesseract)."""

    id = "stub-text"
    model_ids: tuple[str, ...] = ()
    langs: tuple[str, ...] = ("en",)

    def recognize(self, image: Image.Image, ctx: RegionContext) -> TextResult:
        return TextResult(lines=[], status=RecognitionStatus.OK, engine_id=self.id)


class StubLayoutDetector:
    """Layout stub — never called for born-digital PDFs (the structural detector handles those)."""

    id = "stub-layout"
    model_ids: tuple[str, ...] = ()

    def detect(self, image: Image.Image, rendered: RenderedPage) -> LayoutResult:
        return LayoutResult(regions=[], engine_id=self.id)


def write_minimal_pdf(path: Path, n_pages: int) -> Path:
    """Write a minimal, valid, born-digital multi-page PDF with a text layer, no new dependency.

    Each page carries a short Helvetica text line so pypdfium2 extracts a text layer (the pages
    classify as born-digital and exercise the real structural layout path). This is a REAL PDF the
    runner streams page-by-page — not a mock. Used by the memory/semaphore/resume tests until the
    reportlab generator lands in task 4.7.
    """

    objects: list[bytes] = []

    def _obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based object number

    # Reserve: 1=catalog, 2=pages, then per-page [page, content]; font is the last object.
    font_num = 3 + 2 * n_pages
    page_nums: list[int] = []
    for i in range(n_pages):
        page_obj_num = 3 + 2 * i
        content_obj_num = page_obj_num + 1
        page_nums.append(page_obj_num)
        stream = (
            f"BT /F1 24 Tf 72 700 Td (Texora synthetic page {i} with math x = {i}) Tj ET"
        ).encode("ascii")
        content = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
            f"/Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        # Keep allocation order aligned with the reserved numbering.
        objects.append(page)
        objects.append(content)

    kids = " ".join(f"{n} 0 R" for n in page_nums)
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("ascii")
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    # Assemble in object-number order: 1 catalog, 2 pages, 3.. page/content pairs, font last.
    ordered: list[bytes] = [catalog, pages, *objects, font]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for num, body in enumerate(ordered, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    count = len(ordered) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("ascii")
    path.write_bytes(bytes(out))
    return path


def make_stub_deps(settings: Settings, asset_dir: Path | None = None) -> PipelineDeps:
    """Build a real PipelineDeps wired to the fast stubs (no model load)."""

    cfg = load_pipeline_config()
    return PipelineDeps(
        layout=StubLayoutDetector(),  # type: ignore[arg-type]
        text=StubTextRecognizer(),  # type: ignore[arg-type]
        formula=StubFormulaRecognizer(),  # type: ignore[arg-type]
        settings=settings,
        pipeline_config=cfg,
        asset_dir=asset_dir or Path(settings.figure_asset_dir),
    )
