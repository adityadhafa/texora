"""PP-OCRv5 text recognizer via ONNX Runtime — the PERMISSIVE shipped default (design §7.2).

Apache-2.0 for both code (``onnxruntime`` MIT, ``shapely`` BSD, ``pyclipper`` MIT) and weights
(PP-OCRv5 from the PaddleOCR family). Detection runs the DB (Differentiable Binarization) head
to find text boxes; recognition runs the CRNN/CTC head on each crop and decodes class indices to
characters via the pinned ``rec_keys.txt`` dictionary. ``langs = ("en", "id")``: PP-OCRv5's Latin
recognizer covers both (Indonesian uses the Latin script model).

Honesty invariant (``R-REC-8``): on ANY inference exception the adapter logs and returns
``TextResult(status=FAILED, lines=[])`` — it NEVER raises from :meth:`recognize` and NEVER
fabricates text. Real per-line confidence comes from the mean CTC step probability
(``TOKEN_LOGPROB``); it is never invented.

CUDA execution provider is selected when ``device == "cuda"``; the CUDA path is CODE-REVIEW-ONLY
on this CPU host and is flagged PENDING in docs/m3-verification.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from texora_engine.layout.base import BBox
from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.recognizers.base import (
    ConfidenceKind,
    RecognitionStatus,
    RegionContext,
    TextLine,
    TextResult,
)

logger = get_logger("recognizers.text_ppocr_onnx")

# DB detector post-process constants (PP-OCR defaults).
_DB_THRESH = 0.3  # binarization threshold on the probability map
_DB_BOX_THRESH = 0.6  # minimum mean box score to keep a detection
_DB_UNCLIP_RATIO = 1.5  # Vatti-clipper expansion ratio for the shrunk polygon
_DET_LIMIT_SIDE = 960  # det input is resized so the long side <= this, multiple of 32
_REC_IMG_HEIGHT = 48  # PP-OCRv5 rec input height
_REC_IMG_MAX_WIDTH = 320  # rec input width cap before right-padding


def _load_dict(path: Path) -> list[str]:
    """Load the rec character dictionary (one char per line) + the CTC blank + space.

    PP-OCR prepends a blank at index 0 and appends a space class at the end; the returned list
    is indexable by the rec head's argmax class index.
    """

    chars: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            chars.append(raw.rstrip("\n"))
    # CTC blank at 0, characters next, a trailing space class (PP-OCR convention).
    return ["blank", *chars, " "]


class PpOcrV5TextRecognizer:
    """Concrete :class:`~texora_engine.recognizers.base.TextRecognizer` backed by PP-OCRv5 ONNX."""

    id = "pp_ocrv5_onnx"
    model_ids: tuple[str, ...] = ("pp_ocrv5_det", "pp_ocrv5_rec")
    langs: tuple[str, ...] = ("en", "id")

    def __init__(
        self,
        det_onnx: Path,
        rec_onnx: Path,
        dict_path: Path,
        langs: tuple[str, ...] = ("en", "id"),
        device: str = "cpu",
    ) -> None:
        if not det_onnx.exists() or not rec_onnx.exists():
            raise ModelNotReady("pp_ocrv5_det" if not det_onnx.exists() else "pp_ocrv5_rec")
        if not dict_path.exists():
            raise ModelNotReady("pp_ocrv5_rec")

        self._langs = langs
        self._device = device
        self._charset = _load_dict(dict_path)

        import onnxruntime as ort

        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if device == "cuda"
            else ["CPUExecutionProvider"]
        )
        logger.info("constructing pp_ocrv5_onnx on device=%s (providers=%s)", device, providers)
        self._det: Any = ort.InferenceSession(str(det_onnx), providers=providers)
        self._rec: Any = ort.InferenceSession(str(rec_onnx), providers=providers)

    def recognize(self, image: Image.Image, ctx: RegionContext) -> TextResult:
        """Detect + recognize text in ``image``; never raise — map failures to FAILED."""

        try:
            lines = self._infer(image)
        except Exception as exc:  # inference failure must not crash the caller (R-REC-8)
            logger.warning("pp_ocrv5_onnx inference failed: %s", exc)
            return TextResult(
                lines=[],
                status=RecognitionStatus.FAILED,
                engine_id=self.id,
                detail=f"inference error: {exc}",
            )
        return TextResult(lines=lines, status=RecognitionStatus.OK, engine_id=self.id)

    # --- Detection -------------------------------------------------------------------------

    def _infer(self, image: Image.Image) -> list[TextLine]:
        import numpy as np

        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.uint8)
        boxes = self._detect(arr)

        lines: list[TextLine] = []
        for box in boxes:
            x0, y0, x1, y1 = box
            crop = rgb.crop((int(x0), int(y0), int(x1), int(y1)))
            if crop.width < 2 or crop.height < 2:
                continue
            text, conf = self._recognize_crop(np.asarray(crop, dtype=np.uint8))
            if not text.strip():
                continue
            lines.append(
                TextLine(
                    text=text,
                    bbox=BBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1)),
                    confidence=max(0.0, min(1.0, conf)),
                    confidence_kind=ConfidenceKind.TOKEN_LOGPROB,
                )
            )
        return lines

    def _detect(self, arr: Any) -> list[tuple[float, float, float, float]]:
        """Run the DB detector and return axis-aligned text boxes (top-left origin px)."""

        import numpy as np

        h, w = arr.shape[:2]
        scale = min(_DET_LIMIT_SIDE / max(h, w), 1.0)
        rh = max(32, int(round(h * scale / 32)) * 32)
        rw = max(32, int(round(w * scale / 32)) * 32)

        resized = np.asarray(
            Image.fromarray(arr).resize((rw, rh), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32) * 255.0
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32) * 255.0
        norm = (resized - mean) / std
        tensor = np.transpose(norm, (2, 0, 1))[np.newaxis, ...].astype(np.float32)

        input_name = self._det.get_inputs()[0].name
        prob_map = np.asarray(self._det.run(None, {input_name: tensor})[0])[0, 0]
        return self._boxes_from_prob_map(prob_map, rw, rh, w, h)

    def _boxes_from_prob_map(
        self, prob_map: Any, rw: int, rh: int, orig_w: int, orig_h: int
    ) -> list[tuple[float, float, float, float]]:
        """Threshold the DB probability map, extract contours, unclip, and rescale to original."""

        import cv2
        import numpy as np
        import pyclipper
        from shapely.geometry import Polygon

        bitmap = (prob_map > _DB_THRESH).astype(np.uint8)
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        sx = orig_w / float(rw)
        sy = orig_h / float(rh)
        boxes: list[tuple[float, float, float, float]] = []
        for contour in contours:
            if cv2.contourArea(contour) < 4:
                continue
            pts = contour.reshape(-1, 2)
            # Mean probability inside the contour's bounding box as the box score.
            bx, by, bw, bh = cv2.boundingRect(contour)
            region = prob_map[by : by + bh, bx : bx + bw]
            if region.size == 0 or float(region.mean()) < _DB_BOX_THRESH:
                continue
            poly = Polygon(pts)
            if not poly.is_valid or poly.area < 1.0:
                continue
            distance = poly.area * _DB_UNCLIP_RATIO / poly.length
            offset = pyclipper.PyclipperOffset()
            offset.AddPath([tuple(p) for p in pts], pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            expanded = offset.Execute(distance)
            if not expanded:
                continue
            exp = np.asarray(expanded[0], dtype=np.float32)
            x0 = float(exp[:, 0].min()) * sx
            y0 = float(exp[:, 1].min()) * sy
            x1 = float(exp[:, 0].max()) * sx
            y1 = float(exp[:, 1].max()) * sy
            boxes.append(
                (
                    max(0.0, x0),
                    max(0.0, y0),
                    min(float(orig_w), x1),
                    min(float(orig_h), y1),
                )
            )
        # Top-to-bottom, then left-to-right reading order within the region.
        boxes.sort(key=lambda b: (round(b[1] / 10.0), b[0]))
        return boxes

    # --- Recognition -----------------------------------------------------------------------

    def _recognize_crop(self, crop: Any) -> tuple[str, float]:
        """Run the CTC rec head on one crop; return (decoded_text, mean_step_confidence)."""

        import numpy as np

        h, w = crop.shape[:2]
        ratio = w / float(h)
        target_w = min(_REC_IMG_MAX_WIDTH, max(1, int(_REC_IMG_HEIGHT * ratio)))
        resized = np.asarray(
            Image.fromarray(crop).resize((target_w, _REC_IMG_HEIGHT), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        norm = (resized / 255.0 - 0.5) / 0.5
        padded = np.zeros((_REC_IMG_HEIGHT, _REC_IMG_MAX_WIDTH, 3), dtype=np.float32)
        padded[:, :target_w, :] = norm
        tensor = np.transpose(padded, (2, 0, 1))[np.newaxis, ...].astype(np.float32)

        input_name = self._rec.get_inputs()[0].name
        preds = np.asarray(self._rec.run(None, {input_name: tensor})[0])[0]  # [T, C]
        return self._ctc_decode(preds)

    def _ctc_decode(self, preds: Any) -> tuple[str, float]:
        """Greedy CTC decode with blank + repeat collapsing; confidence = mean kept-step prob."""

        import numpy as np

        indices = preds.argmax(axis=1)
        probs = preds.max(axis=1)
        chars: list[str] = []
        kept_probs: list[float] = []
        prev = -1
        for t, idx in enumerate(indices):
            idx_i = int(idx)
            if idx_i != 0 and idx_i != prev:  # 0 == CTC blank; collapse repeats
                if idx_i < len(self._charset):
                    chars.append(self._charset[idx_i])
                    kept_probs.append(float(probs[t]))
            prev = idx_i
        text = "".join(chars)
        confidence = float(np.mean(kept_probs)) if kept_probs else 0.0
        return text, confidence
