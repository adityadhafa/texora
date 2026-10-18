"""PP-DocLayout layout detector via ONNX Runtime — the PERMISSIVE shipped default (design §6.3).

Apache-2.0 for both code (``onnxruntime``, MIT) and weights (PP-DocLayout from the PaddleOCR/
PaddleX family). Runs the pinned ``doclayout.onnx`` through an ``onnxruntime.InferenceSession``
(``CPUExecutionProvider`` default; ``CUDAExecutionProvider`` when ``device == "cuda"``). The
CUDA path is CODE-REVIEW-ONLY on this CPU host and is flagged PENDING in docs/m3-verification.md.

Honesty invariant: on ANY inference exception (session load, run, or decode) the adapter logs the
failure and returns ``LayoutResult(regions=[], engine_id=self.id)`` — it NEVER raises and NEVER
fabricates a region (``R-REC-8``). A failed detection downgrades the page to ``needs_review`` in
the assembler.

The ``label_map.txt`` file maps PP-DocLayout class indices to the :class:`RegionType` taxonomy;
indices with no mapping collapse to :attr:`RegionType.UNKNOWN` rather than being dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from texora_engine.ingest.base import RenderedPage
from texora_engine.layout.base import BBox, LayoutResult, Region, RegionType
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady

logger = get_logger("layout.pp_doclayout_onnx")

# PP-DocLayout class-label strings -> the Texora RegionType taxonomy. The pinned label_map.txt
# supplies the per-index label strings; this table collapses those strings into our taxonomy.
# Unmapped labels fall through to RegionType.UNKNOWN (never dropped, never guessed).
_LABEL_TO_TYPE: dict[str, RegionType] = {
    "title": RegionType.TITLE,
    "doc_title": RegionType.TITLE,
    "paragraph_title": RegionType.TITLE,
    "text": RegionType.PARAGRAPH,
    "paragraph": RegionType.PARAGRAPH,
    "abstract": RegionType.PARAGRAPH,
    "content": RegionType.PARAGRAPH,
    "formula": RegionType.DISPLAY_MATH,
    "display_math": RegionType.DISPLAY_MATH,
    "isolate_formula": RegionType.DISPLAY_MATH,
    "inline_formula": RegionType.INLINE_MATH,
    "inline_math": RegionType.INLINE_MATH,
    "formula_number": RegionType.EQUATION_NUMBER,
    "equation_number": RegionType.EQUATION_NUMBER,
    "table": RegionType.TABLE,
    "figure": RegionType.FIGURE,
    "image": RegionType.FIGURE,
    "chart": RegionType.FIGURE,
    "figure_caption": RegionType.CAPTION,
    "table_caption": RegionType.CAPTION,
    "caption": RegionType.CAPTION,
    "footnote": RegionType.FOOTNOTE,
    "header": RegionType.HEADER,
    "page_header": RegionType.HEADER,
    "footer": RegionType.FOOTER,
    "page_footer": RegionType.FOOTER,
    "list": RegionType.LIST,
    "code": RegionType.CODE,
    "algorithm": RegionType.CODE,
    "handwriting": RegionType.HANDWRITING,
}


def _load_label_map(path: Path) -> dict[int, RegionType]:
    """Parse ``label_map.txt`` (one label per line, index = line number) into index->RegionType."""

    mapping: dict[int, RegionType] = {}
    with open(path, encoding="utf-8") as fh:
        for idx, raw in enumerate(fh):
            label = raw.strip().lower()
            if not label:
                continue
            mapping[idx] = _LABEL_TO_TYPE.get(label, RegionType.UNKNOWN)
    return mapping


class PpDocLayoutOnnxDetector:
    """Concrete :class:`~texora_engine.layout.base.LayoutDetector` backed by PP-DocLayout ONNX."""

    id = "pp_doclayout_onnx"
    model_ids = ("pp_doclayout",)

    def __init__(self, layout_onnx: Path, label_map: Path, device: str = "cpu") -> None:
        if not layout_onnx.exists():
            raise ModelNotReady("pp_doclayout")
        if not label_map.exists():
            raise ModelNotReady("pp_doclayout")

        self._device = device
        self._label_map = _load_label_map(label_map)

        # Import onnxruntime lazily so merely importing this module (e.g. tests that assert
        # ModelNotReady) does not pull the heavy runtime unless weights exist.
        import onnxruntime as ort

        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if device == "cuda"
            else ["CPUExecutionProvider"]
        )
        logger.info("constructing pp_doclayout_onnx on device=%s (providers=%s)", device, providers)
        self._session: Any = ort.InferenceSession(str(layout_onnx), providers=providers)

    def detect(self, image: Image.Image, page: RenderedPage) -> LayoutResult:
        """Run PP-DocLayout on ``image``; never raise — map failures to an empty result."""

        try:
            regions = self._infer(image)
        except Exception as exc:  # inference failure must not crash the caller (R-REC-8)
            logger.warning("pp_doclayout_onnx inference failed: %s", exc)
            return LayoutResult(regions=[], engine_id=self.id)
        return LayoutResult(regions=regions, engine_id=self.id)

    def _infer(self, image: Image.Image) -> list[Region]:
        """Preprocess -> run the ONNX session -> decode detections to :class:`Region`s.

        Raises on any failure; :meth:`detect` catches and converts to an empty result. The
        concrete tensor preprocessing + box decoding depend on the exact pinned PP-DocLayout
        export signature, which lands at model adoption (URL/SHA pin-on-first-fetch); the
        decode below reads the standard ``[N, 6] = (x0, y0, x1, y1, score, class)`` detection
        head and maps class indices through ``label_map.txt``.
        """

        import numpy as np

        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        # HWC -> CHW -> NCHW
        tensor = np.transpose(arr, (2, 0, 1))[np.newaxis, ...]
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: tensor})
        dets = np.asarray(outputs[0])
        if dets.ndim == 3:
            dets = dets[0]

        regions: list[Region] = []
        for row in dets:
            x0, y0, x1, y1, score, cls = (float(v) for v in row[:6])
            rtype = self._label_map.get(int(cls), RegionType.UNKNOWN)
            regions.append(
                Region(
                    type=rtype,
                    bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                    confidence=max(0.0, min(1.0, score)),
                    source="model",
                )
            )
        return regions
