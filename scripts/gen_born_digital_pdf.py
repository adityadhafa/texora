#!/usr/bin/env python3
"""Reproducible generator for the ``born_digital_math.pdf`` ingest fixture.

Writes a minimal, license-clean born-digital PDF by hand (standard Type1 fonts only, no
third-party PDF toolkit), so the fixture is fully regenerable and carries no copyleft or
redistribution encumbrance. The page contains a title, a two-column body with one inline
formula and one numbered display equation -- exactly the structure FEAT-002's ingest and
detection tests exercise.

Run from the repo root (or anywhere):

    python scripts/gen_born_digital_pdf.py

By default it writes ``engine/tests/fixtures/born_digital_math.pdf`` relative to the repo
root. Pass an explicit output path as the first argument to override. It also writes a
sibling ``scanned.pdf`` (an image-only, text-layer-free PDF) used as the born-digital
detector's negative fixture.

The generator is deterministic: identical bytes every run (no timestamps, no random ids).
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

# US Letter media box, in PDF points (1/72 inch), origin bottom-left.
PAGE_WIDTH_PT = 612.0
PAGE_HEIGHT_PT = 792.0


def _escape(text: str) -> str:
    """Escape the three characters that are special inside a PDF literal string."""

    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_op(x: float, y: float, size: float, text: str, font: str = "F1") -> str:
    """One positioned show-text operator (origin bottom-left, PDF points)."""

    return f"BT /{font} {size:g} Tf {x:g} {y:g} Td ({_escape(text)}) Tj ET\n"


def build_content_stream() -> bytes:
    """Build the page content stream: title + two columns + numbered display equation.

    Layout (points, origin bottom-left):
      - Title centred near the top in a larger font (F2 = Times-Bold).
      - Left column: a paragraph with one inline formula ``E = mc^2``.
      - Right column: a second paragraph.
      - A centred numbered display equation with its ``(1)`` number at the right margin.
    """

    ops: list[str] = []

    # Title (Times-Bold, 18 pt).
    ops.append(_text_op(170, 740, 18, "Energy and Mass Equivalence", font="F2"))

    # Left column paragraph (Helvetica, 11 pt) with an inline formula fragment.
    left_x = 72
    ops.append(_text_op(left_x, 700, 11, "In special relativity the energy of a", font="F1"))
    ops.append(_text_op(left_x, 684, 11, "body at rest is given by the famous", font="F1"))
    # The inline formula E = mc^2 rendered with an italic math font (Times-Italic).
    ops.append(_text_op(left_x, 668, 11, "relation ", font="F1"))
    ops.append(_text_op(left_x + 42, 668, 11, "E = mc2", font="F3"))
    ops.append(_text_op(left_x + 80, 668, 11, " which binds mass", font="F1"))
    ops.append(_text_op(left_x, 652, 11, "and energy into a single quantity.", font="F1"))

    # Right column paragraph (Helvetica, 11 pt).
    right_x = 320
    ops.append(_text_op(right_x, 700, 11, "The constant c is the speed of", font="F1"))
    ops.append(_text_op(right_x, 684, 11, "light in vacuum. Because c is", font="F1"))
    ops.append(_text_op(right_x, 668, 11, "large, a small mass maps to a", font="F1"))
    ops.append(_text_op(right_x, 652, 11, "very large rest energy.", font="F1"))

    # Numbered display equation (centred, Times-Italic) with a right-margin number. Drawn at a
    # large uniform font on a single baseline so the rasterised crop fed to the formula recognizer
    # has clear, well-separated glyphs (a tiny glyph image is a poor formula input — see
    # docs/m3-verification.md, R-QA-2). Uniform glyph heights keep the born-digital line clusterer
    # from splitting the equation into stray regions.
    ops.append(_text_op(250, 560, 24, "E = mc2", font="F3"))
    ops.append(_text_op(540, 566, 11, "(1)", font="F1"))

    return "".join(ops).encode("latin-1")


def build_pdf() -> bytes:
    """Assemble a complete, deterministic PDF document from the content stream."""

    content = build_content_stream()

    # Object bodies, in order. Object 0 is the free head of the xref table.
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            + f"/MediaBox [0 0 {PAGE_WIDTH_PT:g} {PAGE_HEIGHT_PT:g}] ".encode("latin-1")
            + b"/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> >> "
            + b"/Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode("latin-1") + b" >>\nstream\n" + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Italic >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"

    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\n".encode("latin-1")
    out += f"startxref\n{xref_offset}\n%%EOF".encode("latin-1")
    return bytes(out)


def build_scanned_pdf() -> bytes:
    """A deterministic image-only PDF with NO text layer (the detector negative fixture).

    A single grayscale raster (a simple gradient with a dark bar) is embedded as an image
    XObject and painted to fill the page. Because there are no text-showing operators, pdfium
    extracts zero characters, so :func:`classify_pdf_page` returns ``PDF_SCANNED``.
    """

    # Tiny deterministic grayscale raster (16x16): a mid-gray field with a darker band.
    img_w, img_h = 16, 16
    raw = bytearray()
    for y in range(img_h):
        for _ in range(img_w):
            raw.append(40 if 6 <= y <= 9 else 200)
    pixels = zlib.compress(bytes(raw), 9)

    # Paint the image XObject scaled to the full MediaBox via the CTM.
    content = (
        f"q {PAGE_WIDTH_PT:g} 0 0 {PAGE_HEIGHT_PT:g} 0 0 cm /Im0 Do Q".encode("latin-1")
    )

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            + f"/MediaBox [0 0 {PAGE_WIDTH_PT:g} {PAGE_HEIGHT_PT:g}] ".encode("latin-1")
            + b"/Resources << /XObject << /Im0 5 0 R >> >> "
            + b"/Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode("latin-1") + b" >>\nstream\n" + content
        + b"\nendstream",
        (
            b"<< /Type /XObject /Subtype /Image "
            + f"/Width {img_w} /Height {img_h} ".encode("latin-1")
            + b"/ColorSpace /DeviceGray /BitsPerComponent 8 "
            + b"/Filter /FlateDecode /Length " + str(len(pixels)).encode("latin-1")
            + b" >>\nstream\n" + pixels + b"\nendstream"
        ),
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"

    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\n".encode("latin-1")
    out += f"startxref\n{xref_offset}\n%%EOF".encode("latin-1")
    return bytes(out)


def default_output_path() -> Path:
    """``engine/tests/fixtures/born_digital_math.pdf`` resolved from this script's location."""

    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "engine" / "tests" / "fixtures" / "born_digital_math.pdf"


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else default_output_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_pdf())
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")

    scanned_path = out_path.parent / "scanned.pdf"
    scanned_path.write_bytes(build_scanned_pdf())
    print(f"wrote {scanned_path} ({scanned_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
