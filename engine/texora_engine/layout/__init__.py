"""Layout package: detector Protocol + region types, factory, detectors, reading order.

Public surface re-exported here so callers import from ``texora_engine.layout`` without reaching
into submodules. The default detector is the permissive Apache-2.0 ``pp_doclayout_onnx``; the
born-digital structural fast-path needs no model; the AGPL ``doclayout_yolo`` adapter is opt-in
only and deliberately NOT re-exported from the default factory (``R-LIC-2``).
"""

from __future__ import annotations

from texora_engine.layout.base import (
    BBox,
    LayoutDetector,
    LayoutResult,
    Region,
    RegionType,
)
from texora_engine.layout.born_digital import BornDigitalLayoutDetector
from texora_engine.layout.factory import (
    LayoutStageNotConfigured,
    UnknownLayoutEngineError,
    build_layout_detector,
    known_layout_engine_ids,
)
from texora_engine.layout.pp_doclayout_onnx import PpDocLayoutOnnxDetector
from texora_engine.layout.reading_order import order

__all__ = [
    "BBox",
    "BornDigitalLayoutDetector",
    "LayoutDetector",
    "LayoutResult",
    "LayoutStageNotConfigured",
    "PpDocLayoutOnnxDetector",
    "Region",
    "RegionType",
    "UnknownLayoutEngineError",
    "build_layout_detector",
    "known_layout_engine_ids",
    "order",
]
