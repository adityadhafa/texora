"""``POST /recognize/snip`` — single-image formula OCR.

Decodes + bounds-checks the image, runs the cached pix2tex recognizer in a single-worker
thread pool under a per-call timeout, validates/normalizes the LaTeX, converts to MathML,
and returns a typed :class:`SnipResponse`. Honesty rules: an unrecognizable image returns
200 with ``status=needs_review|failed`` and empty LaTeX (never a guess); bad input returns a
typed 4xx; a timeout returns 200 with ``status=failed``. ``asciimath`` is always ``null`` in
M2 (deferred to M6).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request, status
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from texora_engine.ensemble import validate_and_normalize
from texora_engine.export import latex_to_mathml
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaRecognizer,
    FormulaResult,
    RecognitionStatus,
    RegionContext,
)
from texora_engine.recognizers.factory import (
    FormulaStageNotConfigured,
    UnknownEngineError,
    build_formula_recognizer,
)
from texora_engine.security import require_token

logger = get_logger("api.recognize")

# One shared single-worker pool: pix2tex's torch module is not concurrency-safe, so snips
# are serialized (backpressure) rather than racing the same model from two threads.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="snip")


class SnipRequest(BaseModel):
    """Request body for a snip recognition."""

    image_base64: str = Field(description="PNG/JPEG bytes, base64; <= max_snip_bytes decoded.")
    is_display: bool = Field(default=True, description="Display vs inline math hint.")


class SnipResponse(BaseModel):
    """Recognition result. Never contains a fabricated guess."""

    latex: str
    confidence: float
    confidence_kind: ConfidenceKind
    status: RecognitionStatus
    validation: RecognitionStatus
    mathml: str | None
    asciimath: str | None = None  # always null in M2 (M6 exporters)
    detail: str | None = None


recognize_router = APIRouter(dependencies=[Depends(require_token)], tags=["recognize"])


def _get_recognizer(request: Request) -> FormulaRecognizer:
    """Return the cached formula recognizer, building it once on first use."""

    cached: FormulaRecognizer | None = request.app.state.formula_recognizer
    if cached is not None:
        return cached
    settings = request.app.state.settings
    store = request.app.state.model_store
    recognizer = build_formula_recognizer(settings, store)
    request.app.state.formula_recognizer = recognizer
    return recognizer


def _decode_image(req: SnipRequest, max_bytes: int, max_pixels: int, max_edge: int) -> Image.Image:
    """Decode + bounds-check the base64 image. Any failure raises a typed 422."""

    try:
        raw = base64.b64decode(req.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid base64 image: {exc}",
        ) from exc

    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"image exceeds max size of {max_bytes} bytes",
        )

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()  # type: ignore[no-untyped-call]
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"could not decode image: {exc}",
        ) from exc

    width, height = image.size
    if width * height > max_pixels or max(width, height) > max_edge:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"image too large: {width}x{height} exceeds "
                f"{max_pixels} px area or {max_edge} px edge"
            ),
        )
    return image


@recognize_router.post("/recognize/snip", response_model=SnipResponse)
async def recognize_snip(req: SnipRequest, request: Request) -> SnipResponse:
    """Recognize a single formula image into LaTeX + MathML."""

    settings = request.app.state.settings
    image = _decode_image(
        req,
        max_bytes=settings.max_snip_bytes,
        max_pixels=settings.max_snip_pixels,
        max_edge=settings.max_snip_edge,
    )

    try:
        recognizer = _get_recognizer(request)
    except ModelNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"model not ready: {exc}. Download it first.",
        ) from exc
    except (UnknownEngineError, FormulaStageNotConfigured) as exc:
        logger.error("recognizer misconfiguration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pipeline misconfiguration: {exc}",
        ) from exc

    ctx = RegionContext(is_display=req.is_display, device=settings.device, source="snip")

    loop = asyncio.get_running_loop()
    try:
        result: FormulaResult = await asyncio.wait_for(
            loop.run_in_executor(_EXECUTOR, recognizer.recognize, image, ctx),
            timeout=settings.snip_timeout_s,
        )
    except TimeoutError:
        logger.warning("snip recognition timed out after %ss", settings.snip_timeout_s)
        return SnipResponse(
            latex="",
            confidence=0.0,
            confidence_kind=ConfidenceKind.UNAVAILABLE,
            status=RecognitionStatus.FAILED,
            validation=RecognitionStatus.FAILED,
            mathml=None,
            asciimath=None,
            detail="recognition timed out",
        )

    # Failed recognition: honest empty result, never a guess.
    if result.status == RecognitionStatus.FAILED or not result.latex.strip():
        return SnipResponse(
            latex="",
            confidence=result.confidence,
            confidence_kind=result.confidence_kind,
            status=RecognitionStatus.FAILED,
            validation=RecognitionStatus.FAILED,
            mathml=None,
            asciimath=None,
            detail=result.detail or "could not recognize",
        )

    normalized, validation = validate_and_normalize(result.latex)
    final_status: RecognitionStatus = result.status
    if validation != RecognitionStatus.OK:
        # Downgrade — never present un-validated LaTeX as confident.
        final_status = validation

    mathml = latex_to_mathml(normalized) if validation != RecognitionStatus.FAILED else None

    return SnipResponse(
        latex=normalized if validation != RecognitionStatus.FAILED else "",
        confidence=result.confidence,
        confidence_kind=result.confidence_kind,
        status=final_status,
        validation=validation,
        mathml=mathml,
        asciimath=None,
        detail=result.detail,
    )
