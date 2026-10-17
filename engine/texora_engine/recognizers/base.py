"""Stable recognizer Protocol + shared result types.

``FormulaRecognizer`` is the engine-agnostic seam that keeps the API/UI free of any specific
model. Adapters implement it; the pipeline factory selects one by id from ``pipeline.yaml``.
Results are Pydantic models (not bare dicts) so they serialize straight into the API and are
mypy-strict across module boundaries. A result NEVER contains a fabricated guess — an
unrecognizable region yields ``needs_review``/``failed``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from PIL import Image
from pydantic import BaseModel, Field


class RecognitionStatus(StrEnum):
    """Single source of truth for recognition/validation state.

    Shared by :class:`FormulaResult`, the LaTeX validator, and the snip API response, and
    mirrored as the TS union ``'ok' | 'needs_review' | 'failed'`` in ``engineClient.ts`` so
    the same literals cross the language boundary with no drift (never "needs-review").
    """

    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ConfidenceKind(StrEnum):
    """How a confidence value was derived."""

    TOKEN_LOGPROB = "token_logprob"
    UNAVAILABLE = "unavailable"


class RegionContext(BaseModel):
    """Inputs that influence recognition but are not the image itself."""

    is_display: bool = Field(
        default=True,
        description=(
            "Display vs inline math hint. In M2 this does NOT change recognition "
            "(pix2tex has no display/inline switch); it only controls downstream Markdown "
            "wrapping ($$...$$ vs $...$) assembled in the UI."
        ),
    )
    device: str = Field(default="cpu", description="Execution device: cpu|cuda|mps.")
    source: str = Field(default="snip", description="snip|page — provenance for logging.")


class FormulaResult(BaseModel):
    """Explicit result type. Never contains a fabricated guess."""

    latex: str = Field(default="", description="Recognized LaTeX; empty when failed.")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_kind: ConfidenceKind = Field(
        default=ConfidenceKind.UNAVAILABLE,
        description=(
            "'token_logprob' = calibrated from decoder logprobs; "
            "'unavailable' = no meaningful score (confidence is 0.0, see detail)."
        ),
    )
    status: RecognitionStatus = Field(default=RecognitionStatus.OK)
    engine_id: str = Field(description="Adapter id that produced this result.")
    detail: str | None = Field(default=None, description="Failure/why context.")


@runtime_checkable
class FormulaRecognizer(Protocol):
    """Stable, minimal, pure recognizer interface."""

    id: str
    # Model registry id(s) this adapter needs, declared by the adapter rather than
    # assuming adapter.id == model.id.
    model_ids: tuple[str, ...]

    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult:
        """Recognize a single cropped formula image into a :class:`FormulaResult`.

        Pure: no I/O beyond the model forward pass. Implementations MUST catch their own
        inference errors and return ``status=FAILED`` with ``detail`` rather than raising.
        """
        ...
