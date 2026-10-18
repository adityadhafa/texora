"""LaTeX preamble templates for the ``.tex`` exporter (design §8.2, task 3.7).

Preambles live here as named config (selected by ``settings.export_preamble`` /
``opts.preamble``), not as magic constants scattered in the emitter body. Each template declares a
``\\documentclass`` plus the math/graphics packages the emitted body relies on
(``amsmath, amssymb, graphicx, booktabs`` + UTF-8 input), so the golden ``.tex`` compiles with the
documented preamble. The emitted math only uses the KaTeX/amsmath-supported macro set already
validated by :mod:`texora_engine.ensemble.latex`.
"""

from __future__ import annotations

_ARTICLE_PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
"""

# Named preamble templates. Add a row here to offer another document class; the exporter never
# hard-codes a preamble string inline.
PREAMBLES: dict[str, str] = {
    "article": _ARTICLE_PREAMBLE,
}

DEFAULT_PREAMBLE = "article"


def preamble_for(name: str) -> str:
    """Return the preamble body for ``name``, falling back to the default template.

    Returns the raw ``\\documentclass`` + ``\\usepackage`` block; the exporter appends
    ``\\begin{document}`` / ``\\end{document}`` around the rendered body.
    """

    return PREAMBLES.get(name, PREAMBLES[DEFAULT_PREAMBLE])
