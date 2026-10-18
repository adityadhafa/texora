"""Tests for the Pillow + pillow-heif image loaders (ingest/images.py).

Loads every supported format (incl. multi-page TIFF and HEIC) and asserts the
decompression-bomb guard rejects an over-bounds image with the typed IngestError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from texora_engine.ingest import IngestError, SourceKind, load_image_pages
from texora_engine.settings import Settings


@pytest.fixture()
def settings() -> Settings:
    return Settings(token="t")


@pytest.mark.parametrize(
    "name",
    ["text_en.png", "sample.jpg", "sample.webp", "sample.bmp", "scanned_page.png"],
)
def test_loads_single_frame_formats(fixtures_dir: Path, settings: Settings, name: str) -> None:
    pages = load_image_pages(fixtures_dir / name, settings)
    try:
        assert len(pages) == 1
        rendered, image = pages[0]
        assert rendered.kind == SourceKind.IMAGE
        assert rendered.text_layer is None
        assert rendered.index == 0
        assert image.mode == "RGB"
        assert (image.width, image.height) == (rendered.width, rendered.height)
    finally:
        for _, img in pages:
            img.close()


def test_loads_heic(fixtures_dir: Path, settings: Settings) -> None:
    pages = load_image_pages(fixtures_dir / "sample.heic", settings)
    try:
        assert len(pages) == 1
        rendered, image = pages[0]
        assert rendered.kind == SourceKind.IMAGE
        assert image.mode == "RGB"
    finally:
        for _, img in pages:
            img.close()


def test_loads_multipage_tiff(fixtures_dir: Path, settings: Settings) -> None:
    pages = load_image_pages(fixtures_dir / "multipage.tiff", settings)
    try:
        assert len(pages) == 2
        assert [p[0].index for p in pages] == [0, 1]
        assert all(p[0].kind == SourceKind.IMAGE for p in pages)
        assert all(img.mode == "RGB" for _, img in pages)
    finally:
        for _, img in pages:
            img.close()


def test_over_bounds_image_raises_typed_guard(
    fixtures_dir: Path, settings: Settings, tmp_path: Path
) -> None:
    """A real image exceeding the pixel-area bound must raise IngestError, never crash."""

    big = tmp_path / "big.png"
    Image.new("RGB", (200, 200), color=(255, 255, 255)).save(big)

    tight = Settings(token="t", max_snip_pixels=100, max_snip_edge=10_000)
    with pytest.raises(IngestError, match="too large"):
        load_image_pages(big, tight)


def test_over_bounds_edge_raises_typed_guard(settings: Settings, tmp_path: Path) -> None:
    big = tmp_path / "wide.png"
    Image.new("RGB", (300, 10), color=(0, 0, 0)).save(big)

    tight = Settings(token="t", max_snip_pixels=10_000_000, max_snip_edge=100)
    with pytest.raises(IngestError, match="too large"):
        load_image_pages(big, tight)


def test_corrupt_file_raises_typed_guard(settings: Settings, tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a real image")
    with pytest.raises(IngestError, match="could not decode"):
        load_image_pages(bad, settings)
