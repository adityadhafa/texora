"""Golden-file test for the Markdown exporter (task 3.7, design §8.1/§8.3).

The exporter is fed a FIXED, hand-constructed :class:`DocumentResult` (deterministic test data in
``tests/_doc_sample.py``, NOT a mocked production OCR result) and its output is byte-matched against
``golden/doc_sample.md``. A dedicated assertion proves inline ``$...$`` math lands mid-paragraph
(resolves design F5) rather than before/after the block.
"""

from __future__ import annotations

from pathlib import Path

from texora_engine.export import MarkdownOptions, document_to_markdown

from tests._doc_sample import build_sample_document

_GOLDEN = Path(__file__).resolve().parent / "golden" / "doc_sample.md"


def test_markdown_byte_matches_golden() -> None:
    rendered = document_to_markdown(build_sample_document())
    expected = _GOLDEN.read_text(encoding="utf-8")
    assert rendered == expected


def test_inline_math_lands_mid_paragraph() -> None:
    """The $...$ span sits BETWEEN its surrounding text, not before/after the paragraph (F5)."""

    rendered = document_to_markdown(build_sample_document())
    line = next(ln for ln in rendered.splitlines() if ln.startswith("In special relativity"))
    assert line == "In special relativity the energy is $E = mc^2$ which binds mass and energy."
    # The math is strictly inside the sentence: text precedes and follows the $...$ span.
    before, _, after = line.partition("$E = mc^2$")
    assert before.strip() and after.strip()


def test_display_math_carries_equation_tag() -> None:
    rendered = document_to_markdown(build_sample_document())
    assert "$$\nE = m c^2 \\tag{1}\n$$" in rendered


def test_table_is_honest_placeholder_never_fabricated() -> None:
    rendered = document_to_markdown(build_sample_document())
    assert "<!-- table: needs_review (M6) -->" in rendered


def test_needs_review_marker_present_for_uncertain_run() -> None:
    rendered = document_to_markdown(build_sample_document())
    assert "<!-- needs_review: low confidence -->" in rendered
    # The uncertain inline-math span emits NO empty "$$" delimiter (honest, not misleading).
    assert "$$ <!--" not in rendered


def test_review_markers_can_be_disabled() -> None:
    opts = MarkdownOptions(include_review_markers=False)
    rendered = document_to_markdown(build_sample_document(), opts)
    assert "needs_review: low confidence" not in rendered
