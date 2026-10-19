#!/usr/bin/env python3
"""Synthetic N-page PDF generator for the M4 5,000-page proof (design §12).

Emits a deterministic (seed-stable) multi-page PDF with mixed text + simple math-like content per
page via ``reportlab`` (BSD-3-Clause, a **test/CI-only** dependency — never frozen into the shipped
sidecar). Also emits a "hostile" variant: one page carries a pathological oversize raster so the
task-4.5 failure-isolation path can be exercised against a real file.

CLI::

    python -m scripts.make_synthetic_pdf --pages 500 --out syn.pdf --seed 7
    python -m scripts.make_synthetic_pdf --pages 50 --out hostile.pdf --hostile

The PDF is a REAL document (not a mock); the proof harness streams it page-by-page.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

_FONT = "Helvetica"
_MATHISH = ["E = mc^2", "a^2 + b^2 = c^2", "f(x) = sum x_i / n", "int_0^1 x dx = 1/2"]


def _page_text(c: canvas.Canvas, index: int, rng: random.Random) -> None:
    """Draw a page of mixed text + math-like lines (deterministic for a given rng state)."""

    width, height = letter
    c.setFont(_FONT, 16)
    c.drawString(1 * inch, height - 1 * inch, f"Texora synthetic document — page {index}")
    c.setFont(_FONT, 11)
    y = height - 1.5 * inch
    for line in range(28):
        if line % 5 == 0:
            text = f"Equation: {rng.choice(_MATHISH)}"
        else:
            words = [f"w{rng.randint(0, 9999)}" for _ in range(rng.randint(6, 12))]
            text = "Lorem " + " ".join(words)
        c.drawString(1 * inch, y, text[:110])
        y -= 0.3 * inch
        if y < 1 * inch:
            break


def _hostile_page(c: canvas.Canvas) -> None:
    """A pathological page: a huge solid raster filling an oversized area (resource-guard bait)."""

    width, height = letter
    c.setFillColorRGB(0.1, 0.1, 0.1)
    # A single large filled rectangle; combined with a high render DPI this blows past the pixel
    # bound, so the runner's resource guard fails just this page.
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(_FONT, 8)
    c.drawString(0.5 * inch, height / 2, "hostile page: oversize raster")


def build_synthetic_pdf(out: Path, pages: int, *, seed: int = 0, hostile: bool = False) -> Path:
    """Write an ``pages``-page synthetic PDF to ``out`` (deterministic given ``seed``)."""

    out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    c = canvas.Canvas(str(out), pagesize=letter)
    for index in range(pages):
        if hostile and index == pages // 2:
            _hostile_page(c)
        else:
            _page_text(c, index, rng)
        c.showPage()
    c.save()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic multi-page PDF.")
    parser.add_argument("--pages", type=int, required=True, help="Number of pages to emit.")
    parser.add_argument("--out", type=Path, required=True, help="Output PDF path.")
    parser.add_argument("--seed", type=int, default=0, help="Deterministic content seed.")
    parser.add_argument(
        "--hostile", action="store_true", help="Insert one pathological oversize page."
    )
    args = parser.parse_args(argv)
    path = build_synthetic_pdf(args.out, args.pages, seed=args.seed, hostile=args.hostile)
    print(f"wrote {path} ({path.stat().st_size} bytes, {args.pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
