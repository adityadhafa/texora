# M4 Design Review — v4 Convergence Pass

Reviewed: `.agents/tasks/m4-design.md` (Design v4).
Scope of this pass: **CONFIRM** the four pre-resolved fixes carried into v4 are present and correct,
and that no settled v3 decision was re-opened. Not a re-litigation of settled items. Only a genuine
NEW buildability blocker in one of the four fixes justifies CHANGES_REQUESTED.

Each fix was checked against the **actual** M2/M3 source, not the design's word:

- `engine/texora_engine/export/markdown.py` (`document_to_markdown`, `_render_page`)
- `engine/texora_engine/export/latex.py` (`document_to_latex`, `_render_page`, `preamble_for`)
- `engine/texora_engine/pipeline/page_result.py` (`PageResult`, `DocumentResult`, Pydantic v2)
- `engine/texora_engine/db/schema.py` (`SCHEMA_VERSION`, `_SCHEMA_SQL`, `migrate`, `connect`)
- `engine/texora_engine/app.py` (`create_app` → `app.state.pipeline_deps = None`)
- `engine/texora_engine/api/pages.py` (`_get_deps`)
- `engine/texora_engine/ingest/pdf.py` + `ingest/images.py` (`open_pdf`, `render_pdf_page`,
  `iter_pdf_pages`, `load_image_pages`)

---

## Verdict

**APPROVED.** 0 HIGH, 0 MEDIUM, 0 NIT.

The four pre-resolved fixes hold against source and introduce no new buildability blocker. The
settled v3 architecture is unchanged in v4.

---

## Confirmation of the four FINAL fixes

### Fix 1 — Empty-fragment filter + byte-equivalence golden (CONFIRMED correct)

Verified against `export/markdown.py` and `export/latex.py`:

- `document_to_markdown` computes `body = "\n\n".join(b for b in blocks if b != "")` over a single
  **flat** block list spanning all pages, then `return body + "\n" if body else "\n"`. Design §7.1
  md concat rule is **byte-identical**: `body = "\n\n".join(f for f in fragments if f != "");
  return body + "\n" if body else "\n"`, with each fragment itself
  `"\n\n".join(b for b in blocks if b != "")`.
- `document_to_latex` computes `body = "\n\n".join(b for b in blocks if b != "")` and assembles
  `parts = [preamble.rstrip("\n"), "", r"\begin{document}", ""]`, appending `body` + `""` only when
  body is non-empty, then `r"\end{document}"`, returning `"\n".join(parts) + "\n"`. Design §7.1 tex
  rule reproduces this assembly exactly, including the `"\n\n"` inter-fragment separator (not `"\n"`)
  and the drop-when-empty behavior.
- The filter `if f != ""` at concat is the precise mirror of the exporter's `if b != ""` over its
  flat list, so a committed page that renders zero blocks (empty fragment) contributes no stray
  `"\n\n"`. Equivalence holds because per-page grouping then empty-filtering the group boundaries is
  associative with the flat filter: no non-empty block is dropped, and only all-empty pages are
  elided — exactly what the whole-document exporter does.
- The golden requirement (§7.1 item 4, §13) mandates a fixture with a committed page rendering an
  empty body, which exercises the filter. Correct.
- The streaming generator (§7.3c) applies the identical filter/joiner and is pinned to produce the
  same byte sequence as the single-shot concat, with a golden asserting it.

No gap. The fix is source-accurate and buildable.

### Fix 2 — Unconditional boot-revert DAO method distinct from the TTL sweeper (CONFIRMED correct)

- `pages_dao.revert_all_leased_for_active_jobs()` is defined as the boot-only method reverting
  **all** `leased` rows of non-terminal jobs regardless of `lease_expires_at`
  (`WHERE status='leased' AND job_id IN (SELECT id FROM job WHERE status IN
  ('running','paused','queued'))`), and is explicitly distinct from
  `revert_expired_leases(now)` (`WHERE status='leased' AND lease_expires_at < :now`) used by the
  periodic sweeper. Both statements are well-formed against the v2 JOB/PAGE DDL (the job status
  domain `running|paused|queued` vs terminal `done|failed|canceled` matches the JOB table).
- `recover_on_boot` (§6.2 step 1) calls the boot-only method; the sweeper (§6.2 tail) calls the
  TTL-gated method. The two paths are not conflated.
- The single-process precondition (one engine process, single-user loopback) is documented in
  §4.3 and §6.2 — a freshly booted process owns no outstanding leases and no other live process can
  hold a valid lease, so an unconditional revert cannot steal a live lease. This makes immediate
  resume deterministic (the §13 interrupt-resume test sets a *future* `lease_expires_at` and asserts
  rows become `pending` at once, which a TTL-only revert could not achieve).
- The `db/` DAO placement and typed-row contract satisfy the "no raw SQL outside db/" rule.

No gap. The fix is correct and buildable.

### Fix 3 — Reference JSON exporter + result_json fidelity contract + golden (CONFIRMED correct)

Verified against `pipeline/page_result.py`:

- `PageResult` and `DocumentResult` are Pydantic v2 `BaseModel`s, so `model_dump_json()` and
  `model_validate_json()` exist. `DocumentResult = {source_name: str, pages: list[PageResult]}`
  matches the design's `document_to_json` output shape exactly.
- `export/json_export.py::document_to_json(doc, opts)` returning
  `doc.model_dump_json(indent=opts.indent)` serializes the full `DocumentResult`/`PageResult`
  losslessly — the design dropped the earlier misleading "compact summary" wording and pins
  `page.result_json == PageResult.model_dump_json()` (the complete model). Consistent with the
  model definition.
- The golden anchor (committed-only) reconstructs a `DocumentResult` by `model_validate`-ing each
  committed page's stored `result_json` and asserts byte-identity to `document_to_json` over the
  in-memory `DocumentResult`, mirroring md/tex; a round-trip assertion
  (`DocumentResult.model_validate_json(out) == doc`) is specified. Correct.
- The mid-job shape (placeholders for non-committed indices) is honestly separated from the typed
  `document_to_json` path and assembled by the concat builder; the committed-only subset remains
  byte-identical. The placeholder object `{"index", "status", "error"}` coexists with real
  serialized `PageResult`s (which carry `index`, `width`, `height`, `dpi`, `kind`, `contents`,
  `status`); the two are distinguishable in practice (a placeholder's `status` is a lease state and
  it lacks the `width/height/dpi/kind/contents` keys). This is a documentation nuance, not a
  buildability blocker — the golden-anchored path (committed-only through `document_to_json`) is
  clean and typed.
- `export/` confirmed to have no JSON module today (only `latex.py`, `markdown.py`, and per design
  `mathml.py`/`templates.py`), so adding `json_export.py` is genuinely additive.

No gap. The fix is source-accurate and buildable.

### Fix 4 — The 3 cheap NITs (CONFIRMED correct)

- **NIT-4 (`get_or_build_deps` tolerates missing/None `pipeline_deps`).** `app.py` `create_app`
  sets `app.state.pipeline_deps = None`, so production always has the attribute; `api/pages._get_deps`
  reads `app.state.{pipeline_deps, settings, model_store}`, builds layout/text/formula engines via
  `load_pipeline_config()` + the build_* factories, caches on `app.state.pipeline_deps`, and raises
  `ModelNotReady`/`TesseractUnavailable`/`UnknownEngineError`/`UnknownTextEngineError` mapped to
  409/500 by the route. The design's `get_or_build_deps(app_state)` is a faithful `Request`-free
  extraction using `getattr(app_state, "pipeline_deps", None)` + `setattr`, correctly handling a
  stub `app_state` in the §13 unit test (which must seed `settings`/`model_store`, as stated).
  `_get_deps` becoming `return get_or_build_deps(request.app.state)` is buildable.
- **NIT-5 (`FtsHit` fields + rowid contract).** `FtsHit = {region_id: str, job_id: str,
  snippet: str, score: float}`, read from the UNINDEXED `region_id`/`job_id` columns plus
  `snippet()`/`bm25()` directly off `region_fts`, never exposing the implicit FTS rowid. Consistent
  with the trigger design keying `region_fts(rowid)` on `region.rowid` (since `region.id` is a TEXT
  PK). Internally consistent and buildable.
- **NIT-6 (`anyio` LICENSES).** The CPU-bound offload uses stdlib
  `concurrent.futures.ThreadPoolExecutor` + `loop.run_in_executor` (shown in the §3.1 loop), so no
  first-party `anyio` import exists and no LICENSES row is owed; `anyio` stays a transitive
  Starlette dependency. Consistent across §1 table/footnote and §12. No gap.

---

## Settled-decision integrity (spot check — no re-opening)

Confirmed the four fixes did not disturb the settled v3 architecture. The migration pattern
(`SCHEMA_VERSION`, `_SCHEMA_SQL` with `CREATE TABLE IF NOT EXISTS`, `user_version`-guarded
`migrate`, `connect` with `check_same_thread=False` + app-level serialization) matches source and
the additive v1→v2 refactor preserves `MODEL`/`SETTING`. `open_pdf`/`render_pdf_page` (indexed)/
`iter_pdf_pages` and the eager `load_image_pages` exist as described; `iter_image_pages` is
correctly new/additive. asyncio runner + global semaphore with `job_page_workers=1`, the lease
machine + TTL + token guards, idempotent temp+`os.replace` export + manifest concat, the Rust
Tauri-event WS bridge, CI-scaled proof, watchdog, and the `status`/`rollup_status` split are all
carried unchanged. No settled item is re-raised here.

---

## Verified Assumptions

1. `document_to_markdown` filters empty blocks with `if b != ""` and applies `body + "\n" if body
   else "\n"` — the per-page md concat matches byte-for-byte. (`export/markdown.py`)
2. `document_to_latex` builds `parts` with `preamble.rstrip("\n")`, `""`, `\begin{document}`, `""`,
   conditional `body`+`""`, `\end{document}`, joined by `"\n"` + trailing `"\n"`, and joins blocks
   with `"\n\n"` filtering empties — the tex concat matches byte-for-byte. (`export/latex.py`)
3. `_render_page` is module-private in both exporters; only whole-document entry points are public —
   the design's new public per-page body emitters are genuinely additive. (both modules)
4. `PageResult`/`DocumentResult` are Pydantic v2 models exposing `model_dump_json` /
   `model_validate_json`; `DocumentResult = {source_name, pages: list[PageResult]}`. The
   `result_json` fidelity contract and `document_to_json` shape are accurate.
   (`pipeline/page_result.py`)
5. `create_app` sets `app.state.pipeline_deps = None`; `_get_deps` reads `app.state.{pipeline_deps,
   settings, model_store}`, builds+caches, and raises the typed errors the route maps — the
   `get_or_build_deps(app_state)` extraction is faithful. (`app.py`, `api/pages.py`)
6. `db/schema.py` has `SCHEMA_VERSION = 1`, `_SCHEMA_SQL` with `CREATE TABLE IF NOT EXISTS
   model/setting`, a `user_version`-guarded `migrate`, and `connect` with `check_same_thread=False`
   — the additive v1→v2 migration and `_V1_SQL == _SCHEMA_SQL` verbatim claims hold.
7. `open_pdf`, `render_pdf_page` (indexed), `iter_pdf_pages`, and eager `load_image_pages` exist;
   `iter_image_pages` does not yet exist (correctly described as new). (`ingest/pdf.py`,
   `ingest/images.py`)

## Unverified / Wrong Assumptions

None. Every source-level claim underpinning the four fixes was read and confirmed. The only item
not independently re-verified by name is the new M4 code itself (DAO methods, `json_export.py`,
`get_or_build_deps`), which does not exist yet by design — its contracts are specified concretely
enough to implement and are consistent with the verified M2/M3 seams.
