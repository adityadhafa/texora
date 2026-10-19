"""Fragment-concat byte-equivalence goldens (design §7.1/§7.3, HIGH-1 + MEDIUM-1 + MEDIUM-3).

The per-page fragment concat MUST be byte-identical to the M3 whole-document exporter over the
committed page set — including a committed page that renders an EMPTY body (zero blocks) and a
mid-job committed SUBSET.
"""

from __future__ import annotations

from pathlib import Path

from texora_engine.export import (
    LatexOptions,
    MarkdownOptions,
    document_to_json,
    document_to_latex,
    document_to_markdown,
)
from texora_engine.jobs import output
from texora_engine.jobs.output import PageOutcome
from texora_engine.pipeline.page_result import DocumentResult
from texora_engine.settings import Settings

from tests._doc_sample import build_multipage_document_with_empty


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "db.sqlite",
        job_output_dir=tmp_path / "output",
        figure_asset_dir=tmp_path / "assets",
    )


def _write_pages(settings: Settings, job_id: str, doc: DocumentResult) -> None:
    for page in doc.pages:
        output.write_page_outputs_idempotent(
            settings, job_id, page.index, page, ["md", "tex", "json"]
        )


def _outcomes(doc: DocumentResult) -> list[PageOutcome]:
    return [PageOutcome(index=p.index, status="done") for p in doc.pages]


def test_markdown_concat_byte_identical_full_set_with_empty_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()  # includes an empty-body page (index 1)
    _write_pages(settings, "j", doc)
    concat = output.build_markdown(settings, "j", _outcomes(doc))
    assert concat == document_to_markdown(doc, MarkdownOptions.from_settings(settings))


def test_latex_concat_byte_identical_full_set_with_empty_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    _write_pages(settings, "j", doc)
    concat = output.build_latex(settings, "j", _outcomes(doc))
    assert concat == document_to_latex(doc, LatexOptions.from_settings(settings))


def test_json_concat_byte_identical_and_round_trips(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    _write_pages(settings, "j", doc)
    concat = output.build_json(settings, "j", doc.source_name, _outcomes(doc))
    assert concat == document_to_json(doc)
    # Round-trip: the json export parses back to an equal DocumentResult.
    assert DocumentResult.model_validate_json(concat) == doc


def test_committed_subset_matches_whole_doc_over_that_subset(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    _write_pages(settings, "j", doc)
    # Only pages 0 and 2 committed (page 1 still "pending" mid-job).
    subset_outcomes = [
        PageOutcome(index=0, status="done"),
        PageOutcome(index=1, status="pending"),
        PageOutcome(index=2, status="done"),
    ]
    committed_doc = DocumentResult(source_name=doc.source_name, pages=[doc.pages[0], doc.pages[2]])

    md = output.build_markdown(settings, "j", subset_outcomes)
    # The concat over the committed subset embeds an in-order placeholder for page 1, so it is NOT
    # equal to the whole-doc exporter over just [0,2]. Strip the placeholder line and compare.
    placeholder = "<!-- texora: page 1 pending (no output) -->"
    assert placeholder in md
    stripped = md.replace(placeholder + "\n\n", "").replace("\n\n" + placeholder, "")
    assert stripped == document_to_markdown(committed_doc, MarkdownOptions.from_settings(settings))


def test_mid_job_json_emits_placeholder_in_order(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    _write_pages(settings, "j", doc)
    outcomes = [
        PageOutcome(index=0, status="done"),
        PageOutcome(index=1, status="failed", error="boom"),
        PageOutcome(index=2, status="done"),
    ]
    import json

    parsed = json.loads(output.build_json(settings, "j", doc.source_name, outcomes))
    assert len(parsed["pages"]) == 3
    assert parsed["pages"][1] == {"index": 1, "status": "failed", "error": "boom"}


def test_mid_job_markdown_placeholder_for_failed_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    _write_pages(settings, "j", doc)
    outcomes = [
        PageOutcome(index=0, status="done"),
        PageOutcome(index=1, status="failed", error="boom"),
        PageOutcome(index=2, status="done"),
    ]
    md = output.build_markdown(settings, "j", outcomes)
    assert "<!-- texora: page 1 failed (no output): boom -->" in md
