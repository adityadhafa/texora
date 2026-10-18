"""``POST /pages/recognize`` — synchronous single-document PDF/image recognition (design §7.6).

Validates + sanitizes the input path, builds/caches the :class:`PipelineDeps` on ``app.state``
(lazy, like the M2 formula singleton), runs the page assembler over the document, and returns a
typed :class:`~texora_engine.pipeline.page_result.DocumentResult`.

Error mapping mirrors ``api/recognize.py``: ``ModelNotReady`` / ``TesseractUnavailable`` → 409
(prompt download / install); misconfiguration (unknown engine / stage not configured) → 500; bad
path / page range / decode → 422. This is the synchronous M3 seam; M4 adds the async ``POST /jobs``
streaming variant over the same assembler.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from texora_engine.ingest.base import IngestError
from texora_engine.ingest.images import load_image_pages
from texora_engine.ingest.pdf import iter_pdf_pages
from texora_engine.layout.factory import (
    LayoutStageNotConfigured,
    UnknownLayoutEngineError,
    build_layout_detector,
)
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.pipeline import DocumentResult, PageResult, PipelineDeps, assemble_page
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.recognizers.factory import (
    FormulaStageNotConfigured,
    UnknownEngineError,
    build_formula_recognizer,
)
from texora_engine.recognizers.text_factory import (
    TextStageNotConfigured,
    UnknownTextEngineError,
    build_text_recognizer,
)
from texora_engine.recognizers.text_tesseract import TesseractUnavailable
from texora_engine.security import require_token

logger = get_logger("api.pages")

_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}

pages_router = APIRouter(dependencies=[Depends(require_token)], tags=["pages"])


class PagesRequest(BaseModel):
    """Request body for a document recognition run."""

    path: str = Field(description="Absolute path to a local PDF or image file.")
    dpi: int | None = Field(
        default=None, description="Optional render-DPI override (clamped to [72, max_dpi])."
    )
    page_start: int | None = Field(
        default=None, ge=0, description="First 0-based page index (inclusive)."
    )
    page_end: int | None = Field(
        default=None, ge=0, description="Last 0-based page index (inclusive)."
    )


def _validate_path(raw: str) -> Path:
    """Resolve + sanitize the input path; raise 422 on anything suspicious or unsupported."""

    if ".." in Path(raw).parts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="path traversal ('..') is not allowed",
        )
    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"path does not exist or is not accessible: {exc}",
        ) from exc
    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="path is not a regular file",
        )
    ext = resolved.suffix.lower()
    if ext not in _PDF_EXTS and ext not in _IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported file extension {ext!r}",
        )
    return resolved


def _get_deps(request: Request) -> PipelineDeps:
    """Build + cache the PipelineDeps on app.state (lazy, needs downloaded weights)."""

    cached: PipelineDeps | None = request.app.state.pipeline_deps
    if cached is not None:
        return cached
    settings = request.app.state.settings
    store = request.app.state.model_store
    cfg = load_pipeline_config()
    deps = PipelineDeps(
        layout=build_layout_detector(settings, store),
        text=build_text_recognizer(settings, store),
        formula=build_formula_recognizer(settings, store),
        settings=settings,
        pipeline_config=cfg,
        asset_dir=Path(settings.figure_asset_dir),
    )
    request.app.state.pipeline_deps = deps
    return deps


def _page_in_range(idx: int, start: int | None, end: int | None) -> bool:
    if start is not None and idx < start:
        return False
    if end is not None and idx > end:
        return False
    return True


def _validate_range(start: int | None, end: int | None) -> None:
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="page_start must be <= page_end",
        )


@pages_router.post("/pages/recognize", response_model=DocumentResult)
def recognize_pages(req: PagesRequest, request: Request) -> DocumentResult:
    """Recognize a whole PDF/image document into a typed :class:`DocumentResult`."""

    settings = request.app.state.settings
    resolved = _validate_path(req.path)
    _validate_range(req.page_start, req.page_end)

    try:
        deps = _get_deps(request)
    except (ModelNotReady, TesseractUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"model/engine not ready: {exc}. Download/install it first.",
        ) from exc
    except (
        UnknownEngineError,
        UnknownTextEngineError,
        UnknownLayoutEngineError,
        FormulaStageNotConfigured,
        TextStageNotConfigured,
        LayoutStageNotConfigured,
    ) as exc:
        logger.error("pipeline misconfiguration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pipeline misconfiguration: {exc}",
        ) from exc

    cfg = deps.pipeline_config
    if req.dpi is not None:
        clamped = max(72, min(req.dpi, cfg.ingest.max_dpi))
        cfg = cfg.model_copy(update={"ingest": cfg.ingest.model_copy(update={"base_dpi": clamped})})

    ext = resolved.suffix.lower()
    pages: list[PageResult] = []
    try:
        if ext in _PDF_EXTS:
            for idx, (rendered, image) in enumerate(iter_pdf_pages(resolved, cfg.ingest)):
                if not _page_in_range(idx, req.page_start, req.page_end):
                    image.close()
                    continue
                pages.append(assemble_page(rendered, image, deps))
        else:
            loaded = load_image_pages(resolved, settings)
            for idx, (rendered, image) in enumerate(loaded):
                if not _page_in_range(idx, req.page_start, req.page_end):
                    image.close()
                    continue
                pages.append(assemble_page(rendered, image, deps))
    except IngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"could not ingest document: {exc}",
        ) from exc

    return DocumentResult(source_name=resolved.name, pages=pages)
