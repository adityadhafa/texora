"""Shared file-path validation for job/batch intake (design §10).

Factored from ``api/pages._validate_path`` so the sync pages route and the async job routes use one
validator. Raises the typed :class:`PathValidationError` (mapped to 422 by the routes) rather than
an ``HTTPException`` so it is framework-agnostic and unit-testable.
"""

from __future__ import annotations

from pathlib import Path

_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
SUPPORTED_EXTS = _PDF_EXTS | _IMAGE_EXTS


class PathValidationError(Exception):
    """A supplied path failed validation (traversal, missing, wrong type, unsupported ext)."""


def validate_source_path(raw: str, *, allow_dir: bool = False) -> Path:
    """Resolve + sanitize ``raw``; raise :class:`PathValidationError` on anything suspect.

    Rejects ``..`` traversal, requires the path to exist, requires a regular file (or a directory
    when ``allow_dir``), and requires a supported extension for files.
    """

    if ".." in Path(raw).parts:
        raise PathValidationError("path traversal ('..') is not allowed")
    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathValidationError(f"path does not exist or is not accessible: {exc}") from exc

    if resolved.is_dir():
        if not allow_dir:
            raise PathValidationError("path is a directory, not a regular file")
        return resolved

    if not resolved.is_file():
        raise PathValidationError("path is not a regular file")
    ext = resolved.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise PathValidationError(f"unsupported file extension {ext!r}")
    return resolved


def is_supported_file(path: Path) -> bool:
    """Whether ``path`` is a regular file with a supported extension."""

    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
