"""Recognizer Protocol + shared result-type tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from texora_engine.recognizers import (
    ConfidenceKind,
    FormulaResult,
    RecognitionStatus,
)


def test_recognition_status_values() -> None:
    assert RecognitionStatus.OK.value == "ok"
    assert RecognitionStatus.NEEDS_REVIEW.value == "needs_review"
    assert RecognitionStatus.FAILED.value == "failed"


def test_formula_result_confidence_bounds() -> None:
    ok = FormulaResult(latex="x", confidence=0.5, engine_id="pix2tex")
    assert 0.0 <= ok.confidence <= 1.0

    with pytest.raises(ValidationError):
        FormulaResult(latex="x", confidence=1.5, engine_id="pix2tex")
    with pytest.raises(ValidationError):
        FormulaResult(latex="x", confidence=-0.1, engine_id="pix2tex")


def test_formula_result_defaults_are_honest() -> None:
    r = FormulaResult(engine_id="pix2tex")
    assert r.latex == ""
    assert r.confidence == 0.0
    assert r.confidence_kind == ConfidenceKind.UNAVAILABLE
    assert r.status == RecognitionStatus.OK
