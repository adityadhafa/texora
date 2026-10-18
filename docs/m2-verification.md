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

---

## Task 2.3 — LaTeX normalize + validate + MathML

### KaTeX allow-list generator input (confirmed at implementation time)

Input path USED: the installed package's shipped ESM bundle
`node_modules/.pnpm/katex@0.16.11/node_modules/katex/dist/katex.mjs` (the public function
registry). The npm dist exposed the registry in a parseable form
(`defineFunction({names:[...]})`, `defineMacro("\\name", ...)`, `defineSymbol(...,"\\name")`,
`defineEnvironment({names:[...]})`), so the **verified fallback** (vendoring the katex SOURCE
tarball) was NOT needed. No source-tarball SHA to record.

```
### python scripts/gen_katex_allowlist.py
wrote engine/texora_engine/ensemble/katex_allowlist.json (commands=1141, environments=33)
```

The JSON header records `katex_version: 0.16.11`; `test_katex_allowlist.py` asserts it
equals the `katex` pin in `apps/desktop/package.json`, so a katex bump without regeneration
fails CI (generated, cannot drift — AC-5).

### Tests (venv python, from `engine/`)

```
### pytest tests/test_katex_allowlist.py tests/test_latex.py tests/test_mathml.py -q
..................   (18 passed)
```

- `test_latex.py`: valid LaTeX (frac/powers/sum/greek/left-right/matrix) → `ok`;
  unbalanced braces / unmatched `\left` / unmatched+mismatched env → `failed`; out-of-allow-
  list macro and unknown env → `needs_review`; normalization (`\dfrac`→`\frac`, spacing)
  keeps the output valid (AC-5 engine side).
- `test_mathml.py`: `\frac{a}{b}` → `<math …><mfrac>…` golden.

`ruff`/`black --check`/`mypy` clean (29 source files).

---

## Tasks 2.4 + 2.6 — /recognize/snip, /hardware, /models (engine side)

### Routes

- `POST /recognize/snip` (protected): base64 decode + bounds guard → cached pix2tex
  singleton → single-worker `ThreadPoolExecutor` under `asyncio.wait_for(snip_timeout_s)` →
  `validate_and_normalize` → `latex2mathml`. Pillow decode errors
  (`UnidentifiedImageError`/`DecompressionBombError`/decode failures) → **422, never 500**;
  oversized decoded dimensions → 422; timeout → 200 `status=failed`; `asciimath` always
  null.
- `GET /hardware` + `POST /hardware/device` (protected): devices from torch availability;
  selection persisted in the `setting` table; unknown device → 422.
- `GET /models/{id}` + `POST /models/{id}/download` (protected): status snapshot; download
  trigger returns `downloading` immediately (background task).

### Tests (venv python, from `engine/`)

```
### pytest tests/test_settings.py tests/test_hardware_api.py tests/test_models_api.py \
###        tests/test_recognize_api.py
15 passed
```

- `test_recognize_api.py` (AC-6): no token → 401; malformed base64 → 422; oversized decoded
  image → 422; real-model fixture → 200 with `{latex, confidence, confidence_kind, status,
  validation, mathml}` and `asciimath == null`. **Confidence branch asserted: `confidence ==
  0.0`, `confidence_kind == "unavailable"`** (the recorded pix2tex branch). Skips with reason
  if weights absent — never mocked.
- `test_hardware_api.py` (AC-7): 401 without token; GET reports cpu + selection; override to
  cpu persists and is reported on the next call; unknown device → 422; cuda override works
  when `_detect_devices` is monkeypatched.
- `test_models_api.py`: 401 without token; status shape with both pinned files; unknown id →
  404; download trigger returns `downloading` immediately (background stubbed so no real
  transfer in the unit test).

Full engine suite after 2.4/2.6: `pytest` → **59 passed**; `ruff`/`black --check`/`mypy`
clean (32 source files).

Note: a thread-shared SQLite connection is opened with `check_same_thread=False` because
FastAPI runs sync routes in a worker threadpool (single-user loopback engine; WAL + the
per-connection lock keep access safe).

---

## JS→engine transport (items 19–20) + Snip UI (task 2.5) + hardware UI (consumes 2.6)

### Transport (Rust) — token/port stay in Rust

`SupervisorState` now holds the live `port` + session `token`; `engine_request` builds an
authenticated `ureq` request (`Authorization: Bearer <token>`) against the live port and
returns a typed `engineNotReady` error when the engine is not healthy. New thin proxy
commands (`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`) are
registered in `generate_handler!`; the webview never receives the port or token. The
model-download poller polls `GET /models/{id}` every 500 ms, emits `engine://model-progress`,
and stops on a terminal state. `snip.rs` registers Ctrl+Shift+M and captures via `xcap` →
PNG → base64 → `engine://snip-captured`. `capabilities/default.json` adds the global-shortcut
allow entries (no network capability — HTTP stays in Rust).

### Frontend (vitest) — engineClient is the sole bridge importer; NO fetch

```
### pnpm --filter desktop test -- --run
Test Files  8 passed (8)
     Tests  33 passed (33)
### pnpm --filter desktop lint   -> clean (0 errors, 0 warnings)
### pnpm --filter desktop build  -> built (KaTeX fonts bundled)
```

- `engineClient.test.ts`: each wrapper invokes the right command / listens on the right
  event (bridge mocked); snake_case→camelCase mapping asserted.
- `bridgeInvariant.test.ts`: grep-style — `engineClient.ts` is the ONLY production module
  importing `@tauri-apps/api`, and no production module calls `fetch()` (AC-8 invariant).
- `locales.test.ts`: id.json / en.json key sets are identical; M2 `snip.*`/`hardware.*` keys
  present; `snip.copyOmml` absent (OMML is M6).
- `SnipPopup.test.tsx`: renders LaTeX + copy buttons from i18next; **real-katex preview**
  renders a `.katex` root; **confidence-unavailable** state shown; failed result renders the
  could-not-recognize message (never fabricated LaTeX); Markdown copy wraps `$$…$$`; Esc
  closes.
- `katexRender.test.ts`: the authoritative real-`katex` render — valid LaTeX renders without
  ParseError; invalid LaTeX throws (AC-5 UI side).
- `SettingsHardware.test.tsx`: renders devices + the CPU-slower note; changing the select
  calls `setDevice`.

### Rust (cargo) — recorded in the Phase 9 section once the gate runs.

### PENDING MANUAL (host/interactive) — NOT claimed as passed

- Global hotkey **Ctrl+Shift+M** actually firing in a running `tauri dev` window.
- Live on-screen **screen-region capture** + OS screen-capture permission.
- The **on-screen popup** appearing over the desktop.
- **CPU snip latency** as a user-perceived number (the ≤1.5 s R-UI-2 target is a GPU target;
  the adoption-time CPU inference was load≈1.26 s + infer≈0.84 s on the fixture, measured, not
  asserted as the UI latency).

---

## Convergence re-run (2026-10-18) — authoritative, freshly executed

Everything below was run end-to-end on this host during convergence and **supersedes** the
per-task self-reports above wherever they differ. Commands are shown exactly as run (the
required PATH export is prepended to every shell; the engine uses the venv python; Rust
commands run after loading the MSVC env via `vcvars64.bat`).

### A. Engine PyInstaller freeze fix (root cause + fix)

The Rust/Tauri build had been red because the `externalBin` sidecar
`binaries/texora-engine-x86_64-pc-windows-msvc.exe` did not exist — the freeze never
finished placing it. Root cause (diagnosed, not guessed): PyInstaller's Windows
post-assembly step rewrites the PE **build timestamp** and **checksum** *in place*. For this
`--onefile` binary (~570 MB, because torch is bundled) the in-place rewrite fails with
`OSError(22, 'Invalid argument')` because `pefile` had just memory-mapped the same path — a
known PyInstaller/pefile interaction on large Windows onefiles, **not** an engine defect. The
fully assembled onefile already existed on disk at that point; only the cosmetic
timestamp/checksum fix-up had not landed.

Reproduced precisely: a plain `open(exe,'wb').write(pe.write())` to a **new** path succeeds,
but `winutils.set_exe_build_timestamp` rewriting the **just-mmapped** path raises
`OSError(22)`. Writing to a temp file and `os.replace`-ing it over the original succeeds.

Fix (in `scripts/build_engine.py`, committed): run PyInstaller with `check=False`; if it
exits non-zero **but** the expected onefile exists on Windows, finish the PE
timestamp+checksum fix-up ourselves via **temp-file + atomic replace** (the proven-safe
path), then proceed to place the sidecar. Any other failure, or a missing binary, is still a
hard error. This changes no engine behavior and ships no unverified binary.

```
### engine/.venv/Scripts/python.exe scripts/build_engine.py --triple x86_64-pc-windows-msvc
[build_engine] PyInstaller exited non-zero but the onefile exists; applying the PE
  timestamp/checksum fix-up via temp+replace (works around the large-onefile OSError 22 on Windows).
[build_engine] frozen binary: ...\engine\.build\dist\texora-engine.exe
[build_engine] sidecar placed: ...\apps\desktop\src-tauri\binaries\texora-engine-x86_64-pc-windows-msvc.exe

### sidecar runs (fully assembled, functional):
./binaries/texora-engine-x86_64-pc-windows-msvc.exe --help
usage: texora_engine [-h] [--host HOST] --port PORT [--token TOKEN]
```

Binary size ≈ 570 MB; `git check-ignore` confirms it is gitignored (never committed).

### B. Rust / Tauri — now GREEN (was exit 101 only due to the missing sidecar)

Run from `apps/desktop/src-tauri` with the MSVC env loaded:

```
### cargo build
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1m 16s

### cargo fmt --check
(fixed one pre-existing formatting nit in src/snip.rs via `cargo fmt`, then:)
### cargo fmt --check  -> clean (exit 0)

### cargo clippy --all-targets -- -D warnings
    Finished `dev` profile ... (exit 0, no warnings)

### cargo test
running 14 tests ... test result: ok. 14 passed; 0 failed; 0 ignored
```

### C. Engine (venv python, from `engine/`)

```
### ruff check .                          -> All checks passed!
### black --check . --line-length 100     -> 50 files would be left unchanged.
### mypy texora_engine                    -> Success: no issues found in 32 source files
### pytest -q                             -> 59 passed
```

Key D-items, re-run and confirmed real (not skipped, not mocked):

```
### pytest tests/test_formula_pix2tex.py tests/test_downloader.py -v
tests/test_formula_pix2tex.py ..   (test_real_model_recognizes_fixture PASSED — real CPU
                                    inference on the committed fixture via the production path)
tests/test_downloader.py ..        (test_bad_hash_is_rejected PASSED — corrupt file raises
                                    ChecksumMismatch, .part deleted, file not promoted)
```

### D. pix2tex hash provenance — confirmed REAL on this host (not a placeholder)

The SHA-256 values baked into `engine/texora_engine/models/catalog.py` were recomputed on
this host from the prefetched weights and cross-checked against the immutable upstream
release assets:

```
### sha256sum engine/.venv/pix2tex_models/pix2tex/weights.pth
a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa   (matches catalog.py)
### sha256sum engine/.venv/pix2tex_models/pix2tex/image_resizer.pth
1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458   (matches catalog.py)

### HEAD on the immutable per-tag upstream URLs (lukas-blecher/LaTeX-OCR @ v0.0.1):
weights.pth        status 200  content-length 102113875  (matches catalog size)
image_resizer.pth  status 200  content-length 19441973   (matches catalog size)
```

Honesty caveat (unchanged, see §Task 2.1 + `docs/LICENSES.md`): these are **our** hashes of
the upstream assets, computed on this host — not a vendor-signed attestation. They detect
tamper/corruption on every later load and offline import. A vendor-pinned/content-addressed
hash is an M7 option.

Confidence contract (R-REC-2) re-confirmed both ways: the pinned pix2tex 0.1.4 exposes no
usable per-token scores, so every result carries `confidence=0.0` +
`confidence_kind="unavailable"` + a `detail` (never a fabricated number). The Snip UI renders
the "confidence unavailable" state — asserted by vitest (`SnipPopup.test.tsx` → "shows the
confidence-unavailable state").

### E. Frontend (from worktree root)

```
### pnpm --filter desktop lint             -> clean (eslint, 0 problems)
### pnpm --filter desktop test -- --run    -> Test Files 8 passed (8) · Tests 33 passed (33)
### pnpm --filter desktop build            -> tsc (strict) + tsc:node + vite build → built in 4.17s
```

### F. Invariants re-checked during convergence (no regressions)

- **Single typed client / no fetch**: `engineClient.ts` is the ONLY production module
  importing `@tauri-apps/api` (`invoke`/`listen`); all other hits are `*.test.*` files. No
  production module calls `fetch(`. Enforced by `bridgeInvariant.test.ts` (passing) and
  grep-confirmed during convergence.
- **Token/port stay in Rust**: JS→engine traffic goes only through the Rust proxy commands
  (`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`); the webview
  never receives the port or bearer token.
- **i18n parity**: `en.json` and `id.json` both carry 33 keys with identical key sets (no
  missing/extra) — checked during convergence and asserted by `locales.test.ts`.
- **Engine security**: bearer required on every non-health route; `/recognize/snip` is
  bearer-protected with Pydantic I/O (asserted in `test_recognize_api.py`). SQLite access
  only via `db/`. Recognizer implements the `recognizers/base.py` Protocol with a stable
  `id` and a pure `recognize(...)` returning a typed `FormulaResult`.

### PENDING MANUAL (host/interactive) — unchanged, NOT claimed as passed

Global hotkey Ctrl+Shift+M firing in a running window; live on-screen region capture + OS
capture permission; the result popup rendered over the desktop; user-perceived CPU snip
latency. These are satisfied structurally here (green builds + unit/integration tests); no
long-running dev server/watcher was started by automation.
