# M3 Design Review — PDF pipeline (v2)

Reviewer: design-review subagent (fresh read, no authoring context).
Design under review: `.agents/tasks/m3-design.md` (Design v2, claims F1–F7 from the prior
review resolved).
Verdict: **APPROVED** (0 HIGH, 0 MEDIUM; NITs only).

The design is a revision that explicitly resolves a prior review's F1–F7. I re-read it fresh and
independently verified every load-bearing claim against the actual M2 source in the worktree and
against official package sources (PyPI). The hard M3 gates are all met. Remaining findings are
NITs that do not block implementation.

---

## Gate checklist (the blocking criteria)

1. **Layout-model license RESOLVED + permissive default — PASS.**
   DocLayout-YOLO verified AGPL-3.0 from the official source (PyPI `doclayout-yolo` 0.0.4:
   `license: AGPL-3.0`, classifier `GNU Affero General Public License v3 or later`; its
   `ultralytics` 8.4.x lineage: AGPL-3.0, confirmed). The design marks it **opt-in only, never
   default, not bundled, and intentionally absent from `_REGISTRY`** (§2.1, §3, §6.2, §16). The
   shipped default is a two-path permissive stage: the born-digital structural fast-path
   (pypdfium2 text layer, no model) and `pp_doclayout_onnx` (PP-DocLayout weights via ONNX
   Runtime), both Apache-2.0/BSD. No AGPL/non-commercial engine sits in the default path.

2. **pypdfium2 default, PyMuPDF opt-in — PASS.**
   pypdfium2 5.14.0 verified BSD-3-Clause/Apache-2.0 (PyPI). PyMuPDF (AGPL) adds no M3 dependency
   and stays in the deferred/opt-in section (§1, §3.2, §16). M3 adds no PyMuPDF import.

3. **PP-OCRv5 default permissive + Tesseract fallback — PASS.**
   paddleocr 3.7.0 verified Apache-2.0; pytesseract 0.3.13 verified Apache-2.0 (PyPI). PP-OCRv5 is
   the default text recognizer run through ONNX Runtime (MIT), Tesseract is the named Apache-2.0
   fallback with EN+ID first-class (§1, §3.2, §7.2).

4. **Protocols + factory + pipeline.yaml; UI/API engine-agnostic; M2 pix2tex REUSED — PASS.**
   New `layout/base.py LayoutDetector` and the added `recognizers/base.py TextRecognizer` mirror
   the verified M2 `FormulaRecognizer` Protocol (stable `id`, `model_ids`, pure typed
   `detect`/`recognize`, errors caught internally). Factories are modeled on the real
   `recognizers/factory.py`, selected by id from `pipeline.yaml`. Formula regions reuse the M2
   `build_formula_recognizer`/`Pix2TexFormulaRecognizer` unchanged (§0, §2.1, §7.4). API/UI depend
   only on the Protocols + typed `PageResult`.

5. **No mocked OCR / no fabrication; SQLite via db/ — PASS.**
   Every adapter returns typed empty/failed results and never raises; the assembler rolls up
   status `failed > needs_review > ok`; unsupported regions (TABLE, HANDWRITING) are marked
   `needs_review` with a `detail`, never fabricated (§0, §6.1, §7.4, §12.2). Recognition tests use
   real fixtures; only export goldens use a constructed `DocumentResult` as deterministic test
   input (not a mocked production path). M3's synchronous path needs little SQLite; model rows
   persist through the existing store/`db/` DAOs (verified: `ModelStore` uses `db` DAOs, no raw
   SQL).

6. **Each 3.1–3.7 has a concrete, testable plan + named fixtures — PASS.**
   §10 names every fixture (`born_digital_math.pdf`, `scanned_page.png`, `text_en.png`,
   `text_id.png`, `skewed_scan.png`, `two_column.json`, `inline_math_para.json`,
   `golden/doc_sample.{md,tex}`); §13/§14 map each task's `done:` to a real test, and the
   `done:` strings match `tasks.md` 3.1–3.7 verbatim. The 3.7 `LaTeX compiles` gate is made
   non-skippable in CI via a provisioned-toolchain `latexmk` exit-0 job.

---

## Findings

1. **NIT — Adaptive-DPI small-font trigger mixes units/terms (§4.2).**
   The re-render rule reads "median glyph cap-height below `small_font_px` (12 px)", but the
   born-digital signal is derived from the text layer whose spans carry `font_size_pt` (points),
   while the threshold is in rendered pixels. The pt→px conversion at the current effective DPI
   (`px = pt * dpi / 72`) is implied but not written, and "glyph height" vs "cap-height" are used
   interchangeably.
   *Fix:* state the comparison explicitly, e.g. "re-render once when
   `median_span_font_pt * base_dpi / 72 < small_font_px`," and pick one term (cap-height) with how
   it is estimated for the scanned connected-component path. The §8/§13 unit test already covers
   this logic, so this is a wording-precision NIT, not a gap.

2. **NIT — Born-digital math heuristic (`is_mathish`) has no concrete rule set (§4.2, §6.3, §6.5).**
   The born-digital path is the shipped default for born-digital PDFs and its inline/display math
   split depends entirely on the `is_mathish` heuristic ("glyph-run gaps, math-font / Unicode-math
   detection, isolated display-equation lines, trailing `(n)`"). The concrete signals/thresholds
   are not pinned.
   *Fix:* acceptable to leave thresholds provisional (tuned in M7) since the `born_digital_math.pdf`
   fixture integration test validates the outcome, but name the minimal signal set the first
   implementation must include (math Unicode-block ratio, italic/math-font flag from the span,
   isolation on its own line, right-margin `(n)`), so the fixture test is not the only spec.

3. **NIT — Model-path inline-math "non-math remainder" crop is unspecified (§6.5).**
   On the scanned/model path the assembler "runs text OCR on the non-math remainder and pix2tex on
   the math box." How the remainder is produced (mask the inline-math sub-boxes out of the block
   crop, or OCR the whole block then splice) is not defined, and the two produce different
   `inlines` orderings.
   *Fix:* specify one: OCR the full text block, then for each contained `INLINE_MATH` box replace
   the overlapping OCR span(s) with a `MATH` run ordered by x within the line. This matches the
   stated "ordered by x (same-line) then y" rule and keeps a single deterministic path.

4. **NIT — `RegionContext.source` has no `"page"` producer wired (§7.1, §7.4).**
   The design reuses the M2 `RegionContext` (verified fields: `is_display`, `device`,
   `source="snip"`) for text/formula recognition in the page pipeline, and §6.1 comments reference a
   "`confidence_kind` analog" for born-digital structural confidence, but the assembler section
   never shows constructing `RegionContext(..., source="page")`.
   *Fix:* note that the assembler builds `RegionContext(is_display=..., device=settings.device,
   source="page")` per region, so provenance logging distinguishes page vs snip. Pure
   documentation; the field already exists.

5. **NIT — `pipeline.yaml` top-level `ingest:` block vs `PipelineConfig` shape (§9, §11).**
   The verified `pipeline_config.PipelineConfig` has only `version` + `stages`; §9's YAML adds a
   top-level `ingest:` block (DPI + preprocess toggles) that today would be dropped silently by
   Pydantic's `extra` default on `PipelineConfig` unless the new `IngestConfig` field is actually
   added. The design says it extends `pipeline_config.py`, which is correct, but the ownership of
   these values is split between `pipeline.yaml` (§9) and `settings.py` (§11) without a stated
   precedence.
   *Fix:* state which wins when both are present (recommend: `pipeline.yaml` ingest block is the
   source of truth, mirrored into settings; or load ingest config solely from
   `pipeline_config.IngestConfig`) so there is one home for `base_dpi`/preprocess toggles, per the
   project's "no magic constants, one config home" rule.

6. **NIT — Default-layout ONNX artifact is a provisional pin with a contingency (§1.1, §3.1, §16).**
   The permissive default depends on an official PP-DocLayout/PP-OCRv5 **ONNX export** existing at a
   stable URL, else the Apache-2.0 `rapid-layout`/`rapidocr-onnxruntime` redistribution. I confirmed
   those redistributors exist and are Apache-2.0 (PyPI: `rapid-layout` 1.2.1, `rapidocr-onnxruntime`
   1.4.4), and that paddleocr/paddlex code is Apache-2.0 — so the *license verdict* for the default
   is resolved and permissive, which is what the gate requires. The specific artifact URL+SHA is
   honestly deferred to pin-on-first-fetch (same approved pattern as M2 pix2tex).
   *Fix:* none required for the gate. At adoption, confirm the exact ONNX asset (official export or
   the named redistributor) and that its bundled weights are the Apache-2.0 PP family, then pin
   URL+SHA and add the `docs/LICENSES.md` rows already drafted in §16.

---

## Verified Assumptions (checked against real source / official registries)

- `recognizers/factory.py build_formula_recognizer` resolves `entry.model_ids[0]` via
  `model_store.require_ready(...)` and calls `spec.file_path("weights.pth")` — **confirmed**; the
  design's §2.1 claim that the M2 factory resolves only the first id (and that M3 must resolve all
  of `model_ids`) is accurate.
- `models/registry.py ModelSpec.file_path(name)` raises `KeyError` on an unpinned name —
  **confirmed**; the §2.1 "hard contract / `file_path(name)` `KeyError`s on unpinned name" claim is
  correct.
- `models/store.py ModelStore.require_ready` returns a `ModelSpec` and raises `ModelNotReady` at
  build/resolve time (not inside `recognize`) — **confirmed**; this validates §7.2.1's placing of
  the Tesseract-fallback decision in `build_text_recognizer`.
- `recognizers/base.py` exposes `RecognitionStatus {ok,needs_review,failed}`, `ConfidenceKind`,
  `RegionContext {is_display,device,source}`, and a `@runtime_checkable FormulaRecognizer` Protocol
  with `id`, `model_ids`, pure `recognize` that must catch its own errors — **confirmed**; the new
  `TextRecognizer`/`LayoutDetector` Protocols faithfully mirror it.
- `Pix2TexFormulaRecognizer(checkpoint_path, resizer_path, device)` with `id="pix2tex"`,
  `model_ids=("pix2tex",)`, errors mapped to `status=FAILED` (never raises), confidence honestly
  `unavailable` — **confirmed**; the "reuse M2 pix2tex as-is" claim holds.
- `ensemble.validate_and_normalize` and `export.latex_to_mathml` exist and are imported exactly as
  the design's assembler/exporter reuse them — **confirmed** in `api/recognize.py`, `ensemble/latex.py`,
  `export/mathml.py`.
- M2 snip route patterns the design says it mirrors are real: `protected_router` /
  `require_token` bearer dependency (`api/routes.py`, `security.py`), single-worker
  `ThreadPoolExecutor(max_workers=1)` + `asyncio.wait_for` timeout, and 409 (`ModelNotReady`) /
  500 (`UnknownEngineError`,`FormulaStageNotConfigured`) / 422 (bad input) error mapping
  (`api/recognize.py`) — **confirmed**.
- `pipeline_config.py` has `Stages {ingest, layout, recognize{formula,text,table,handwriting},
  ensemble, export}` with ingest/layout/text currently `None` and `load_pipeline_config()` reading
  repo-root `pipeline.yaml` — **confirmed**; §9's "fill previously-reserved stage keys" is accurate.
  Current `pipeline.yaml` sets only `stages.recognize.formula: pix2tex` — **confirmed**.
- `tasks.md` 3.1–3.7 `done:` strings — **confirmed verbatim** against §14's mapping; task 3.3 does
  instruct "DocLayout-YOLO … verify license, mark opt-in if AGPL," which the design satisfies.
- License verdicts (PyPI, this run): `doclayout-yolo` 0.0.4 = AGPL-3.0; `ultralytics` 8.4.182 =
  AGPL-3.0; `pypdfium2` 5.14.0 = BSD-3-Clause/Apache-2.0; `onnxruntime` = MIT; `paddleocr` 3.7.0 =
  Apache-2.0; `pytesseract` 0.3.13 = Apache-2.0; `pillow-heif` = BSD-3-Clause; `rapid-layout` /
  `rapidocr-onnxruntime` = Apache-2.0 — **all confirmed**.
- `models/store.py` uses `db` DAOs (`get_model`, `upsert_model`, `set_status`) and never raw SQL —
  **confirmed**; the "SQLite only via db/" invariant holds for the model store M3 touches.

## Unverified / Wrong Assumptions

- **PP-DocLayout / PP-OCRv5 ONNX artifact URL + SHA (UNVERIFIED, honestly deferred).** I confirmed
  the *licenses* (Apache-2.0 for the paddleocr/paddlex code and for the `rapid-layout` /
  `rapidocr-onnxruntime` redistributors) but did not verify that a specific stable ONNX export of
  these exact model versions exists at a fixed URL, nor its byte hash. The design treats this as
  pin-on-first-fetch with a named contingency (the approved M2 pattern), so it is not a blocker;
  it must be pinned and license-re-confirmed at adoption (NIT 6).
- **PP-OCRv5 Latin recognizer covers Indonesian well enough for the EN+ID sanity test (§7.2) —
  NOT independently verified.** The design asserts the PP Latin model handles ID; this is a
  recognition-quality claim validated only by the planned `text_id.png` fixture at implementation
  time, not provable from source now. Acceptable: the fixture test is the verification gate, and a
  low score simply routes to the Tesseract fallback or `needs_review` (no fabrication).
- **DocLayout-YOLO *weights* license (as opposed to code) — NOT separately re-pulled.** The code +
  runtime are AGPL (confirmed). The opt-in adapter is unregistered and never shipped regardless, so
  the exact weights-license nuance does not affect the default-path gate; §16 already requires
  re-confirmation at adoption.
