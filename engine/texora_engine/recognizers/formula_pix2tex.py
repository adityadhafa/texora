"""pix2tex (LaTeX-OCR) formula recognizer — REAL inference, local-weights-only.

The adapter constructs pix2tex pointed ONLY at registry-resolved local checkpoint/resizer
paths so pix2tex's built-in GitHub downloader is NEVER triggered (R-SEC-1, FR-1). If a
weight file is absent it raises :class:`ModelNotReady` and makes no network call.

Confidence (R-REC-2, design §B.4): the pinned pix2tex exposes no usable per-token scores —
its ``CustomARWrapper.generate`` returns token ids only and discards the sampling
probabilities. Verified on the pin (see docs/m2-verification.md). So every result carries
``confidence=0.0`` with ``confidence_kind="unavailable"`` and a ``detail`` — NEVER a
fabricated number. A scoring-capable engine is expected to land in M7.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image

from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaResult,
    RecognitionStatus,
    RegionContext,
)

logger = get_logger("recognizers.pix2tex")

# Confidence is unavailable on the pinned pix2tex (probed at adoption, see verification doc).
_CONFIDENCE_UNAVAILABLE_DETAIL = (
    "pix2tex 0.1.4 exposes no usable per-token scores; confidence reported as unavailable"
)


class Pix2TexFormulaRecognizer:
    """Concrete :class:`FormulaRecognizer` backed by pix2tex on CPU/CUDA."""

    id = "pix2tex"
    model_ids = ("pix2tex",)

    def __init__(self, checkpoint_path: Path, resizer_path: Path, device: str = "cpu") -> None:
        if not checkpoint_path.exists():
            raise ModelNotReady("pix2tex")
        # The resizer is optional in pix2tex, but our catalog pins it; require it too so a
        # partial install is treated as not-ready rather than silently degrading.
        if not resizer_path.exists():
            raise ModelNotReady("pix2tex")

        self._device = device
        # Import pix2tex lazily so merely importing this module (e.g. for tests that assert
        # ModelNotReady) does not pull the heavy torch/pix2tex stack unless weights exist.
        import pix2tex as _pix2tex
        from munch import Munch
        from pix2tex.cli import LatexOCR

        pkg_dir = Path(_pix2tex.__file__).resolve().parent
        config_path = pkg_dir / "model" / "settings" / "config.yaml"

        # no_cuda forces CPU; when device is cuda/mps we let pix2tex pick cuda if available.
        no_cuda = device not in ("cuda",)
        args = Munch(
            {
                "config": str(config_path),
                "checkpoint": str(checkpoint_path),
                "no_cuda": no_cuda,
                "no_resize": False,
            }
        )
        # Quiet pix2tex's albumentations update check in library use.
        os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
        logger.info("constructing pix2tex on device=%s (no_cuda=%s)", device, no_cuda)
        self._model: Any = LatexOCR(args)

    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult:
        """Run pix2tex on ``image``; never raise — map failures to status=FAILED."""

        try:
            # pix2tex expects a PIL image; it handles its own preprocessing.
            latex = self._model(image.copy())
        except Exception as exc:  # inference failure must not crash the caller
            logger.warning("pix2tex inference failed: %s", exc)
            return FormulaResult(
                latex="",
                confidence=0.0,
                confidence_kind=ConfidenceKind.UNAVAILABLE,
                status=RecognitionStatus.FAILED,
                engine_id=self.id,
                detail=f"inference error: {exc}",
            )

        latex = (latex or "").strip()
        if not latex:
            return FormulaResult(
                latex="",
                confidence=0.0,
                confidence_kind=ConfidenceKind.UNAVAILABLE,
                status=RecognitionStatus.FAILED,
                engine_id=self.id,
                detail="empty recognition result",
            )

        # Honest confidence: unavailable on the pinned pix2tex (never fabricated).
        return FormulaResult(
            latex=latex,
            confidence=0.0,
            confidence_kind=ConfidenceKind.UNAVAILABLE,
            status=RecognitionStatus.OK,
            engine_id=self.id,
            detail=_CONFIDENCE_UNAVAILABLE_DETAIL,
        )
