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
