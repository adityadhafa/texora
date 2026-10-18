"""Golden-file + gated-compile tests for the LaTeX exporter (task 3.7, design §8.2/§8.3).

The exporter renders the same FIXED :class:`DocumentResult` (deterministic test data, not mocked
OCR) and byte-matches ``golden/doc_sample.tex``, including the paragraph-with-inline-math so the
in-place ``$...$`` is byte-asserted (design F5).

The real ``latexmk`` exit-0 compile is marked ``@pytest.mark.latex``. On a host with NO TeX
toolchain it **xfail-skips with a recorded reason** (developer convenience); the CI
``m3-latex-compile`` job provisions TinyTeX/texlive and runs it with no-skip so a non-compiling
``.tex`` fails CI. The test is NEVER deleted or silently passed — an absent toolchain is explicit.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from texora_engine.export import LatexOptions, document_to_latex

from tests._doc_sample import build_sample_document

_GOLDEN = Path(__file__).resolve().parent / "golden" / "doc_sample.tex"


def _latexmk() -> str | None:
    """Absolute path to ``latexmk`` if a TeX toolchain is installed, else None."""

    return shutil.which("latexmk")


def test_latex_byte_matches_golden() -> None:
    rendered = document_to_latex(build_sample_document())
    expected = _GOLDEN.read_text(encoding="utf-8")
    assert rendered == expected


def test_latex_inline_math_in_place() -> None:
    """Inline $...$ sits inside the sentence, proving the run interleaving (design F5)."""

    rendered = document_to_latex(build_sample_document())
    line = next(ln for ln in rendered.splitlines() if ln.startswith("In special relativity"))
    assert line == "In special relativity the energy is $E = mc^2$ which binds mass and energy."


def test_latex_preamble_and_structure() -> None:
    rendered = document_to_latex(build_sample_document())
    # Preamble template (article) + the math/graphics packages the body relies on.
    assert rendered.startswith("\\documentclass{article}")
    for pkg in ("amsmath", "amssymb", "graphicx", "booktabs"):
        assert f"\\usepackage{{{pkg}}}" in rendered
    assert "\\begin{document}" in rendered and "\\end{document}" in rendered
    # A numbered display equation (equation, not equation*) since an equation number is attached.
    assert "\\begin{equation}\nE = m c^2\n\\end{equation}" in rendered
    # Honest, compilable review notes live on their OWN lines (no mid-sentence '%').
    assert "An unresolved fragment  remains." in rendered
    assert "% needs_review: low confidence" in rendered


def test_latex_table_is_comment_never_fabricated() -> None:
    rendered = document_to_latex(build_sample_document())
    assert "% table: needs_review (M6)" in rendered
    assert "\\begin{tabular}" not in rendered


def test_latex_preamble_selectable() -> None:
    # Unknown preamble name falls back to the default template rather than crashing.
    rendered = document_to_latex(build_sample_document(), LatexOptions(preamble="unknown_template"))
    assert rendered.startswith("\\documentclass{article}")


@pytest.mark.latex
def test_golden_tex_compiles_with_latexmk(tmp_path: Path) -> None:
    """Real ``latexmk -pdf`` exit-0 compile of the golden .tex.

    xfail-skips locally when no TeX toolchain is present (recorded reason); the CI
    ``m3-latex-compile`` job provisions the toolchain and asserts exit 0 with no skip.
    """

    latexmk = _latexmk()
    if latexmk is None:
        pytest.xfail(
            "no TeX toolchain (latexmk) on this host; asserted in the CI m3-latex-compile job"
        )

    tex_src = _GOLDEN.read_text(encoding="utf-8")
    work = tmp_path / "doc_sample.tex"
    work.write_text(tex_src, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - fixed args, trusted golden input
        [latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", work.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "doc_sample.pdf").exists()
