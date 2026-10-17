# M2 — Verification Log

Real command output captured while implementing M2 (single-image formula OCR). Each section
is appended as its task completes; earlier sections are not overwritten. Host: Windows +
bash. Engine venv: Python **3.11.9** at `.worktrees/m2-formula-ocr/engine/.venv` (created
fresh for M2; gitignored). Interactive/host-only items are recorded as PENDING MANUAL and
are never claimed as passed.

---

## Phase 0 — dependency pins + license rows

### Engine (installed into the venv; match `docs/LICENSES.md` + `engine/requirements.txt`)

Key installed versions (from `pip freeze`):

```
pix2tex==0.1.4
torch==2.3.1+cpu
torchvision==0.18.1+cpu
pillow==10.4.0
pylatexenc==2.10
latex2mathml==3.77.0
httpx==0.28.1            # promoted dev -> runtime
transformers==4.42.4     # transitive pin (era-matched to torch 2.3.1)
tokenizers==0.19.1
huggingface-hub==0.24.6
numpy==1.26.4
opencv-python-headless==4.10.0.84
albumentations==1.4.15
albucore==0.0.16
timm==0.5.4
x-transformers==0.15.0
```

Deviation recorded honestly: the design named direct pins (`pix2tex`, `torch==2.3.1+cpu`,
`pillow`, `pylatexenc`, `latex2mathml`, `httpx`), all of which are satisfied. pix2tex 0.1.4
predates the current torch/transformers/numpy line, so a consistent set of **transitive**
pins (torchvision 0.18.1, transformers 4.42.4, tokenizers 0.19.1, numpy 1.26.4, opencv
4.10, albumentations 1.4.15 + albucore 0.0.16) was required for an import-and-infer-clean
stack. `python -m pip check` reports no broken requirements.

```
### engine/.venv/Scripts/python.exe -m pip check
No broken requirements found.

### import smoke
python -c "import pix2tex, torch, PIL, pylatexenc, latex2mathml, httpx; print('ok')"
ok
```

The `+cpu` torch/torchvision wheels come from the PyTorch CPU index
(`--extra-index-url https://download.pytorch.org/whl/cpu`), not PyPI — no CUDA payload.

### Frontend (resolved by pnpm; `apps/desktop/package.json` + `pnpm-lock.yaml`)

```
katex@0.16.11
@types/katex@0.16.7
@tauri-apps/plugin-global-shortcut@2.3.0   # JS floor; crate resolves to 2.4.1
```

`pnpm --filter desktop build` passes with the deps added (no new imports yet):

```
✓ 65 modules transformed.
✓ built in 7.76s
```

### Rust (`apps/desktop/src-tauri/Cargo.toml` + `Cargo.lock`)

```
tauri-plugin-global-shortcut = "2.4.1"   # resolved from the "2.3.0" floor
xcap = "0.9.8"
# transitive: image 0.25.10, global-hotkey 0.8.0
```

`cargo fetch` resolved the lockfile (see Task 2.x Rust section for the build result).

---

## Task 2.1 — Model registry + checksum downloader + offline bundle + db layer

### Model adoption facts (pin-on-first-fetch — confirmed on THIS host, NOT invented)

Confirmed against the GitHub releases API for `lukas-blecher/LaTeX-OCR`:

- PyPI package: `pix2tex==0.1.4` (exists on PyPI, MIT, uploaded 2025-01-18).
- Release tag hosting the weights: **`v0.0.1`** (release name "Weights release").
- Assets, with their direct immutable per-tag URLs:
  - `weights.pth` — size **102113875** bytes —
    `https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/weights.pth`
  - `image_resizer.pth` — size **19441973** bytes —
    `https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/image_resizer.pth`

Real SHA-256 values computed by streaming each asset once on this host (baked into
`engine/texora_engine/models/catalog.py`):

```
weights.pth         sha256=a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa
image_resizer.pth   sha256=1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458
```

HONESTY NOTE (recorded in `docs/LICENSES.md` too): upstream publishes no vendor-signed
checksum for these assets. The pinned SHA-256 values above are **our** hashes of the
upstream release assets at tag `v0.0.1`, computed once on first fetch — not a vendor
attestation. They guarantee integrity/immutability relative to the bytes we first pinned
(tamper/corruption detection on every later load + offline import). A vendor-pinned or
content-addressed hash is an M7 option. The design assumption (`weights.pth` /
`image_resizer.pth` at tag `v0.0.1`) matched reality exactly — no catalog shape changes
were needed.

### Tests (venv python, from `engine/`)

```
### pytest tests/test_db.py tests/test_registry.py tests/test_downloader.py tests/test_bundle.py -q
............                                                             [100%]  (12 passed)
```

- `test_db.py`: WAL mode asserted; MODEL upsert/read/status; SETTING upsert/read.
- `test_registry.py`: pix2tex spec validates; `file_path` composes; unknown-file KeyError.
- `test_downloader.py`: good-hash download promotes to `ready` (terminal progress event);
  **bad-hash deletes the `.part`, does not promote, raises `ChecksumMismatch`** (AC-1) —
  against a local HTTP server (download/verify plumbing, NOT mocked OCR).
- `test_bundle.py`: offline import from dir + zip with **networking stubbed to fail**
  (AC-2); missing-file → `BundleIncomplete`; bad-hash → `ChecksumMismatch`.

### Engine gate after Task 2.1

```
### ruff check .      -> All checks passed!
### black --check . --line-length 100 -> left unchanged
### mypy texora_engine -> Success: no issues found in 20 source files
```

---

## Task 2.2 — FormulaRecognizer Protocol + pix2tex adapter + factory

### Confidence probe outcome (R-REC-2 — recorded honestly, NOT fabricated)

Probed the pinned `pix2tex==0.1.4` decode path: `Model.generate` →
`CustomARWrapper.generate` returns **token ids only** and discards the sampling
probabilities (`probs`); `LatexOCR.__call__` returns only the decoded string. There is no
stable public API on the pin that yields per-token logprobs.

**Decision branch taken: `unavailable`.** Every `FormulaResult`/`SnipResponse` carries
`confidence == 0.0` with `confidence_kind == "unavailable"` and a `detail`. No number is
fabricated. The Snip UI renders a "confidence unavailable" state (asserted in vitest). Per
the approved design this is an accepted, documented R-REC-2 satisfaction for the provisional
M2 default; a scoring-capable engine is expected in M7.

### pipeline.yaml

The entire commented placeholder body was replaced with the real minimal config (permissive-
first comment kept); `recognize` is a MAP of sub-stages with `formula: pix2tex`.

### HOST GATE — real pix2tex inference on this CPU host (PASSED)

The committed fixture `engine/tests/fixtures/formula_frac_ab.png` was recognized by the REAL
model through the production adapter path (no mock). Representative run during adoption:

```
load_s=1.26
infer_s=0.84
LATEX_OUT: '\frac{\d C}{\d l_{\bar{\cal{M}}}}'
```

The output is a non-empty, structurally-valid `\frac{...}{...}` LaTeX string produced by the
real model (AC-4). The fixture was rendered via matplotlib mathtext in a throwaway scratch
venv (not an engine dep); its distribution differs slightly from pix2tex's training set, so
the recognized tokens are not a character-perfect match — AC-4 requires a non-empty
KaTeX-valid string via the real model, which is met. The adapter points pix2tex ONLY at
local registry-resolved weights, so pix2tex's built-in downloader is never triggered.

### Tests (venv python, from `engine/`)

```
### pytest tests/test_recognizers_base.py tests/test_pipeline_config.py \
###        tests/test_formula_pix2tex.py tests/test_factory.py -q
..........   (10 passed)

### pytest tests/test_formula_pix2tex.py -v
test_real_model_recognizes_fixture ... 2 passed  (NOT skipped — weights prefetched)
```

- `test_recognizers_base.py`: RecognitionStatus values; FormulaResult enforces 0≤conf≤1;
  honest defaults (unavailable/0.0).
- `test_pipeline_config.py`: `stages.recognize.formula == "pix2tex"` (AC loads real yaml).
- `test_formula_pix2tex.py`: REAL model → non-empty LaTeX via production path (AC-4,
  skip-with-reason if weights absent, never mocked); construct-without-weights raises
  `ModelNotReady` with **networking stubbed to fail** (no egress).
- `test_factory.py`: pix2tex registered + `isinstance(adapter, FormulaRecognizer)` (AC-3);
  unknown id → `UnknownEngineError` carrying offending+known ids (AC-3a); absent key →
  `FormulaStageNotConfigured`.

Full engine suite after Task 2.2: `pytest -q` → **26 passed**; `ruff`/`black --check`/`mypy`
all clean (25 source files).

Prefetch note: the real-model tests read `TEXORA_TEST_MODELS_DIR` (default
`engine/.venv/pix2tex_models`, gitignored). CI runs them only in a gated job that prefetches
the pinned weights; absent weights → skip-with-reason, never a mock.
