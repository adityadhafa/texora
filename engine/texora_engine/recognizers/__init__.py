"""Recognizer adapters + the engine-agnostic Protocol and pipeline factory."""

from texora_engine.recognizers.base import (
    ConfidenceKind,
    FormulaRecognizer,
    FormulaResult,
    RecognitionStatus,
    RegionContext,
)

__all__ = [
    "ConfidenceKind",
    "FormulaRecognizer",
    "FormulaResult",
    "RecognitionStatus",
    "RegionContext",
]
