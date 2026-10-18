"""Tesseract text recognizer (permissive fallback, EN + ID) via pytesseract (design §7.2).

``id = "tesseract"``, ``model_ids = ()`` — Tesseract uses its own Apache-2.0 ``traineddata``
located via ``settings``/``PATH``, not Texora's model store. Recognition runs
``pytesseract.image_to_data`` with ``lang="eng+ind"`` (EN + ID first-class) and normalizes the
per-word Tesseract confidence (0..100) to a 0..1 :class:`~texora_engine.recognizers.base.TextLine`
confidence. On any error the adapter returns ``status=FAILED`` — it never raises from
:meth:`recognize` and never fabricates text (``R-REC-8``).
"""

from __future__ import annotations

from PIL import Image

from texora_engine.layout.base import BBox
from texora_engine.logging_config import get_logger
from texora_engine.recognizers.base import (
    ConfidenceKind,
    RecognitionStatus,
    RegionContext,
    TextLine,
    TextResult,
)

logger = get_logger("recognizers.text_tesseract")

# Tesseract language codes for English + Indonesian (first-class per the product rules).
_TESSERACT_LANGS = "eng+ind"


class TesseractUnavailable(Exception):
    """The Tesseract binary could not be resolved or probed (install/point to it).

    Raised by the factory when ``text: tesseract`` is selected explicitly but no usable binary
    is found; the API maps it to 409 with an actionable message — never a silent no-op.
    """

    def __init__(self, tesseract_cmd: str | None) -> None:
        self.tesseract_cmd = tesseract_cmd
        where = tesseract_cmd or "PATH"
        super().__init__(
            f"tesseract binary is not usable (looked at {where}); install it or set "
            "TEXORA_ENGINE_TESSERACT_CMD"
        )


class TesseractTextRecognizer:
    """Concrete :class:`~texora_engine.recognizers.base.TextRecognizer` backed by Tesseract."""

    id = "tesseract"
    model_ids: tuple[str, ...] = ()
    langs: tuple[str, ...] = ("en", "id")

    def __init__(
        self,
        langs: tuple[str, ...] = ("en", "id"),
        tesseract_cmd: str | None = None,
        data_dir: str | None = None,
    ) -> None:
        self._langs = langs
        self._tesseract_cmd = tesseract_cmd
        self._data_dir = data_dir

    def recognize(self, image: Image.Image, ctx: RegionContext) -> TextResult:
        """Run Tesseract on ``image``; never raise — map failures to status=FAILED."""

        try:
            lines = self._infer(image)
        except Exception as exc:  # binary/decode/parse failure must not crash the caller
            logger.warning("tesseract recognition failed: %s", exc)
            return TextResult(
                lines=[],
                status=RecognitionStatus.FAILED,
                engine_id=self.id,
                detail=f"tesseract error: {exc}",
            )
        return TextResult(lines=lines, status=RecognitionStatus.OK, engine_id=self.id)

    def _infer(self, image: Image.Image) -> list[TextLine]:
        """Run ``image_to_data`` and group words into lines with averaged confidence."""

        import pytesseract

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        config = f'--tessdata-dir "{self._data_dir}"' if self._data_dir else ""
        data = pytesseract.image_to_data(
            image.convert("RGB"),
            lang=_TESSERACT_LANGS,
            output_type=pytesseract.Output.DICT,
            config=config,
        )

        n = len(data["text"])
        # Group words by (block, paragraph, line) so one TextLine == one Tesseract line.
        grouped: dict[tuple[int, int, int], list[int]] = {}
        order: list[tuple[int, int, int]] = []
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(i)

        lines: list[TextLine] = []
        for key in order:
            idxs = grouped[key]
            words = [(data["text"][i] or "").strip() for i in idxs]
            text = " ".join(w for w in words if w)
            if not text:
                continue
            confs = [float(data["conf"][i]) for i in idxs if float(data["conf"][i]) >= 0.0]
            confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
            x0 = min(float(data["left"][i]) for i in idxs)
            y0 = min(float(data["top"][i]) for i in idxs)
            x1 = max(float(data["left"][i]) + float(data["width"][i]) for i in idxs)
            y1 = max(float(data["top"][i]) + float(data["height"][i]) for i in idxs)
            lines.append(
                TextLine(
                    text=text,
                    bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                    confidence=max(0.0, min(1.0, confidence)),
                    confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
                )
            )
        return lines
