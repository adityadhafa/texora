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
