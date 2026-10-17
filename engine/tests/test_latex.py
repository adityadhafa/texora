"""LaTeX validate + normalize golden tests (AC-5 engine side)."""

from __future__ import annotations

import pytest
from texora_engine.ensemble import validate_and_normalize
from texora_engine.recognizers.base import RecognitionStatus


@pytest.mark.parametrize(
    "latex",
    [
        r"\frac{a}{b}",
        r"x^2 + y^2 = z^2",
        r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}",
        r"\alpha + \beta = \gamma",
        r"\left( \frac{a}{b} \right)",
        r"\begin{matrix} a & b \\ c & d \end{matrix}",
    ],
)
def test_valid_latex_passes(latex: str) -> None:
    _, status = validate_and_normalize(latex)
    assert status == RecognitionStatus.OK


@pytest.mark.parametrize(
    "latex",
    [
        r"\frac{a}{b",  # unbalanced brace
        r"\left( x",  # unmatched \left
        r"\begin{matrix} a & b",  # unmatched \begin
        r"\begin{matrix} a \end{bmatrix}",  # mismatched env names
    ],
)
def test_structurally_invalid_is_failed(latex: str) -> None:
    _, status = validate_and_normalize(latex)
    assert status == RecognitionStatus.FAILED


def test_empty_is_failed() -> None:
    _, status = validate_and_normalize("")
    assert status == RecognitionStatus.FAILED


def test_unknown_macro_is_needs_review() -> None:
    _, status = validate_and_normalize(r"\notakatexcommand{x}")
    assert status == RecognitionStatus.NEEDS_REVIEW


def test_unknown_environment_is_needs_review() -> None:
    _, status = validate_and_normalize(r"\begin{notanenv} x \end{notanenv}")
    assert status == RecognitionStatus.NEEDS_REVIEW


def test_normalization_preserves_validity() -> None:
    # \dfrac -> \frac, extra spaces collapsed; still valid.
    normalized, status = validate_and_normalize(r"\dfrac{a}{b}   +   c")
    assert status == RecognitionStatus.OK
    assert "\\dfrac" not in normalized
    assert "\\frac" in normalized
    # Re-validating the normalized output still passes.
    _, status2 = validate_and_normalize(normalized)
    assert status2 == RecognitionStatus.OK
