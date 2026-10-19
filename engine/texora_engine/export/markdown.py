"""Markdown exporter — the headline PDF -> Markdown output (design §8.1, task 3.7).

``document_to_markdown`` walks a :class:`DocumentResult`'s pages and regions **in reading order**
and emits clean Markdown with math. The one hard rule that makes the headline feature work is the
ordered :class:`InlineRun` interleaving: a paragraph's ``inlines`` list carries TEXT and MATH runs
in their true left-to-right order, so inline ``$...$`` math lands at its real position *inside* the
paragraph's flow (resolves design F5), not merely before or after the block.

Honesty invariants (carried from the assembler, re-stated here):

* Nothing is fabricated. A region/run whose ``status != ok`` is still emitted (its best-effort
  LaTeX/text, possibly empty) **followed by** an honest ``<!-- needs_review: ... -->`` marker.
* A detected-but-unrecognized TABLE becomes an honest placeholder comment, never an invented table.
* No region is silently dropped.
"""

from __future__ import annotations

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


class MarkdownOptions:
    """Rendering options for :func:`document_to_markdown` (design §8.1).

    Defaults mirror the shipped ``pipeline.yaml`` / settings values; no magic constants live in the
    emitter body.
    """

    def __init__(
        self,
        *,
        math_delimiters: str = "dollar",
        emit_tags: bool = True,
        include_review_markers: bool = True,
        figure_asset_dir: str = "assets",
    ) -> None:
        self.math_delimiters = math_delimiters
        self.emit_tags = emit_tags
        self.include_review_markers = include_review_markers
        self.figure_asset_dir = figure_asset_dir

    @classmethod
    def from_settings(cls, settings: Settings) -> MarkdownOptions:
        """Build options from engine settings (figure asset dir)."""

        return cls(figure_asset_dir=str(settings.figure_asset_dir).replace("\\", "/"))


def document_to_markdown(doc: DocumentResult, opts: MarkdownOptions | None = None) -> str:
    """Render ``doc`` to a Markdown string with inline/display math (design §8.1).

    Pages are separated by a blank line; blocks within a page are separated by a blank line.
    The output always ends with a single trailing newline for byte-stable goldens.
    """

    options = opts or MarkdownOptions()
    blocks: list[str] = []
    for page in doc.pages:
        blocks.extend(_render_page(page, options))
    body = "\n\n".join(b for b in blocks if b != "")
    return body + "\n" if body else "\n"


def render_page_markdown(page: PageResult, opts: MarkdownOptions | None = None) -> str:
    """Render ONE page's blocks to a Markdown body fragment (design §7.1, M4).

    A body fragment: the page's blocks joined with ``"\\n\\n"`` with NO document wrapper and NO
    leading/trailing-newline normalization. Empty blocks are filtered exactly as
    :func:`document_to_markdown` filters its flat block list, so concatenating these fragments is
    byte-identical to the whole-document exporter (the empty-fragment filter at concat handles a
    page that renders zero blocks).
    """

    options = opts or MarkdownOptions()
    return "\n\n".join(b for b in _render_page(page, options) if b != "")


def _render_page(page: PageResult, opts: MarkdownOptions) -> list[str]:
    """Render one page's regions (already in reading order) to Markdown blocks."""

    blocks: list[str] = []
    seen_title = False
    contents = page.contents
    for i, content in enumerate(contents):
        rtype = content.region.type
        if rtype == RegionType.EQUATION_NUMBER:
            # Equation numbers bind to the preceding display equation (emitted via \tag there);
            # reading-order places them immediately after their DISPLAY_MATH. A stray number with
            # no preceding display equation is kept as an honest paragraph, never dropped.
            prev = contents[i - 1].region.type if i > 0 else None
            if prev == RegionType.DISPLAY_MATH:
                continue
            blocks.append(_render_paragraph(content, opts))
        elif rtype == RegionType.TITLE:
            blocks.append(_render_title(content, level=1 if not seen_title else 2, opts=opts))
            seen_title = True
        elif rtype == RegionType.DISPLAY_MATH:
            number = _following_equation_number(contents, i)
            blocks.append(_render_display_math(content, number, opts))
        elif rtype == RegionType.FIGURE:
            blocks.append(_render_figure(page, content, opts))
        elif rtype == RegionType.TABLE:
            blocks.append(_render_table(content, opts))
        elif rtype == RegionType.LIST:
            blocks.append(_render_list(content, opts))
        elif rtype == RegionType.CODE:
            blocks.append(_render_code(content, opts))
        elif rtype == RegionType.INLINE_MATH and not content.inlines:
            blocks.append(_render_standalone_inline_math(content, opts))
        else:
            # PARAGRAPH / CAPTION / FOOTNOTE / HEADER / FOOTER / UNKNOWN / INLINE_MATH-with-inlines
            blocks.append(_render_paragraph(content, opts))
    return blocks


def _render_title(content: RegionContent, level: int, opts: MarkdownOptions) -> str:
    text = _render_inlines(content.inlines, opts) or (content.text or "")
    marker = _review_marker(content.status, content.detail, opts)
    hashes = "#" * level
    line = f"{hashes} {text}".rstrip()
    return f"{line}\n{marker}" if marker else line


def _render_paragraph(content: RegionContent, opts: MarkdownOptions) -> str:
    text = _render_inlines(content.inlines, opts)
    if not text and content.text:
        text = content.text
    marker = _review_marker(content.status, content.detail, opts)
    if marker and text:
        return f"{text}\n{marker}"
    return marker or text


def _render_inlines(inlines: list[InlineRun], opts: MarkdownOptions) -> str:
    """Concatenate ordered runs so inline math lands at its true position (design F5)."""

    parts: list[str] = []
    for run in inlines:
        if run.kind == RunKind.TEXT:
            parts.append(run.text or "")
        else:  # MATH run -> inline $...$ at its real offset
            latex = (run.latex or "").strip()
            marker = _review_marker(run.status, run.detail, opts)
            if latex:
                parts.append(f"${latex}$")
                if marker:
                    parts.append(marker)
            elif marker:
                # Uncertain/failed span with no usable LaTeX: honest marker only, no empty "$$".
                parts.append(marker)
    return "".join(parts).strip()


def _render_display_math(content: RegionContent, number: str | None, opts: MarkdownOptions) -> str:
    latex = (content.latex or "").strip()
    tag = f"\\tag{{{number}}}" if number and opts.emit_tags else ""
    if tag:
        body = f"$$\n{latex} {tag}\n$$"
    else:
        body = f"$$\n{latex}\n$$"
    marker = _review_marker(content.status, content.detail, opts)
    return f"{body}\n{marker}" if marker else body


def _render_standalone_inline_math(content: RegionContent, opts: MarkdownOptions) -> str:
    latex = (content.latex or "").strip()
    body = f"${latex}$"
    marker = _review_marker(content.status, content.detail, opts)
    return f"{body}\n{marker}" if marker else body


def _render_figure(page: PageResult, content: RegionContent, opts: MarkdownOptions) -> str:
    # The assembler records the saved asset filename in ``detail`` on success.
    asset = content.detail if content.status == RecognitionStatus.OK and content.detail else None
    if asset is None:
        asset = f"fig_p{page.index}.png"
    ref = f"![figure]({opts.figure_asset_dir}/{asset})"
    if content.status != RecognitionStatus.OK:
        marker = _review_marker(content.status, content.detail, opts)
        return f"{ref}\n{marker}" if marker else ref
    return ref


def _render_table(content: RegionContent, opts: MarkdownOptions) -> str:
    # Honest placeholder — a detected table whose structure is recognized in M6, never fabricated.
    return "<!-- table: needs_review (M6) -->"


def _render_list(content: RegionContent, opts: MarkdownOptions) -> str:
    text = _render_inlines(content.inlines, opts) or (content.text or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    rendered = "\n".join(f"- {ln.strip()}" for ln in lines) if lines else f"- {text}".rstrip()
    marker = _review_marker(content.status, content.detail, opts)
    return f"{rendered}\n{marker}" if marker else rendered


def _render_code(content: RegionContent, opts: MarkdownOptions) -> str:
    text = content.text or _render_inlines(content.inlines, opts)
    return f"```\n{text}\n```"


def _following_equation_number(contents: list[RegionContent], i: int) -> str | None:
    """Return the digits of the EQUATION_NUMBER that reading-order placed right after index ``i``.

    Reading-order binds a right-margin ``(n)`` immediately after its display equation, so the
    exporter reads that sibling region's text and renders it as ``\\tag{n}`` on the equation. The
    surrounding parentheses are stripped (``(1)`` -> ``1``).
    """

    if i + 1 >= len(contents):
        return None
    nxt = contents[i + 1]
    if nxt.region.type != RegionType.EQUATION_NUMBER:
        return None
    raw = (nxt.text or "").strip()
    digits = raw.strip("()").strip()
    return digits or None


def _review_marker(status: RecognitionStatus, detail: str | None, opts: MarkdownOptions) -> str:
    """Honest inline marker for a non-ok region/run; empty when ok or markers disabled."""

    if not opts.include_review_markers or status == RecognitionStatus.OK:
        return ""
    label = "needs_review" if status == RecognitionStatus.NEEDS_REVIEW else "failed"
    reason = f": {detail}" if detail else ""
    return f"<!-- {label}{reason} -->"
