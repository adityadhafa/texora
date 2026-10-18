"""Tests for the toggleable preprocessing pipeline (ingest/preprocess.py).

Each toggle set false yields byte-identical output (a disabled step is a strict no-op); the
deskew step enabled on the known-skew fixture reduces the measured skew below threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from texora_engine.ingest import SourceKind, preprocess
from texora_engine.ingest.preprocess import estimate_skew_deg
from texora_engine.pipeline_config import PreprocessSettings

_DESKEW_MIN_DEG = 0.3


def _load_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def test_all_disabled_is_byte_identical_noop(fixtures_dir: Path) -> None:
    img = _load_rgb(fixtures_dir / "skewed_scan.png")
    all_off = PreprocessSettings(
        deskew=False, denoise=False, binarize=False, perspective=False, auto_crop=False
    )
    out = preprocess(img, all_off, SourceKind.IMAGE)
    # Same object (strict no-op) and identical pixels.
    assert out is img
    assert np.array_equal(np.asarray(img), np.asarray(out))


@pytest.mark.parametrize("step", ["deskew", "perspective"])
def test_noop_step_on_clean_image_preserves_pixels(fixtures_dir: Path, step: str) -> None:
    """A step that has nothing to do (upright image, no page quad) leaves pixels unchanged.

    This proves a single enabled flag does not implicitly run the other four steps: with
    only ``step`` on, the clean upright fixture comes back identical.
    """

    img = _load_rgb(fixtures_dir / "text_en.png")  # clean, upright
    before = np.asarray(img).copy()
    flags = {
        "deskew": False,
        "denoise": False,
        "binarize": False,
        "perspective": False,
        "auto_crop": False,
    }
    flags[step] = True
    cfg = PreprocessSettings(**flags)
    out = preprocess(img, cfg, SourceKind.IMAGE)
    assert np.array_equal(before, np.asarray(out))


def test_deskew_reduces_measured_skew(fixtures_dir: Path) -> None:
    img = _load_rgb(fixtures_dir / "skewed_scan.png")
    meta = json.loads((fixtures_dir / "skewed_scan.json").read_text(encoding="utf-8"))
    known = float(meta["skew_angle_deg"])

    before = estimate_skew_deg(img)
    # The estimator should see a skew comparable in magnitude to the baked-in angle.
    assert abs(before) > 1.0
    assert abs(abs(before) - known) < 3.0

    cfg = PreprocessSettings(
        deskew=True, denoise=False, binarize=False, perspective=False, auto_crop=False
    )
    out = preprocess(img, cfg, SourceKind.IMAGE)
    after = estimate_skew_deg(out)
    assert abs(after) < abs(before)
    assert abs(after) < _DESKEW_MIN_DEG + 0.5


def test_denoise_skipped_for_born_digital(fixtures_dir: Path) -> None:
    """Denoise is scanned-only: a born-digital page is returned unchanged even if the flag is on."""

    img = _load_rgb(fixtures_dir / "text_en.png")
    cfg = PreprocessSettings(
        deskew=False, denoise=True, binarize=False, perspective=False, auto_crop=False
    )
    out = preprocess(img, cfg, SourceKind.PDF_BORN_DIGITAL)
    assert out is img


def test_binarize_changes_pixels_when_enabled(fixtures_dir: Path) -> None:
    img = _load_rgb(fixtures_dir / "scanned_page.png")
    cfg = PreprocessSettings(
        deskew=False, denoise=False, binarize=True, perspective=False, auto_crop=False
    )
    out = preprocess(img, cfg, SourceKind.IMAGE)
    arr = np.asarray(out)
    # Binary output: every pixel is either 0 or 255.
    assert set(np.unique(arr)).issubset({0, 255})
