"""LaTeX -> MathML golden test."""

from __future__ import annotations

from texora_engine.export import latex_to_mathml


def test_frac_converts_to_mathml() -> None:
    mathml = latex_to_mathml(r"\frac{a}{b}")
    assert mathml is not None
    assert mathml.startswith("<math")
    assert "<mfrac>" in mathml
    # Operands present.
    assert ">a<" in mathml
    assert ">b<" in mathml


def test_empty_returns_none() -> None:
    assert latex_to_mathml("") is None
