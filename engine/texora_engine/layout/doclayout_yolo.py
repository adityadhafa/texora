"""DocLayout-YOLO layout detector — AGPL-3.0, OPT-IN ONLY, NEVER the shipped default.

LICENSE POLICY (``R-LIC-2``, design §3): ``doclayout-yolo`` 0.0.4 and its ``ultralytics`` lineage
runtime are **AGPL-3.0** (code + weights). This adapter exists so a user can *locally* and
explicitly choose DocLayout-YOLO for personal use, but it is:

- NEVER imported into / registered in :mod:`texora_engine.layout.factory` ``_REGISTRY``;
- NEVER written as a default engine id in ``pipeline.yaml``;
- NEVER bundled in the redistributable installer.

The permissive shipped default is the ``pp_doclayout_onnx`` detector
(:class:`~texora_engine.layout.pp_doclayout_onnx.PpDocLayoutOnnxDetector`, Apache-2.0). Enabling
this adapter requires the same explicit acknowledgment gate the project
reserves for opt-in copyleft/non-commercial engines (Surya, PyMuPDF). See
``docs/LICENSES.md`` → "Deferred / opt-in only".

The module imports ``doclayout_yolo`` lazily inside the constructor so importing this file does
NOT pull the AGPL runtime into the default (permissive) code path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from texora_engine.ingest.base import RenderedPage
from texora_engine.layout.base import BBox, LayoutResult, Region, RegionType
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady

logger = get_logger("layout.doclayout_yolo")

# DocLayout-YOLO class-name strings -> the Texora RegionType taxonomy. Unmapped names collapse
# to RegionType.UNKNOWN (never dropped, never guessed).
_NAME_TO_TYPE: dict[str, RegionType] = {
    "title": RegionType.TITLE,
    "plain text": RegionType.PARAGRAPH,
    "plain_text": RegionType.PARAGRAPH,
    "text": RegionType.PARAGRAPH,
    "abandon": RegionType.UNKNOWN,
    "figure": RegionType.FIGURE,
    "figure_caption": RegionType.CAPTION,
    "table": RegionType.TABLE,
    "table_caption": RegionType.CAPTION,
    "table_footnote": RegionType.FOOTNOTE,
    "isolate_formula": RegionType.DISPLAY_MATH,
    "formula": RegionType.DISPLAY_MATH,
    "formula_caption": RegionType.EQUATION_NUMBER,
}


class DocLayoutYoloDetector:
    """Concrete :class:`~texora_engine.layout.base.LayoutDetector` backed by DocLayout-YOLO.

    OPT-IN ONLY (AGPL-3.0) — see the module docstring. Not registered in the default factory.
    """

    id = "doclayout_yolo"
    model_ids = ("doclayout_yolo",)

    def __init__(self, weights: Path, device: str = "cpu") -> None:
        if not weights.exists():
            raise ModelNotReady("doclayout_yolo")

        self._device = device
        # Lazy import keeps the AGPL runtime out of the permissive default import path.
        from doclayout_yolo import YOLOv10

        logger.info("constructing doclayout_yolo (AGPL opt-in) on device=%s", device)
        self._model: Any = YOLOv10(str(weights))

    def detect(self, image: Image.Image, page: RenderedPage) -> LayoutResult:
        """Run DocLayout-YOLO on ``image``; never raise — map failures to an empty result."""

        try:
            regions = self._infer(image)
        except Exception as exc:  # inference failure must not crash the caller (R-REC-8)
            logger.warning("doclayout_yolo inference failed: %s", exc)
            return LayoutResult(regions=[], engine_id=self.id)
        return LayoutResult(regions=regions, engine_id=self.id)

    def _infer(self, image: Image.Image) -> list[Region]:
        """Run the YOLOv10 predictor and decode detections to :class:`Region`s."""

        rgb = image.convert("RGB")
        results = self._model.predict(rgb, device=self._device, verbose=False)
        regions: list[Region] = []
        for res in results:
            names = res.names
            for box in res.boxes:
                x0, y0, x1, y1 = (float(v) for v in box.xyxy[0].tolist())
                score = float(box.conf[0])
                name = str(names[int(box.cls[0])]).strip().lower()
                rtype = _NAME_TO_TYPE.get(name, RegionType.UNKNOWN)
                regions.append(
                    Region(
                        type=rtype,
                        bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        confidence=max(0.0, min(1.0, score)),
                        source="model",
                    )
                )
        return regions
