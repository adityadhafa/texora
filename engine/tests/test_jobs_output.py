"""Idempotent per-page writer + manifest tests (design §7.2)."""

from __future__ import annotations

from pathlib import Path

from texora_engine.jobs import output
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


def test_idempotent_writer_twice_one_file_same_bytes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    page = build_multipage_document_with_empty().pages[0]
    output.write_page_outputs_idempotent(settings, "j", 0, page, ["md"])
    frag_path = output.pages_dir(Path(settings.job_output_dir), "j") / "0.md"
    first = frag_path.read_bytes()
    output.write_page_outputs_idempotent(settings, "j", 0, page, ["md"])
    files = sorted(f.name for f in output.pages_dir(Path(settings.job_output_dir), "j").glob("0.*"))
    # No stray .tmp left behind; the md + json fragments present, identical bytes.
    assert "0.md.tmp" not in files
    assert frag_path.read_bytes() == first


def test_json_fragment_always_written_even_without_json_format(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    page = build_multipage_document_with_empty().pages[0]
    output.write_page_outputs_idempotent(settings, "j", 0, page, ["md"])  # md only
    json_frag = output.pages_dir(Path(settings.job_output_dir), "j") / "0.json"
    # The full PageResult JSON is always persisted (the search/result source).
    assert json_frag.exists()


def test_manifest_records_completed_in_order(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    doc = build_multipage_document_with_empty()
    output.write_page_outputs_idempotent(settings, "j", 2, doc.pages[2], ["md"])
    output.write_page_outputs_idempotent(settings, "j", 0, doc.pages[0], ["md"])
    assert output.read_manifest(Path(settings.job_output_dir), "j") == [0, 2]
