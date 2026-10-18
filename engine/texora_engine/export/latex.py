"""LaTeX exporter — compilable ``.tex`` from a DocumentResult (design §8.2, task 3.7).

``document_to_latex`` emits a self-contained ``.tex`` document: a preamble template selected by
``opts.preamble`` (``article`` default, see :mod:`texora_engine.export.templates`) followed by a
body that preserves reading order, in-paragraph inline math, numbered/unnumbered display math,
figures, and honest ``% needs_review`` comments for anything the pipeline could not recognize.

The same ordered :class:`InlineRun` interleaving as the Markdown exporter places inline ``$...$``
math at its true position inside a paragraph (design F5). The emitted math uses only the
KaTeX/amsmath-supported macro set already validated upstream, so the golden ``.tex`` compiles under
the documented preamble.
"""

from __future__ import annotations

from texora_engine.export.templates import DEFAULT_PREAMBLE, preamble_for
from texora_engine.layout.base import RegionType
from texora_engine.pipeline.page_result import (
    DocumentResult,
    InlineRun,
    PageResult,
    RegionContent,
    RunKind,
)
from texora_engine.recognizers.base import RecognitionStatus
from texora_engine.settings import Settings

# LaTeX special characters that must be escaped in body TEXT runs (never inside math).
_TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


class LatexOptions:
    """Rendering options for :func:`document_to_latex` (design §8.2)."""

    def __init__(
        self,
        *,
        preamble: str = DEFAULT_PREAMBLE,
        emit_tags: bool = True,
        include_review_markers: bool = True,
        figure_asset_dir: str = "assets",
    ) -> None:
        self.preamble = preamble
        self.emit_tags = emit_tags
        self.include_review_markers = include_review_markers
        self.figure_asset_dir = figure_asset_dir

    @classmethod
    def from_settings(cls, settings: Settings) -> LatexOptions:
        """Build options from engine settings (preamble template + figure asset dir)."""

        return cls(
            preamble=settings.export_preamble,
            figure_asset_dir=str(settings.figure_asset_dir).replace("\\", "/"),
        )


def _escape_text(text: str) -> str:
    """Escape LaTeX-special characters in a plain-text run."""

    out: list[str] = []
    for ch in text:
        out.append(_TEX_ESCAPES.get(ch, ch))
    return "".join(out)


def document_to_latex(doc: DocumentResult, opts: LatexOptions | None = None) -> str:
    """Render ``doc`` to a compilable ``.tex`` string (design §8.2).

    Output ends with a single trailing newline for byte-stable goldens.
    """

    options = opts or LatexOptions()
    blocks: list[str] = []
    for page in doc.pages:
        blocks.extend(_render_page(page, options))
    body = "\n\n".join(b for b in blocks if b != "")

    preamble = preamble_for(options.preamble)
    parts = [preamble.rstrip("\n"), "", r"\begin{document}", ""]
    if body:
        parts.append(body)
        parts.append("")
    parts.append(r"\end{document}")
    return "\n".join(parts) + "\n"


def _render_page(page: PageResult, opts: LatexOptions) -> list[str]:
    blocks: list[str] = []
    contents = page.contents
    for i, content in enumerate(contents):
        rtype = content.region.type
        if rtype == RegionType.EQUATION_NUMBER:
            prev = contents[i - 1].region.type if i > 0 else None
            if prev == RegionType.DISPLAY_MATH:
                continue
            blocks.append(_render_paragraph(content, opts))
        elif rtype == RegionType.TITLE:
            blocks.append(_render_title(content, opts))
        elif rtype == RegionType.DISPLAY_MATH:
            number = _following_equation_number(contents, i)
            blocks.append(_render_display_math(content, number, opts))
        elif rtype == RegionType.FIGURE:
            blocks.append(_render_figure(page, content, opts))
        elif rtype == RegionType.TABLE:
            blocks.append(_render_table(content, opts))
        elif rtype == RegionType.CODE:
            blocks.append(_render_code(content, opts))
        elif rtype == RegionType.INLINE_MATH and not content.inlines:
            blocks.append(_render_standalone_inline_math(content, opts))
        else:
            blocks.append(_render_paragraph(content, opts))
    return blocks


def _render_title(content: RegionContent, opts: LatexOptions) -> str:
    text, notes = _render_inlines(content.inlines, opts)
    if not text:
        text = _escape_text(content.text or "")
    line = f"\\section{{{text}}}"
    marker = _review_marker(content.status, content.detail, opts)
    lines = [line, *notes]
    if marker:
        lines.append(marker)
    return "\n".join(lines)


def _render_paragraph(content: RegionContent, opts: LatexOptions) -> str:
    text, notes = _render_inlines(content.inlines, opts)
    if not text and content.text:
        text = _escape_text(content.text)
    marker = _review_marker(content.status, content.detail, opts)
    lines = [text] if text else []
    # Inline review notes go on their OWN comment lines AFTER the paragraph so a mid-line '%'
    # never comments out the rest of the sentence (which would corrupt the compiled output).
    lines.extend(notes)
    if marker:
        lines.append(marker)
    return "\n".join(lines) if lines else ""


def _render_inlines(inlines: list[InlineRun], opts: LatexOptions) -> tuple[str, list[str]]:
    """Concatenate ordered runs so inline math lands at its true position (design F5).

    Returns ``(text, notes)`` where ``notes`` are honest full-line ``% needs_review`` comments for
    any uncertain inline-math span, kept OUT of the sentence body so they never comment out text.
    """

    parts: list[str] = []
    notes: list[str] = []
    for run in inlines:
        if run.kind == RunKind.TEXT:
            parts.append(_escape_text(run.text or ""))
        else:  # MATH -> inline $...$ at its real offset
            latex = (run.latex or "").strip()
            if latex:
                parts.append(f"${latex}$")
            marker = _review_marker(run.status, run.detail, opts)
            if marker:
                notes.append(marker)
    return "".join(parts).strip(), notes


def _render_display_math(content: RegionContent, number: str | None, opts: LatexOptions) -> str:
    latex = (content.latex or "").strip()
    numbered = bool(number) and opts.emit_tags
    env = "equation" if numbered else "equation*"
    body = f"\\begin{{{env}}}\n{latex}\n\\end{{{env}}}"
    marker = _review_marker(content.status, content.detail, opts)
    return f"{body}\n{marker}" if marker else body


def _render_standalone_inline_math(content: RegionContent, opts: LatexOptions) -> str:
    latex = (content.latex or "").strip()
    body = f"${latex}$"
    marker = _review_marker(content.status, content.detail, opts)
    return f"{body}\n{marker}" if marker else body


def _render_figure(page: PageResult, content: RegionContent, opts: LatexOptions) -> str:
    asset = content.detail if content.status == RecognitionStatus.OK and content.detail else None
    if asset is None:
        asset = f"fig_p{page.index}.png"
    ref = f"\\includegraphics{{{opts.figure_asset_dir}/{asset}}}"
    if content.status != RecognitionStatus.OK:
        marker = _review_marker(content.status, content.detail, opts)
        return f"{ref}\n{marker}" if marker else ref
    return ref


def _render_table(content: RegionContent, opts: LatexOptions) -> str:
    # Honest placeholder — table structure recognition is M6, never a fabricated tabular.
    return "% table: needs_review (M6)"


def _render_code(content: RegionContent, opts: LatexOptions) -> str:
    if content.text:
        text = content.text
    else:
        text, _ = _render_inlines(content.inlines, opts)
    return f"\\begin{{verbatim}}\n{text}\n\\end{{verbatim}}"


def _following_equation_number(contents: list[RegionContent], i: int) -> str | None:
    """Digits of the EQUATION_NUMBER reading-order placed right after index ``i`` (or None)."""

    if i + 1 >= len(contents):
        return None
    nxt = contents[i + 1]
    if nxt.region.type != RegionType.EQUATION_NUMBER:
        return None
    raw = (nxt.text or "").strip()
    digits = raw.strip("()").strip()
    return digits or None


def _review_marker(status: RecognitionStatus, detail: str | None, opts: LatexOptions) -> str:
    """Honest ``% comment`` for a non-ok region/run; empty when ok or markers disabled."""

    if not opts.include_review_markers or status == RecognitionStatus.OK:
        return ""
    label = "needs_review" if status == RecognitionStatus.NEEDS_REVIEW else "failed"
    reason = f": {detail}" if detail else ""
    return f"% {label}{reason}"
