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
