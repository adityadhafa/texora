# M3 — Verification Log

Real command output captured while implementing M3 (PDF streaming + layout + text/formula
pipeline + MD/LaTeX export). Each section is appended as its feature completes; earlier
sections are not overwritten. Host: Windows + bash. Engine venv: Python **3.11.9** at
`.worktrees/m3-pdf-pipeline/engine/.venv` (created fresh for M3; gitignored). Interactive /
host-only items are recorded as PENDING MANUAL and are never claimed as passed.

---

## FEAT-001 — foundation: M3 deps + pipeline.yaml stages + typed IngestConfig + settings

### Dependency pins (verified against official PyPI metadata before pinning)

New M3 runtime deps added to `engine/requirements.txt` with the matching `docs/LICENSES.md`
rows added in the same change:

| Dependency  | Pinned   | License                   | PyPI verification |
|-------------|----------|---------------------------|-------------------|
| pypdfium2   | 5.14.0   | BSD-3-Clause / Apache-2.0 | Present on PyPI (sdist + cp311 wheels; uploaded 2026-10-04). |
| pillow-heif | 0.18.0   | BSD-3-Clause (libheif LGPL-3.0, dynamically linked) | `pillow_heif-0.18.0-cp311-cp311-win_amd64.whl` present. |
| onnxruntime | 1.19.2   | MIT                       | Latest 1.19 patch on PyPI (1.19.0 / 1.19.2); cp311 win_amd64 wheel present. Design said 1.19.* → pinned exact 1.19.2. |
| pytesseract | 0.3.13   | Apache-2.0                | Present on PyPI (uploaded 2024-08-16). Drives system/bundled Tesseract 5.x (Apache-2.0). |

**shapely / pyclipper NOT pinned in FEAT-001.** FEAT-001 adds no ONNX text-decode code, so
the PP-OCR postprocess transitives are deferred to the text-adapter feature that imports
them (per FEAT-001 step 2: "add ONLY if the chosen ONNX text decode path needs them,
otherwise omit and note it"). `opencv-python-headless==4.10.0.84` and `numpy==1.26.4` are the
existing M2 pins and were reused, not re-added.

**Deferred / opt-in:** the AGPL **DocLayout-YOLO** (`doclayout-yolo` 0.0.4 / `ultralytics`
lineage) row was added to the `docs/LICENSES.md` "Deferred / opt-in only" section — opt-in
only, never default, not bundled. The existing PyMuPDF (AGPL) deferred row is retained; M3
adds no PyMuPDF dependency.

### Install + integrity

```
$ .venv/Scripts/python.exe -m pip install -r requirements-dev.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
Successfully installed ... onnxruntime-1.19.2 ... pillow-heif-0.18.0 ... pypdfium2-5.14.0 ...
  pytesseract-0.3.13 ... torch-2.3.1+cpu torchvision-0.18.1+cpu ...

$ .venv/Scripts/python.exe -m pip check
No broken requirements found.

$ .venv/Scripts/python.exe -c "import pypdfium2, PIL, pillow_heif, onnxruntime, pytesseract, cv2, numpy; print('ok')"
ok
```

### Config / settings tests

```
$ .venv/Scripts/python.exe -m pytest tests/test_pipeline_config.py tests/test_settings.py -q
...........                                                              [100%]
11 passed
```

### Full engine gate

```
$ .venv/Scripts/python.exe -m ruff check .
All checks passed!

$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
50 files would be left unchanged.

$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 32 source files

$ .venv/Scripts/python.exe -m pytest -q
..........s...s.........................................s..........      [100%]
(3 skips = M2 model-gated tests, unchanged by FEAT-001)
```

PENDING / host-limited (unchanged for FEAT-001; no model, LaTeX, or CUDA paths touched here):
the `@pytest.mark.latex` TeX-compile and `@pytest.mark.model` weight-backed tests arrive with
later M3 features; CUDA EP remains code-review-only on this CPU host.

---

## FEAT-002 — ingest/ package: pypdfium2 render + image loaders + detection + preprocess (3.1/3.2)

No new third-party dependency was added (pypdfium2 / pillow-heif / opencv-python-headless /
numpy were all pinned + licensed in FEAT-001), so `docs/LICENSES.md` needed no new row. mypy
`[[tool.mypy.overrides]]` was extended to cover the first imports of the stub-less libs
`pypdfium2.*`, `pillow_heif.*`, and `cv2.*`.

### New modules

`engine/texora_engine/ingest/`: `base.py` (SourceKind, PdfTextSpan, RenderedPage,
IngestError), `pdf.py` (lazy per-page pypdfium2 render, adaptive DPI + one-shot small-font
raise, the SINGLE point->pixel conversion `_pt_to_px_bbox`), `images.py` (Pillow + pillow-heif
loaders, multi-page TIFF, M2 decompression-bomb guards -> typed IngestError), `detect.py`
(pure born-digital/scanned classifier over the pdfium text page), `preprocess.py` (one pure
fn per step; fixed order deskew->perspective->denoise->binarize->auto_crop; disabled step is a
byte-identical no-op), `__init__.py` (re-exports).

### Fixtures (reproducibly generated, license-clean)

Generators added under `scripts/`: `gen_born_digital_pdf.py` (writes `born_digital_math.pdf`
by hand, standard Type1 fonts only, plus an image-only `scanned.pdf` detector-negative) and
`gen_ingest_image_fixtures.py` (writes `scanned_page.png`, `text_en.png`, `text_id.png`,
`skewed_scan.png` + `skewed_scan.json` skew metadata, and per-format `sample.jpg/.webp/.bmp/
.heic` + two-frame `multipage.tiff`). Both are deterministic (fixed seed/layout, no
timestamps).

### Coordinate-conversion check (the one fiddly invariant)

The fixture title char `E` sits at pdfium point box ~`(170.36, 740.0, 181.20, 751.92)` on a
612x792 pt page; at base DPI 260 (`scale = 260/72`) that maps to pixel bbox
~`(615.2, 144.7, 654.3, 187.8)` top-left origin, which the renderer-produced span matches
within < 0.5 px. Asserted in `test_ingest_pdf.py::test_point_to_pixel_conversion_matches_known_span`.

### Feature + full gate

```
$ .venv/Scripts/python.exe -m pytest tests/test_ingest_pdf.py tests/test_ingest_images.py \
    tests/test_ingest_detect.py tests/test_preprocess.py -q
........................                                                 [100%]
24 passed

$ .venv/Scripts/python.exe -m ruff check .
All checks passed!

$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
60 files would be left unchanged.

$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 38 source files

$ .venv/Scripts/python.exe -m pytest -q
88 passed, 3 skipped, 4 warnings in 9.76s
```

PENDING / host-limited (unchanged by FEAT-002): the `@pytest.mark.latex` TeX-compile and
`@pytest.mark.model` weight-backed tests arrive with later M3 features; CUDA EP remains
code-review-only on this CPU host. FEAT-002 touches no model, LaTeX, or CUDA path.

---

## FEAT-003 — layout/ package: Protocol + factory + detectors + reading order (3.3/3.4)

The `layout/` package was implemented FRESH as ONE coherent public API after a prior concurrent
run left two incompatible half-implementations (both already wiped). New modules under
`engine/texora_engine/layout/`:

- `base.py` — `RegionType` StrEnum (full 15-value taxonomy), `BBox`, `Region` (confidence 0..1 +
  `reading_order=-1` + `source`), `LayoutResult`, and the `@runtime_checkable LayoutDetector`
  Protocol (`detect` MUST catch its own errors and return `regions=[]` with `engine_id` set, never
  raise, never fabricate).
- `factory.py` — mirror of `recognizers/factory.py`: a PERMISSIVE-ONLY `_REGISTRY` containing ONLY
  `pp_doclayout_onnx` (AGPL `doclayout_yolo` is intentionally ABSENT); `build_layout_detector`
  resolves EVERY id in `entry.model_ids` via a dict-comprehension over `model_store.require_ready`
  (multi-model resolution per design §2.1), typed `LayoutStageNotConfigured` /
  `UnknownLayoutEngineError` (never a silent default); `known_layout_engine_ids()`.
- `born_digital.py` — NO model, NOT a registry id (assembler-owned structural fast-path). Clusters
  text-layer spans into lines→regions; classifies TITLE / PARAGRAPH / INLINE_MATH / DISPLAY_MATH /
  EQUATION_NUMBER / LIST with the minimal `is_mathish` signal set (math Unicode-block ratio, the
  per-span italic/math-font flag from ingest, line isolation, right-margin `(n)`). Confidence is a
  documented structural heuristic (not a model probability).
- `pp_doclayout_onnx.py` — `id='pp_doclayout_onnx'`, `model_ids=('pp_doclayout',)`; onnxruntime
  `CPUExecutionProvider` default (`CUDAExecutionProvider` only when `device=='cuda'` — CUDA path is
  CODE-REVIEW-ONLY on this CPU host, flagged PENDING). On ANY inference exception returns
  `LayoutResult(regions=[], engine_id=self.id)`, never raises.
- `doclayout_yolo.py` — AGPL opt-in adapter with an AGPL-opt-in-only module docstring; NOT imported
  into / registered in `factory._REGISTRY`, never written as a `pipeline.yaml` default.
- `reading_order.py` — pure `order(regions, width, height) -> list[Region]`: column detection
  (x-center projection + vertical gutters) + recursive XY-cut; a right-margin `EQUATION_NUMBER`
  binds to the nearest `DISPLAY_MATH` on the same band and orders immediately after it;
  headers/footers ordered out-of-band; deterministic.
- `__init__.py` — re-exports the Protocol + types + factory + `order`.

### Model catalog + licenses (same change)

`models/catalog.py` gained three ONNX `ModelSpec` rows with the EXACT `ModelFile.name`s from design
§2.1 — `pp_doclayout` (`doclayout.onnx` + `label_map.txt`), `pp_ocrv5_det` (`det.onnx`),
`pp_ocrv5_rec` (`rec.onnx` + `rec_keys.txt` char dictionary), all Apache-2.0. **File names are the
hard contract now; URL + SHA-256 are pin-on-first-fetch at adoption** (same honesty note as
pix2tex — the placeholder `PIN_ON_FIRST_FETCH` URL + zeroed SHA fail loudly rather than fetch
unverified bytes). If a stable official ONNX export URL is unavailable at adoption, the Apache-2.0
`rapid-layout` / `rapidocr-onnxruntime` redistribution is pinned instead (same license + file-name
contract) — a documented contingency, recorded in `docs/LICENSES.md`. The matching Apache-2.0
rows were added to `docs/LICENSES.md` in this same change.

### Fixtures

Synthetic region-list fixtures (pure, no image): `engine/tests/fixtures/two_column.json`
(interleaved two-column order + a right-margin equation number bound to its display equation) and
`inline_math_para.json` (a one-line paragraph with text→math→text runs). The born-digital detector
test builds typed `PdfTextSpan` inputs directly (the real ingest contract), NOT mocked OCR.

### Feature tests

```
$ .venv/Scripts/python.exe -m pytest tests/test_layout_base.py tests/test_layout_factory.py \
    tests/test_layout_born_digital.py tests/test_reading_order.py
23 passed, 1 skipped, 1 warning in 0.60s
    # the 1 skip = the factory build-with-weights test (pp_doclayout ONNX weights absent)

$ .venv/Scripts/python.exe -m pytest tests/test_layout_ppdoclayout.py -rs
SKIPPED [1] tests/test_layout_ppdoclayout.py:36: pp_doclayout ONNX weights absent; run model prefetch
1 passed, 1 skipped, 1 warning in 0.38s
    # the 1 pass = failure-injection (corrupt session -> empty LayoutResult, never raises);
    # the 1 skip = the @pytest.mark.model real-weights test (skip-with-reason, never mocked)
```

### Full engine gate

```
$ .venv/Scripts/python.exe -m ruff check .
All checks passed!

$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
72 files would be left unchanged.

$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 45 source files

$ .venv/Scripts/python.exe -m pytest -q
114 passed, 5 skipped, 4 warnings in 10.59s
```

The 5 skips = 3 M2 pix2tex model-gated tests (unchanged) + the 2 FEAT-003 model-gated layout tests
(the factory build-with-weights test and the `@pytest.mark.model` PP-DocLayout real-weights test),
all skip-with-reason when ONNX weights are absent — never mocked.

PENDING / host-limited for FEAT-003:
- **PP-DocLayout ONNX weights** — URL + SHA-256 are pin-on-first-fetch at adoption; the
  `@pytest.mark.model` weight-backed test skips-with-reason until the weights are prefetched (same
  gate as the M2 pix2tex real-model test). The failure-injection test runs WITHOUT weights and
  proves the honesty invariant (corrupt session → empty `LayoutResult`, never raises).
- **CUDA execution provider** — code-review-only on this CPU host; `CPUExecutionProvider` is the
  tested path, CUDA EP wiring is reviewed and flagged PENDING.
- **DocLayout-YOLO (AGPL)** — adapter present for local opt-in use but not installed, not
  registered, and not exercised in the default path; `mypy` ignores the missing `doclayout_yolo`
  import via the stub-less override list.

---

## FEAT-004 — tasks 3.5 (text OCR adapter) + 3.6 (page assembly)

New engine modules: `recognizers/base.py` (+`TextLine`/`TextResult`/`TextRecognizer` Protocol,
reusing the single `layout.base.BBox`), `recognizers/text_factory.py` (the single-owning
PP-OCRv5→Tesseract fallback decision), `recognizers/text_ppocr_onnx.py` (id `pp_ocrv5_onnx`,
PP-OCRv5 det+rec via ONNX Runtime, DB post-process via shapely+pyclipper, CTC rec decode via
`rec_keys.txt`), `recognizers/text_tesseract.py` (id `tesseract`, `eng+ind`),
`pipeline/page_result.py` (`PageResult`/`DocumentResult`/`RegionContent`/`InlineRun`),
`pipeline/assembler.py` (ingest→layout→reading-order→recognition, reusing the M2 pix2tex
`build_formula_recognizer` UNCHANGED for all math), and `api/pages.py`
(`POST /pages/recognize`, bearer-protected, 409/422/500 mapping).

### New dependency pins (verified against official sources before pinning)

Added to `engine/requirements.txt` with matching `docs/LICENSES.md` rows in this same change
(FEAT-001 intentionally deferred them until the ONNX text adapter that needs them):

- `shapely==2.0.6` — BSD-3-Clause (PyPI/GitHub). PP-OCR DB post-process polygon geometry.
- `pyclipper==1.3.0.post6` — MIT (PyPI). PP-OCR DB post-process Vatti unclip. Latest cp311 wheel.

```
$ .venv/Scripts/python.exe -m pip install "shapely==2.0.6" "pyclipper==1.3.0.post6"
Successfully installed pyclipper-1.3.0.post6 shapely-2.0.6
$ .venv/Scripts/python.exe -m pip check
No broken requirements found.
```

PaddleOCR / PP-OCRv5 license re-confirmed **Apache-2.0** (official `PaddlePaddle/PaddleOCR`), so
the shipped default text path is fully permissive; its `docs/LICENSES.md` ML-models rows (det/rec
+ `rec_keys.txt` dictionary) were already present from FEAT-003 and are unchanged.

### Task 3.5 — text factory decision table + adapters

```
$ .venv/Scripts/python.exe -m pytest tests/test_text_factory.py -q
9 passed
    # full design §7.2.1 decision table: PP present -> PP (every model_id resolved + named
    # paths passed); PP absent + fallback + tesseract usable -> tesseract (INFO degrade);
    # PP absent + fallback + tesseract NOT usable -> re-raise ModelNotReady (API 409);
    # PP absent + no fallback -> 409; explicit tesseract + missing binary -> TesseractUnavailable;
    # built.id == configured id; unknown id / absent key -> typed errors.
$ .venv/Scripts/python.exe -m pytest tests/test_text_ppocr.py tests/test_text_tesseract.py -rs
SKIPPED tests/test_text_tesseract.py: tesseract binary not installed on this host; fallback test is host-limited
SKIPPED tests/test_text_ppocr.py: PP-OCRv5 ONNX weights absent; run model prefetch
    # contract + missing-weights(ModelNotReady) + failure-injection(->FAILED, never raises) pass;
    # the real EN/ID accuracy tests are model-/binary-gated and skip-with-reason (never mocked).
```

### Task 3.6 — page assembler + PageResult + POST /pages/recognize

```
$ .venv/Scripts/python.exe -m pytest tests/test_assembler.py tests/test_pages_api.py -rs
SKIPPED tests/test_assembler.py: pix2tex weights absent; run model prefetch
SKIPPED tests/test_pages_api.py: pix2tex/PP-OCRv5 weights absent; the 200 path is model-gated
    # structure tests on the REAL born_digital_math.pdf fixture pass WITHOUT weights (text comes
    # from the pdfium text layer; a tiny formula double exercises the math path): region types +
    # non-decreasing reading order + display-math latex/mathml + inline math recognized;
    # TABLE/HANDWRITING -> needs_review (detail 'M6'), worst-of page roll-up = needs_review.
    # API: 401 w/o token, 422 bad path/traversal/extension/range, 409 when a model is absent.
    # the @pytest.mark.model real pix2tex+PP-OCRv5 integration + the 200 path skip-with-reason.
```

### Full engine gate (FEAT-004)

```
$ .venv/Scripts/python.exe -m ruff check .
All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
84 files would be left unchanged.
$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 52 source files
$ .venv/Scripts/python.exe -m pytest -q
135 passed, 12 skipped in 28.71s
```

The 12 skips = 3 M2 pix2tex model-gated tests + 2 FEAT-003 layout model-gated tests + 7 FEAT-004
model-/binary-gated tests (PP-OCRv5 ONNX real recognition, pix2tex-backed assembler + API 200,
Tesseract real EN/ID). All skip-with-reason when weights/binary are absent — never mocked.

PENDING / host-limited for FEAT-004:
- **Tesseract binary ABSENT on this host** — `pytesseract.get_tesseract_version()` fails, so the
  Tesseract real EN/ID accuracy test and the live fallback-degrade path are documented PENDING
  (host-limited). The factory decision table that *selects* Tesseract is fully covered by
  monkeypatching `_tesseract_available` (no binary needed). Install Tesseract 5.x or set
  `TEXORA_ENGINE_TESSERACT_CMD` to exercise the real fallback.
- **PP-OCRv5 ONNX weights** — URL + SHA-256 are pin-on-first-fetch at adoption; the real EN/ID
  recognition test and the assembler/API 200 path skip-with-reason until weights are prefetched
  (same gate as the M2 pix2tex and FEAT-003 PP-DocLayout real-model tests). Never mocked.
- **CUDA execution provider** — code-review-only on this CPU host; `CPUExecutionProvider` is the
  tested path, CUDA EP wiring is reviewed and flagged PENDING.

---

## FEAT-005 — task 3.7: Markdown + LaTeX exporters (THE HEADLINE OUTPUT)

Scope: the Markdown + LaTeX document emitters (`export/markdown.py`, `export/latex.py`,
`export/templates.py`), byte-stable golden-file tests (incl. a paragraph-with-inline-math golden
proving `$...$` lands mid-paragraph), the gated `latexmk` compile, and the M3 docs. No new runtime
dependency was added — the emitters use only the stdlib + the existing Pydantic models — so there is
no new `docs/LICENSES.md` row for FEAT-005.

### Dependency note (prefetched for the real demo, not a new pin)
To run the REAL end-to-end PDF→Markdown demo below, the already-pinned M2 pix2tex weights were
fetched through the catalog pin and byte-verified against the pinned SHA-256:
```
weights.pth        sha256 a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa  match=True  (102113875 bytes)
image_resizer.pth  sha256 1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458  match=True  ( 19441973 bytes)
```
These are the existing `catalog.pix2tex_spec` bytes (MIT), not a new dependency.

### Golden-file export tests
```
$ .venv/Scripts/python.exe -m pytest tests/test_export_markdown.py tests/test_export_latex.py -p no:warnings
11 passed, 1 xfailed in 0.79s
```
- `document_to_markdown` byte-matches `tests/golden/doc_sample.md`; `document_to_latex` byte-matches
  `tests/golden/doc_sample.tex`. Both are rendered from a FIXED, hand-constructed `DocumentResult`
  (`tests/_doc_sample.py`) — deterministic TEST DATA, not a mocked production OCR result.
- The inline-math paragraph asserts `$...$` lands mid-sentence (design F5): the rendered line is
  `In special relativity the energy is $E = mc^2$ which binds mass and energy.` with non-empty text
  on both sides of the `$...$` span.
- TABLE → honest `<!-- table: needs_review (M6) -->` (MD) / `% table: needs_review (M6)` (TeX),
  never a fabricated tabular. A `status!=ok` run emits an honest `needs_review` marker and NO empty
  `$$` delimiter.

### LaTeX `latexmk` compile — PENDING (host-limited), honestly xfail-skipped
`test_golden_tex_compiles_with_latexmk` is marked `@pytest.mark.latex`. There is **no TeX toolchain
on this host** (`which latexmk` / `which pdflatex` both fail), so the test **xfail-skips** with the
recorded reason `no TeX toolchain (latexmk) on this host; asserted in the CI m3-latex-compile job`.
The test is NOT deleted and NOT silently passed — it is written to run `latexmk -pdf
-interaction=nonstopmode -halt-on-error` on the golden `.tex` and assert exit 0 + a produced PDF
where a toolchain exists. The CI `m3-latex-compile` job provisions TinyTeX/texlive and runs it
no-skip. **No compile has run on this host; this is recorded as PENDING, never claimed as passed.**

### Assembler ordering bug found by the real demo + its fix
Running the real demo (below) first surfaced a genuine bug in the committed FEAT-004 assembler
(`pipeline/assembler.py`): born-digital text-layer spans are PER-CHARACTER, and glyph bbox heights
vary (ascenders/descenders), so their y-centers differ on the SAME line. The old ordering
(`sort by round((y0+y1)/2, 1) then x0`) therefore **scrambled each line**. Proof on the title band:
```
ASSEMBLER (old) -> "iEMEldnrnnaaaesseceuvqgy"
x-ordered       -> "EnergyandMassEquivalence"   (correct)
```
Fix (design §6.5: runs ordered left-to-right within a line band), tightly scoped to span ordering
in `_text_from_layer` + `_born_digital_inlines` via a new `_order_spans` helper: cluster spans into
line bands by ≥50% vertical overlap, order bands top-to-bottom, order spans left-to-right by `x0`
within each band. No layout/region API or `PageResult`/`DocumentResult` type changed. A regression
test (`test_born_digital_span_order_is_not_scrambled`) asserts the title band now reads
`EnergyandMassEquivalence`.

### REAL end-to-end demo — born_digital_math.pdf → Markdown via the real pix2tex engine
No mocks, no fabricated OCR. Prose comes from the pdfium born-digital text layer (now correctly
ordered); the display + inline equations were recognized by the **real** pix2tex model on CPU. This
is the headline PDF→Markdown feature, run end-to-end (`iter_pdf_pages` → `assemble_page` →
`document_to_markdown`):
```markdown
# EnergyandMassEquivalence

InspecialrelativitytheenergyofaTheconstantcisthespeedof
bodyatrestisgivenbythefamouslightinvacuum.Becausecis

$$
\mathrm{\Gammaelatior}\ \ E=m c2\ \mathrm{Wilicl\binds\mass}
$$
<!-- needs_review: pix2tex 0.1.4 exposes no usable per-token scores; confidence reported as unavailable -->

,

andenergyintoasinglequantity.verylargerestenergy.

$E=m\;c^{\times}2\ \qquad\qquad ... \qquad(1)
```
Honest notes on this real output (characteristics of the committed born-digital path + the
hand-built fixture, NOT exporter defects and OUT of FEAT-005's span-ordering scope):
- **No inter-word spaces** — the fixture PDF draws each word as a separate show-text op with no
  space glyph, so the born-digital path (which joins span glyphs verbatim) yields no spaces. This is
  faithful to the input, not fabricated.
- **Columns merged on a line** — the committed born-digital layout detector emits paragraph regions
  spanning the full page width (it does not yet split the two columns into separate regions), so
  left+right column text on the same y-band is joined. This is a FEAT-003 born-digital layout
  limitation, tracked separately; the exporter faithfully renders the regions it is given.
- The `needs_review` marker on the display equation is the honest pix2tex confidence-unavailable
  note (the pinned pix2tex exposes no per-token score), carried through verbatim — never a
  fabricated confidence.

The exporters themselves are correct: they reproduce reading order, place inline `$...$` math in
its true position, emit numbered display math, and surface honest review markers — exactly as the
byte-stable goldens assert.

### Full engine gate (FEAT-005) — ALL GREEN
```
$ .venv/Scripts/python.exe -m ruff check .
All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
90 files would be left unchanged.
$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 55 source files
$ .venv/Scripts/python.exe -m pytest -q
150 passed, 9 skipped, 1 xfailed in 35.44s
```
The 9 skips = model-gated tests (PP-DocLayout ONNX + PP-OCRv5 text ONNX weights pin-on-first-fetch,
+ Tesseract binary absent), all skip-with-reason, never mocked. The 1 xfail = the `latexmk` compile
(no TeX toolchain on this host, recorded PENDING above). The real pix2tex model-gated tests PASS
(weights prefetched + SHA-256 verified).

---

## Convergence — born-digital prose quality: word spacing + column reading order

The two "honest notes" recorded against the FEAT-005 demo above (no inter-word spaces; columns
merged on a line) were real defects in the born-digital path, not acceptable output. They are now
**fixed** (M3 modules are under active development, so this is in-scope, not a redesign). The third
note (garbled display/inline LaTeX) is **not** an assembler bug — it is the accuracy of the
provisional pix2tex default on a small synthetic crop, handled honestly below (R-QA-2), never
hand-corrected.

### 1. Gap-based word spacing (real extraction fix)
pdfium's text layer is per-character and drops space glyphs (spaces are positioning, not
characters), so a verbatim `"".join` jammed words ("Inspecialrelativitytheenergyofa"). A shared
`join_spans_with_spaces` helper (`layout/born_digital.py`) now inserts a single space between two
consecutive glyphs on a line when the horizontal gap exceeds `_WORD_GAP_FRAC` (0.38) of the local
glyph height — calibrated between the within-word gaps (≤~0.3×) and inter-word gaps (≥~0.45×) of
the standard Type1 metrics the fixture uses. The assembler's `_text_from_layer` and
`_born_digital_inlines` join per line band with the same helper and join bands with a space, so a
wrapped run reads as continuous prose. Regression: `test_born_digital_prose_is_word_spaced`.

### 2. Column reading order (real layout/reading-order fix)
The born-digital detector clustered each y-band across the full page width, so a left-column and a
right-column line on the same band merged into one region straddling the gutter; reading order then
interleaved the columns ("...the energy of a The constant c is the speed of"). Fix, in three tight
pieces:
- `layout/born_digital._cluster_lines` now clusters by ≥50% vertical OVERLAP (robust to the
  mixed glyph heights of a display line), replacing the fragile y-center epsilon.
- `_detect_column_gutters` finds the page's persistent vertical gutter from the per-line GLYPH
  coverage (a band's union bbox always straddles the gutter, so the span boxes are tested), keeping
  a gutter only where body text straddles it on both sides — a margin or a one-off gap is dropped.
- `_split_line_at_gutters` splits a clustered line at a gutter only when the straddling gap is
  itself ≥ the gutter width, so a full-width title / centred display line stays whole.
- `layout/reading_order._xy_cut` was rewritten to cut on the axis with the WIDEST whitespace gap
  at each step (not a forced horizontal/vertical alternation), so a title or display-equation band
  that crosses the gutter is separated by its large horizontal gap BEFORE the body is cut into
  columns; `_detect_columns` computes the gutter from non-spanning regions only.
Regression: `test_born_digital_columns_read_left_then_right` (assembler) +
`test_two_column_body_splits_into_separate_regions` / `test_per_character_equation_number_is_peeled`
(detector), and the existing synthetic `two_column.json` reading-order tests still pass.

A born-digital `INLINE_MATH` region (a prose line carrying one inline formula, design §6.5) is now
routed through the text/inline-run path, so only the formula sub-crop goes to pix2tex and the
surrounding words stay as text runs — recognizing the whole line as one formula crop was what
garbled the prose on that line.

### 3. Fixture realism + honest formula-accuracy bound (R-QA-2)
The display equation in `scripts/gen_born_digital_pdf.py` is now drawn at a large (24 pt) uniform
font on a single baseline, so the rasterised crop fed to the formula recognizer has clear,
well-separated glyphs (a tiny glyph image is a poor formula input). The fixture is still a
hand-built, license-clean born-digital PDF (standard Type1 fonts, deterministic bytes). It renders
the equation as plain text `E = mc2` (no real superscript glyph), which is a faithful but modest
formula image.

**Formula-recognition QUALITY is bounded by the provisional pix2tex default**, not by the
assembler. On this fixture's small synthetic crops the real pix2tex 0.1.4 model still produces
imperfect LaTeX (e.g. it reads the inline `E = mc2` fragment as `\overline{{\neg}}` and the display
line as `E=m c2`, not `E = mc^2`). This is reported honestly and **never hand-corrected**: the
LaTeX shown below is the model's real output. Choosing a benchmark-selected, higher-accuracy
permissive formula model is the **M7 decision (R-QA-2)**; pix2tex is the provisional default only.

### REAL end-to-end demo (improved) — born_digital_math.pdf → Markdown via the real pix2tex engine
No mocks, no fabricated OCR. Prose comes from the pdfium born-digital text layer (now correctly
spaced AND column-ordered); the inline + display equations are the **real** pix2tex model output on
CPU. Run end-to-end (`iter_pdf_pages` → `assemble_page` → `document_to_markdown`) with the pix2tex
weights prefetched + SHA-256 verified:
```markdown
# Energy and Mass Equivalence
In special relativity the energy of a
body at rest is given by the famous
relation E$\overline{{\neg}}$mc2 which binds mass
and energy into a single quantity.
The constant c is the speed of
light in vacuum. Because c is
large, a small mass maps to a
very large rest energy.
$$
E=m c2 \tag{1}
$$
```
Prose now reads with correct word spacing; the left column is read fully (title → "In special
relativity…" → "…which binds mass" → "…single quantity.") before the right column ("The constant
c…" → "…very large rest energy."); the numbered display equation renders as a block with its
`\tag{1}`. The ONLY remaining imperfection is the LaTeX inside the `$...$`/`$$...$$` — real pix2tex
output on these small synthetic crops, documented above as the M7 formula-model decision, not a
pipeline defect and not hand-edited.

### Full engine gate (convergence) — ALL GREEN
```
$ .venv/Scripts/python.exe -m ruff check .
All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100
All done! ✨ 🍰 ✨
90 files would be left unchanged.
$ .venv/Scripts/python.exe -m mypy texora_engine
Success: no issues found in 55 source files
$ .venv/Scripts/python.exe -m pytest -q
154 passed, 9 skipped, 1 xfailed in 37.69s
```
+4 tests vs FEAT-005 (two assembler prose/column regressions + two born-digital detector
column/eqnum regressions). The 9 skips / 1 xfail are unchanged in nature from FEAT-005 (ONNX text +
layout weights pin-on-first-fetch, Tesseract binary absent, latexmk no toolchain) — the real
pix2tex model-gated tests PASS.
