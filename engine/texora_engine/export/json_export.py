"""Reference JSON exporter — the lossless ``DocumentResult`` serialization (design §7.1, MEDIUM-3).

``document_to_json`` serializes the FULL :class:`DocumentResult` (every page's complete
:class:`PageResult`: region content/latex/mathml, confidences, bboxes, reading order, status) via
Pydantic v2 ``model_dump_json`` — NOT a compact summary. This is the reference the per-page
fragment concat is proven byte-identical against, and the shape stored in ``page.result_json``.
"""

from __future__ import annotations

from texora_engine.pipeline.page_result import DocumentResult


class JsonOptions:
    """Rendering options for :func:`document_to_json`."""

    def __init__(self, *, indent: int | None = 2) -> None:
        self.indent = indent


def document_to_json(doc: DocumentResult, opts: JsonOptions | None = None) -> str:
    """Serialize the full :class:`DocumentResult` losslessly to a JSON string.

    Round-trips: ``DocumentResult.model_validate_json(document_to_json(doc)) == doc``.
    """

    options = opts or JsonOptions()
    return doc.model_dump_json(indent=options.indent)
