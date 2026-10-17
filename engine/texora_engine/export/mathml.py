"""LaTeX -> MathML conversion for the snip result.

Uses ``latex2mathml``. No AsciiMath and no OMML/XSLT in M2 — both are deferred to M6
exporters (design §B.9).
"""

from __future__ import annotations

from latex2mathml.converter import convert

from texora_engine.logging_config import get_logger

logger = get_logger("export.mathml")


def latex_to_mathml(latex: str) -> str | None:
    """Convert a (validated) LaTeX string to a MathML string.

    Returns ``None`` when conversion fails rather than raising, so a MathML hiccup never
    turns a successful recognition into a 500.
    """

    text = (latex or "").strip()
    if not text:
        return None
    try:
        return convert(text)
    except Exception as exc:  # latex2mathml can raise on exotic input
        logger.warning("latex2mathml conversion failed: %s", exc)
        return None
