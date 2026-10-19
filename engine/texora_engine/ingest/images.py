"""Pillow + pillow-heif image loaders for every supported standalone-image format.

Handles PNG/JPG/JPEG/WEBP/BMP via Pillow, multi-page TIFF via ``ImageSequence`` (one
:class:`RenderedPage` per frame), and HEIC/HEIF via pillow-heif. Every decoded image is run
through the same decompression-bomb guards the M2 snip path uses (``Image.MAX_IMAGE_PIXELS``
plus explicit area/edge/byte bounds from settings), so a hostile or malformed image raises a
typed :class:`IngestError` the API maps to 422 -- it never crashes a multi-page/document run.

Loaded images carry ``kind=IMAGE`` and no text layer; born-digital detection applies only to
PDFs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pillow_heif
from PIL import Image, ImageSequence, UnidentifiedImageError

from texora_engine.ingest.base import IngestError, RenderedPage, SourceKind
from texora_engine.logging_config import get_logger
from texora_engine.settings import Settings

logger = get_logger("ingest.images")

# Register the HEIF opener exactly once at import so Image.open handles .heic/.heif.
pillow_heif.register_heif_opener()


class ImageBounds:
    """Decode guards sourced from settings (reuses the M2 snip-guard values)."""

    def __init__(self, settings: Settings) -> None:
        self.max_pixels = settings.max_snip_pixels
        self.max_edge = settings.max_snip_edge
        self.max_bytes = settings.max_snip_bytes


def _check_file_size(path: Path, bounds: ImageBounds) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IngestError(f"could not stat image {path!s}: {exc}") from exc
    if size > bounds.max_bytes:
        raise IngestError(
            f"image file too large: {size} bytes exceeds {bounds.max_bytes} byte limit"
        )


def _check_dimensions(image: Image.Image, bounds: ImageBounds) -> None:
    width, height = image.size
    if width * height > bounds.max_pixels or max(width, height) > bounds.max_edge:
        raise IngestError(
            f"image too large: {width}x{height} exceeds {bounds.max_pixels} px area "
            f"or {bounds.max_edge} px edge"
        )


def _to_rgb(frame: Image.Image) -> Image.Image:
    """Return an RGB copy of a frame, leaving the source frame untouched."""

    return frame.convert("RGB")


@contextmanager
def _open_image(path: Path, bounds: ImageBounds) -> Iterator[Image.Image]:
    """Open an image file with decode + bounds guards; always closed."""

    _check_file_size(path, bounds)
    try:
        image = Image.open(path)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise IngestError(f"could not decode image {path!s}: {exc}") from exc
    try:
        yield image
    finally:
        image.close()


def load_image_pages(
    path: str | Path,
    settings: Settings,
) -> list[tuple[RenderedPage, Image.Image]]:
    """Load an image file into one or more ``(RenderedPage, PIL.Image)`` pairs.

    Multi-page TIFFs yield one pair per frame; every other format yields a single pair. Each
    returned RGB image is independent (callers own and must close them). Raises
    :class:`IngestError` on a decode failure or an over-bounds image.
    """

    file_path = Path(path)
    bounds = ImageBounds(settings)
    results: list[tuple[RenderedPage, Image.Image]] = []

    with _open_image(file_path, bounds) as image:
        try:
            frames = list(ImageSequence.Iterator(image))
        except (OSError, ValueError, SyntaxError) as exc:
            raise IngestError(f"could not iterate frames of {file_path!s}: {exc}") from exc

        for index, frame in enumerate(frames):
            try:
                frame.load()
            except (OSError, Image.DecompressionBombError, ValueError) as exc:
                _close_all(results)
                raise IngestError(
                    f"could not decode frame {index} of {file_path!s}: {exc}"
                ) from exc

            try:
                _check_dimensions(frame, bounds)
                rgb = _to_rgb(frame)
            except Image.DecompressionBombError as exc:
                _close_all(results)
                raise IngestError(f"image frame {index} is a decompression bomb: {exc}") from exc
            except IngestError:
                _close_all(results)
                raise

            rendered = RenderedPage(
                index=index,
                width=rgb.width,
                height=rgb.height,
                dpi=settings_render_dpi(),
                kind=SourceKind.IMAGE,
                text_layer=None,
            )
            results.append((rendered, rgb))

    return results


def iter_image_pages(
    path: str | Path,
    settings: Settings,
) -> Iterator[tuple[RenderedPage, Image.Image]]:
    """Lazily yield one ``(RenderedPage, RGB Image)`` per frame, one bitmap at a time.

    Mirrors :func:`texora_engine.ingest.pdf.iter_pdf_pages`: loads + converts ONE frame at a time
    via ``ImageSequence.Iterator``, applies the same :class:`ImageBounds` guards, and never holds
    more than the current frame's bitmap (design §2.1, MEDIUM-1). The caller owns and MUST close
    each yielded image before requesting the next. The eager :func:`load_image_pages` is left
    untouched for the small-image synchronous routes.
    """

    file_path = Path(path)
    bounds = ImageBounds(settings)
    with _open_image(file_path, bounds) as image:
        try:
            iterator = ImageSequence.Iterator(image)
        except (OSError, ValueError, SyntaxError) as exc:
            raise IngestError(f"could not iterate frames of {file_path!s}: {exc}") from exc

        for index, frame in enumerate(iterator):
            try:
                frame.load()
            except (OSError, Image.DecompressionBombError, ValueError) as exc:
                raise IngestError(
                    f"could not decode frame {index} of {file_path!s}: {exc}"
                ) from exc
            try:
                _check_dimensions(frame, bounds)
                rgb = _to_rgb(frame)
            except Image.DecompressionBombError as exc:
                raise IngestError(f"image frame {index} is a decompression bomb: {exc}") from exc

            rendered = RenderedPage(
                index=index,
                width=rgb.width,
                height=rgb.height,
                dpi=settings_render_dpi(),
                kind=SourceKind.IMAGE,
                text_layer=None,
            )
            yield rendered, rgb


def image_frame_count(path: str | Path, settings: Settings) -> int:
    """Return the number of frames in an image file (one open, no bitmap decode — design §6.1)."""

    file_path = Path(path)
    bounds = ImageBounds(settings)
    with _open_image(file_path, bounds) as image:
        try:
            return sum(1 for _ in ImageSequence.Iterator(image))
        except (OSError, ValueError, SyntaxError) as exc:
            raise IngestError(f"could not iterate frames of {file_path!s}: {exc}") from exc


def _close_all(pairs: list[tuple[RenderedPage, Image.Image]]) -> None:
    """Close already-produced images when a later frame fails (no leaks on error)."""

    for _, img in pairs:
        img.close()
    pairs.clear()


def settings_render_dpi() -> int:
    """Nominal DPI recorded for raster images.

    Standalone images have no intrinsic DPI from the pipeline's perspective; 96 is the
    conventional screen DPI and is used purely as metadata on :class:`RenderedPage` (the
    pixels are taken as-is -- no resampling happens for images).
    """

    return 96
