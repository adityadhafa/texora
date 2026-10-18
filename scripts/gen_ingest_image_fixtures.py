#!/usr/bin/env python3
"""Reproducible generator for FEAT-002's raster ingest fixtures.

Writes four images (plus one JSON metadata companion) into
``engine/tests/fixtures/``, all synthesized with Pillow's built-in bitmap font -- no
third-party assets, no copyrighted scans, fully regenerable and license-clean:

  - ``scanned_page.png``   -- a rasterized, scanned-style page (no embedded text layer),
                              used to exercise the model layout path + born-digital negative.
  - ``text_en.png``        -- a cropped English text line.
  - ``text_id.png``        -- a cropped Indonesian line with ID diacritics.
  - ``skewed_scan.png``    -- a text block rotated by a known angle for the deskew test,
                              with ``skewed_scan.json`` recording that angle.
  - ``multipage.tiff``     -- a two-frame TIFF for the multi-page image-loader test.
  - ``sample.heic``        -- a small HEIC/HEIF image for the pillow-heif loader test.
  - ``sample.webp`` / ``sample.bmp`` / ``sample.jpg`` -- per-format loader coverage.

Run from the repo root (or anywhere):

    python scripts/gen_ingest_image_fixtures.py

Deterministic: identical bytes each run (fixed seed, fixed layout, no timestamps).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pillow_heif
from PIL import Image, ImageDraw, ImageFont

pillow_heif.register_heif_opener()

# Known skew baked into skewed_scan.png (degrees, counter-clockwise positive).
SKEW_ANGLE_DEG = 7.0

_FONT = ImageFont.load_default()


def _text_block(
    lines: list[str],
    *,
    width: int,
    height: int,
    origin: tuple[int, int] = (12, 12),
    line_step: int = 16,
) -> Image.Image:
    """Render dark text lines on a white background (a clean synthetic 'scan')."""

    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    x, y = origin
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_step), line, fill=0, font=_FONT)
    return img


def build_scanned_page() -> Image.Image:
    """A full-page scanned-style image: several text lines, slight uniform gray noise."""

    rng = np.random.default_rng(1234)
    width, height = 850, 1100  # ~Letter at 100 dpi
    img = _text_block(
        [
            "Scanned Document Sample",
            "",
            "This page is rasterized with no embedded text layer, so the",
            "ingest detector must classify it as scanned rather than",
            "born-digital. The body simulates a photocopied article with",
            "multiple paragraphs of ordinary prose for the layout model.",
            "",
            "A second paragraph continues here with additional lines so",
            "the connected-component glyph-height estimate has real data.",
        ],
        width=width,
        height=height,
        origin=(40, 40),
        line_step=22,
    )
    arr = np.asarray(img, dtype=np.int16)
    noise = rng.integers(-8, 9, size=arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L").convert("RGB")


def build_text_en() -> Image.Image:
    return _text_block(
        ["The quick brown fox jumps over the lazy dog."],
        width=360,
        height=40,
    ).convert("RGB")


def build_text_id() -> Image.Image:
    # Indonesian line; ID uses the Latin script (diacritics are rare but kept here for coverage).
    return _text_block(
        ["Rubah cokelat melompati anjing yang malas."],
        width=360,
        height=40,
    ).convert("RGB")


def build_skewed_scan() -> Image.Image:
    """A text block rotated by SKEW_ANGLE_DEG, on a white canvas (expand to keep all pixels)."""

    block = _text_block(
        [
            "Deskew fixture line one.",
            "Deskew fixture line two.",
            "Deskew fixture line three.",
        ],
        width=320,
        height=80,
        origin=(10, 10),
        line_step=22,
    )
    # PIL rotate: positive angle is counter-clockwise; fillcolor white keeps the background clean.
    rotated = block.rotate(
        SKEW_ANGLE_DEG, expand=True, fillcolor=255, resample=Image.Resampling.BICUBIC
    )
    return rotated.convert("RGB")


def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "engine" / "tests" / "fixtures"


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else fixtures_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    build_scanned_page().save(out_dir / "scanned_page.png")
    build_text_en().save(out_dir / "text_en.png")
    build_text_id().save(out_dir / "text_id.png")
    build_skewed_scan().save(out_dir / "skewed_scan.png")
    (out_dir / "skewed_scan.json").write_text(
        json.dumps({"skew_angle_deg": SKEW_ANGLE_DEG}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Per-format coverage, all derived from the same clean synthetic line.
    base = build_text_en()
    base.save(out_dir / "sample.jpg", quality=95)
    base.save(out_dir / "sample.webp", lossless=True)
    base.save(out_dir / "sample.bmp")
    base.save(out_dir / "sample.heic")

    # Two-frame multi-page TIFF (EN then ID line).
    frame2 = build_text_id()
    base.save(out_dir / "multipage.tiff", save_all=True, append_images=[frame2])

    written = [
        "scanned_page.png",
        "text_en.png",
        "text_id.png",
        "skewed_scan.png",
        "sample.jpg",
        "sample.webp",
        "sample.bmp",
        "sample.heic",
        "multipage.tiff",
    ]
    for name in written:
        p = out_dir / name
        print(f"wrote {p} ({p.stat().st_size} bytes)")
    print(f"wrote {out_dir / 'skewed_scan.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
