"""Idempotent per-page export writer + on-demand fragment concat (design §7).

Each completed page writes its body fragments (``md``/``tex``) + a full JSON page dump via
temp-file + ``os.replace`` (atomic on Windows + POSIX), updates a manifest, and only then is the
page marked ``done`` (the final write is the commit point). The on-demand concat joins committed
fragments in ``page_index`` order and applies the single document wrap exactly once per format so
the output is byte-identical to the M3 whole-document exporter over the committed set; non-``done``
pages emit honest in-order placeholders, never a silent gap (§7.3).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from texora_engine.export.json_export import JsonOptions, document_to_json
from texora_engine.export.latex import LatexOptions, render_page_latex_body
from texora_engine.export.markdown import MarkdownOptions, render_page_markdown
from texora_engine.export.templates import preamble_for
from texora_engine.pipeline.page_result import DocumentResult, PageResult
from texora_engine.settings import Settings

_FRAGMENT_EXTS = {"md": "md", "tex": "tex", "json": "json"}


@dataclass(frozen=True)
class PageOutcome:
    """A page's outcome for the concat builder (committed fragment or honest placeholder)."""

    index: int
    status: str  # done|failed|pending|leased
    error: str | None = None


def job_dir(output_root: Path, job_id: str) -> Path:
    return output_root / job_id


def pages_dir(output_root: Path, job_id: str) -> Path:
    return job_dir(output_root, job_id) / "pages"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _fragment_path(output_root: Path, job_id: str, index: int, fmt: str) -> Path:
    return pages_dir(output_root, job_id) / f"{index}.{_FRAGMENT_EXTS[fmt]}"


def write_page_outputs_idempotent(
    settings: Settings,
    job_id: str,
    page_index: int,
    result: PageResult,
    formats: list[str],
) -> None:
    """Write a page's ``md``/``tex`` body fragments + JSON dump atomically, update the manifest.

    Called in ``runner`` BEFORE ``mark_done`` so a page marked ``done`` always has its artifact on
    disk. Re-running a page (retry) overwrites the same deterministic temp→final path — no append,
    no duplicate. The JSON fragment always carries the full ``PageResult`` (the FTS/search source).
    """

    output_root = Path(settings.job_output_dir)
    md_opts = MarkdownOptions.from_settings(settings)
    tex_opts = LatexOptions.from_settings(settings)

    # Always store the full PageResult JSON (lossless; the DB also stores result_json). The md/tex
    # body fragments are written only for the requested formats.
    _atomic_write_text(
        _fragment_path(output_root, job_id, page_index, "json"),
        result.model_dump_json(indent=2),
    )
    if "md" in formats:
        _atomic_write_text(
            _fragment_path(output_root, job_id, page_index, "md"),
            render_page_markdown(result, md_opts),
        )
    if "tex" in formats:
        _atomic_write_text(
            _fragment_path(output_root, job_id, page_index, "tex"),
            render_page_latex_body(result, tex_opts),
        )
    _update_manifest(output_root, job_id, page_index)


def _manifest_path(output_root: Path, job_id: str) -> Path:
    return job_dir(output_root, job_id) / "manifest.json"


def _update_manifest(output_root: Path, job_id: str, page_index: int) -> None:
    path = _manifest_path(output_root, job_id)
    completed: set[int] = set()
    if path.exists():
        try:
            completed = set(json.loads(path.read_text(encoding="utf-8")).get("completed", []))
        except (OSError, ValueError):
            completed = set()
    completed.add(page_index)
    _atomic_write_text(path, json.dumps({"completed": sorted(completed)}))


def read_manifest(output_root: Path, job_id: str) -> list[int]:
    """Return the sorted list of committed page indices from the manifest (empty if absent)."""

    path = _manifest_path(output_root, job_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(int(i) for i in data.get("completed", []))


# --- on-demand concat (used by the export route in task 4.4) --------------------------------


def _read_fragment(output_root: Path, job_id: str, index: int, fmt: str) -> str | None:
    path = _fragment_path(output_root, job_id, index, fmt)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _placeholder_md(outcome: PageOutcome) -> str:
    err = f": {outcome.error}" if outcome.error else ""
    return f"<!-- texora: page {outcome.index} {outcome.status} (no output){err} -->"


def _placeholder_tex(outcome: PageOutcome) -> str:
    err = f": {outcome.error}" if outcome.error else ""
    return f"% texora: page {outcome.index} {outcome.status} (no output){err}"


def build_markdown(settings: Settings, job_id: str, outcomes: list[PageOutcome]) -> str:
    """Concat committed md fragments + in-order placeholders into one document (§7.1/§7.3).

    Byte-identical to ``document_to_markdown`` over the committed page set (empties filtered). The
    placeholder for a non-committed page is non-empty and always kept (never a silent gap).
    """

    output_root = Path(settings.job_output_dir)
    fragments: list[str] = []
    for outcome in sorted(outcomes, key=lambda o: o.index):
        if outcome.status == "done":
            frag = _read_fragment(output_root, job_id, outcome.index, "md")
            fragments.append(frag if frag is not None else "")
        else:
            fragments.append(_placeholder_md(outcome))
    body = "\n\n".join(f for f in fragments if f != "")
    return body + "\n" if body else "\n"


def build_latex(settings: Settings, job_id: str, outcomes: list[PageOutcome]) -> str:
    """Concat committed tex fragments + in-order placeholders, wrapped once (§7.1/§7.3).

    Byte-identical to ``document_to_latex`` over the committed page set.
    """

    output_root = Path(settings.job_output_dir)
    fragments: list[str] = []
    for outcome in sorted(outcomes, key=lambda o: o.index):
        if outcome.status == "done":
            frag = _read_fragment(output_root, job_id, outcome.index, "tex")
            fragments.append(frag if frag is not None else "")
        else:
            fragments.append(_placeholder_tex(outcome))
    body = "\n\n".join(f for f in fragments if f != "")

    preamble = preamble_for(settings.export_preamble)
    parts = [preamble.rstrip("\n"), "", r"\begin{document}", ""]
    if body:
        parts.append(body)
        parts.append("")
    parts.append(r"\end{document}")
    return "\n".join(parts) + "\n"


def build_json(
    settings: Settings,
    job_id: str,
    source_name: str,
    outcomes: list[PageOutcome],
) -> str:
    """Concat committed JSON page dumps into a document (§7.1 json rule, MEDIUM-3).

    When every requested page is committed, reconstruct a ``DocumentResult`` from the stored
    per-page ``PageResult`` JSON and return ``document_to_json`` (byte-identical to the whole-doc
    exporter + round-trippable). When a non-committed page is present, emit a top-level object whose
    ``pages`` array carries each committed full ``PageResult`` and an in-order placeholder object
    ``{index,status,error}`` for each non-committed index.
    """

    output_root = Path(settings.job_output_dir)
    ordered = sorted(outcomes, key=lambda o: o.index)
    all_committed = all(o.status == "done" for o in ordered)

    if all_committed:
        pages: list[PageResult] = []
        for outcome in ordered:
            frag = _read_fragment(output_root, job_id, outcome.index, "json")
            if frag is None:
                # Treat a missing fragment as not-committed; fall through to the mixed shape.
                all_committed = False
                break
            pages.append(PageResult.model_validate_json(frag))
        if all_committed:
            doc = DocumentResult(source_name=source_name, pages=pages)
            return document_to_json(doc, JsonOptions(indent=2))

    # Mixed shape: committed full PageResults + in-order placeholders.
    page_objs: list[object] = []
    for outcome in ordered:
        if outcome.status == "done":
            frag = _read_fragment(output_root, job_id, outcome.index, "json")
            if frag is not None:
                page_objs.append(json.loads(frag))
                continue
        page_objs.append({"index": outcome.index, "status": outcome.status, "error": outcome.error})
    return json.dumps({"source_name": source_name, "pages": page_objs}, indent=2)
