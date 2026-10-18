"""Individually toggleable image preprocessing (design §5, R-ING-4).

One pure function per step; :func:`preprocess` applies the enabled steps in the fixed order
deskew -> perspective -> denoise -> binarize -> auto_crop, each returning a NEW image and
freeing the previous intermediate. A step whose flag is false is a strict no-op: the function
returns the input image object unchanged, so a disabled pipeline yields byte-identical output
(the toggle-respect contract the tests assert).

Born-digital pages are already clean, so the assembler passes them through with no
preprocessing unless a flag is forced on by the caller.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from texora_engine.ingest.base import SourceKind
from texora_engine.logging_config import get_logger
from texora_engine.pipeline_config import PreprocessSettings

logger = get_logger("ingest.preprocess")

# Below this absolute skew angle a deskew rotation is pointless and is skipped.
_DESKEW_MIN_DEG = 0.3
# Deskew only corrects modest page rotation; anything beyond this is left alone.
_DESKEW_MAX_DEG = 15.0


def _to_gray(img: Image.Image) -> npt.NDArray[np.uint8]:
    """Return a grayscale uint8 ndarray view of a PIL image (for OpenCV ops)."""

    return np.asarray(img.convert("L"), dtype=np.uint8)


def estimate_skew_deg(img: Image.Image) -> float:
    """Estimate page skew in degrees via the min-area rectangle of the foreground mask.

    Positive = the content is rotated counter-clockwise (so a positive correction rotates it
    back clockwise). Returns 0.0 when no foreground is found. The angle is normalized into
    [-45, 45] so near-upright pages report a small magnitude.
    """

    gray = _to_gray(img)
    # Foreground = dark ink on light paper. Otsu threshold, then invert so ink is white.
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    # OpenCV (>=4.5) reports the rectangle angle in (0, 90]. A near-horizontal text block
    # is ambiguous by 90 degrees, so fold into the smallest-magnitude deviation from upright
    # in [-45, 45]: angles above 45 denote a slightly-rotated wide block (angle - 90).
    if angle > 45.0:
        angle -= 90.0
    return float(angle)


def deskew(img: Image.Image) -> Image.Image:
    """Rotate the image to remove a small skew; a near-upright page is returned unchanged."""

    angle = estimate_skew_deg(img)
    if abs(angle) < _DESKEW_MIN_DEG or abs(angle) > _DESKEW_MAX_DEG:
        return img
    # Rotate by the measured angle to counter the skew (PIL rotates counter-clockwise for a
    # positive angle, matching this estimator's sign); expand to keep all content, white fill.
    return img.rotate(
        angle, expand=True, fillcolor=(255, 255, 255), resample=Image.Resampling.BICUBIC
    )


def denoise(img: Image.Image) -> Image.Image:
    """Reduce scan noise with non-local-means (grayscale-preserving on an RGB image)."""

    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    cleaned = cv2.fastNlMeansDenoisingColored(arr, None, 7, 7, 7, 21)
    return Image.fromarray(cleaned, mode="RGB")


def binarize(img: Image.Image) -> Image.Image:
    """Adaptive (Otsu) binarization; returns an RGB image so downstream types stay uniform."""

    gray = _to_gray(img)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary, mode="L").convert("RGB")


def perspective(img: Image.Image) -> Image.Image:
    """Four-point perspective correction from the largest quadrilateral contour.

    If no suitable quadrilateral is found (e.g. a flat scan with no page border), the image
    is returned unchanged -- correction only helps photographed pages.
    """

    gray = _to_gray(img)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img
    largest = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        return img

    quad = _order_quad(approx.reshape(4, 2).astype(np.float32))
    (tl, tr, br, bl) = quad
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width <= 0 or height <= 0:
        return img
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(quad, dst)
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    warped = cv2.warpPerspective(arr, matrix, (width, height))
    return Image.fromarray(warped, mode="RGB")


def _order_quad(pts: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""

    ordered = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    ordered[0] = pts[np.argmin(s)]  # top-left: smallest x+y
    ordered[2] = pts[np.argmax(s)]  # bottom-right: largest x+y
    ordered[1] = pts[np.argmin(diff)]  # top-right: smallest y-x
    ordered[3] = pts[np.argmax(diff)]  # bottom-left: largest y-x
    return ordered


def auto_crop(img: Image.Image) -> Image.Image:
    """Trim surrounding whitespace to the foreground bounding box with a small pad."""

    gray = _to_gray(img)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return img
    x, y, w, h = cv2.boundingRect(coords)
    pad = 4
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(img.width, x + w + pad)
    bottom = min(img.height, y + h + pad)
    if left == 0 and top == 0 and right == img.width and bottom == img.height:
        return img
    return img.crop((left, top, right, bottom))


def preprocess(
    img: Image.Image,
    cfg: PreprocessSettings,
    kind: SourceKind,
) -> Image.Image:
    """Apply the enabled preprocessing steps in the fixed order, freeing intermediates.

    A disabled step is skipped entirely (no-op). ``kind`` gates the scanned-only denoise
    step: denoise runs only for scanned pages/images even when its flag is on, because
    non-local-means on a crisp born-digital render only blurs it.
    """

    current = img

    def _apply(step_fn: Callable[[Image.Image], Image.Image], enabled: bool) -> None:
        nonlocal current
        if not enabled:
            return
        produced = step_fn(current)
        if produced is not current:
            prev = current
            current = produced
            # Free our own intermediate, but never the caller-owned input image.
            if prev is not img:
                prev.close()

    _apply(deskew, cfg.deskew)
    _apply(perspective, cfg.perspective)
    _apply(denoise, cfg.denoise and kind != SourceKind.PDF_BORN_DIGITAL)
    _apply(binarize, cfg.binarize)
    _apply(auto_crop, cfg.auto_crop)
    return current
