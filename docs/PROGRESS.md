# Texora — Build Progress Checkpoint

Last updated: 2026-10-18 (M3 FEAT-005) · Milestone: **M3 (PDF pipeline → MD/LaTeX)** ·
Branch: `feat/m3-pdf-pipeline` (worktree `.worktrees/m3-pdf-pipeline`). NOT merged into `main`.
M1 and M2 are complete; M3 tasks 3.1–3.7 are implemented on this branch (engine-side; the headline
PDF→Markdown/LaTeX flow is runnable + demonstrated). The TeX-compile check is CI-only on hosts
without a TeX toolchain.

Required engine commands run with the PATH export + the worktree venv
(`engine/.venv/Scripts/python.exe`), from `engine/`:
`export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:...:$PATH"`.

## M3 feature status (tasks 3.1–3.7)

| Feature | Tasks | Status | Notes |
|---|---|---|---|
| FEAT-001 foundation | deps + `pipeline.yaml` stages + typed ingest/settings | **DONE** | M3 runtime deps pinned (`pypdfium2` 5.14.0, `pillow-heif` 0.18.0, `onnxruntime` 1.19.2, `pytesseract` 0.3.13) + license rows; `pytest.mark.model`/`latex` markers registered. See `docs/m3-verification.md`. |
| FEAT-002 ingest | 3.1 render/load/detect · 3.2 preprocess | **DONE** | `ingest/` package: pypdfium2 render (adaptive DPI + one-shot small-font raise), image loaders incl. HEIC/TIFF, born-digital/scanned detection, toggleable preprocessing. Single point→pixel conversion site. |
| FEAT-003 layout | 3.3 layout Protocol + default · 3.4 reading order | **DONE** | `layout/` package implemented fresh as ONE coherent API: `LayoutDetector` Protocol + full `RegionType` taxonomy; permissive-only factory (`pp_doclayout_onnx`, Apache-2.0; AGPL `doclayout_yolo` present but unregistered/opt-in); no-model `born_digital` structural detector; pure XY-cut reading order with column + equation-number binding. Catalog pins 3 ONNX models (file names now, URL/SHA pin-on-first-fetch) + Apache-2.0 license rows. Full gate green. |
| FEAT-004 text + assembler | 3.5 PP-OCRv5 + Tesseract (EN+ID) · 3.6 page assembly + `POST /pages/recognize` | **DONE** | Delivered together as FEAT-004 (tasks 3.5 + 3.6). `TextRecognizer` Protocol (reusing the single `layout.base.BBox`); `pp_ocrv5_onnx` PP-OCRv5 det+rec via ONNX Runtime (DB post-process via shapely+pyclipper, CTC decode via `rec_keys.txt`) + `tesseract` fallback (EN+ID). Single-owning fallback decision in `build_text_recognizer` (full §7.2.1 table covered). `pipeline/` assembler merges ingest→layout→reading-order→recognition into typed `PageResult`/`DocumentResult`, reusing the M2 pix2tex `build_formula_recognizer` UNCHANGED for all math; TABLE/HANDWRITING → `needs_review` (M6). `POST /pages/recognize` bearer-protected (409/422/500 mapping). `shapely`/`pyclipper` pinned + license rows added in this change. Full gate green. |
| FEAT-005 export + M3 docs | 3.7 Markdown + LaTeX + golden files | **DONE** | THE HEADLINE OUTPUT. `export/markdown.py` + `export/latex.py` + `export/templates.py`: ordered `InlineRun` interleaving so inline `$...$` lands mid-paragraph (design F5); numbered/unnumbered display math (`$$...$$ \tag{n}` / `equation`/`equation*`); honest TABLE/needs_review markers, never fabricated. Byte-stable golden `.md`/`.tex` from a fixed `DocumentResult` (test data). Real born_digital_math.pdf→Markdown via the real pix2tex engine recorded in `docs/m3-verification.md`. No new runtime dep (stdlib + existing Pydantic). The demo surfaced + fixed a committed born-digital span-ordering bug in the assembler (line-banding, tightly scoped; regression test added). `latexmk` compile is `@pytest.mark.latex` → xfail-skip locally (no TeX toolchain), asserted in CI. Full gate green. |

### FEAT-003 gate (this change) — all green on this host
`ruff check .` clean · `black --check . --line-length 100` clean · `mypy texora_engine` clean
(45 files) · `pytest -q` → **114 passed, 5 skipped** (5 skips = 3 M2 pix2tex model-gated + 2 M3
PP-DocLayout model-gated, all skip-with-reason when ONNX weights absent — never mocked). Full
command output in `docs/m3-verification.md` §FEAT-003.

### FEAT-003 PENDING / host-limited (recorded honestly, never claimed passed)
- **PP-DocLayout ONNX weights** — URL + SHA-256 are pin-on-first-fetch at adoption; the
  `@pytest.mark.model` weight-backed layout test skips-with-reason until weights are prefetched.
  Failure-injection (corrupt session → empty `LayoutResult`, never raises) runs WITHOUT weights.
- **CUDA execution provider** — code-review-only on this CPU host; `CPUExecutionProvider` is tested.
- **DocLayout-YOLO (AGPL)** — opt-in adapter present but not installed, not registered, not in any
  default path.

### FEAT-004 gate (this change) — all green on this host
`ruff check .` clean · `black --check . --line-length 100` clean · `mypy texora_engine` clean
(52 files) · `pytest -q` → **135 passed, 12 skipped** (12 skips = 3 M2 pix2tex + 2 FEAT-003 layout
+ 7 FEAT-004 model-/binary-gated tests, all skip-with-reason when ONNX weights / the Tesseract
binary are absent — never mocked). Full command output in `docs/m3-verification.md` §FEAT-004.

### FEAT-004 PENDING / host-limited (recorded honestly, never claimed passed)
- **Tesseract binary ABSENT on this host** — the real EN/ID accuracy test and the live
  fallback-degrade path are documented PENDING (host-limited); the factory decision that *selects*
  Tesseract is fully covered by monkeypatching. Install Tesseract 5.x or set
  `TEXORA_ENGINE_TESSERACT_CMD` to exercise the real fallback.
- **PP-OCRv5 ONNX weights** — pin-on-first-fetch; the real EN/ID recognition test + the
  pix2tex-backed assembler/API-200 path skip-with-reason until weights are prefetched (never mocked).
- **CUDA execution provider** — code-review-only on this CPU host; `CPUExecutionProvider` is tested.

### FEAT-005 gate (this change) — all green on this host
`ruff check .` clean · `black --check . --line-length 100` clean (90 files) ·
`mypy texora_engine` clean (55 files) · `pytest -q` → **150 passed, 9 skipped, 1 xfailed** (9 skips
= PP-DocLayout + PP-OCRv5 ONNX weights pin-on-first-fetch + Tesseract binary absent, all
skip-with-reason; 1 xfail = the `latexmk` compile, no TeX toolchain). The real pix2tex model-gated
tests PASS (weights prefetched + SHA-256 verified). Full command output + the real PDF→Markdown
sample in `docs/m3-verification.md` §FEAT-005.

### FEAT-005 PENDING / host-limited (recorded honestly, never claimed passed)
- **LaTeX `latexmk` compile** — no TeX toolchain on this host; `test_golden_tex_compiles_with_latexmk`
  xfail-skips with a recorded reason and is NOT deleted/silently passed. The CI `m3-latex-compile`
  job provisions TinyTeX/texlive and runs the real exit-0 compile no-skip. No compile has run here.
- **Born-digital layout characteristics** surfaced by the real demo (inter-word spacing from the
  fixture's space-less show-text ops; two-column text merged by the full-width born-digital paragraph
  regions) are FEAT-003 born-digital-layout limitations tracked separately — NOT exporter defects and
  out of FEAT-005's span-ordering scope. The exporter faithfully renders the regions it is given.

---

## M2 reference (complete; context for M3)

M1 is complete and merged; M2 is implemented and **converged to green** on this host
(`feat/m2-formula-ocr`). The M2 detail below is retained for context.

## M2 task status (tasks 2.1–2.6) — all DONE, all gates green

| Task | Status | Notes |
|---|---|---|
| 2.1 Model registry + downloader | **DONE** | `MODEL` table + pinned catalog (`models/catalog.py`) with **real** SHA-256 for the pix2tex `weights.pth` + `image_resizer.pth` (computed on this host; sizes cross-checked against the immutable upstream release URLs at tag `v0.0.1`). Checksum downloader promotes good-hash → `ready` and **rejects** bad-hash (deletes `.part`, raises `ChecksumMismatch`). Offline bundle import. SQLite via `db/` (WAL). |
| 2.2 FormulaRecognizer + default engine | **DONE** | Protocol in `recognizers/base.py`; **pix2tex (LaTeX-OCR, MIT)** adapter doing REAL CPU inference on local-only weights (never triggers pix2tex's own downloader). Confidence honestly `unavailable` (pinned pix2tex exposes no usable per-token scores) — never fabricated. Factory wires it via `pipeline.yaml`. Spec erratum (PP-FormulaNet-S wording) kept in `tasks.md`. |
| 2.3 LaTeX normalize + validate + MathML | **DONE** | KaTeX supported-macro allow-list (generated from the pinned `katex` npm, cannot drift) + structural validate/normalize + `latex2mathml`. The authoritative real-KaTeX render is the UI check (R-REC-6 erratum flagged in `tasks.md`). |
| 2.4 `POST /recognize/snip` | **DONE** | Bearer-protected; Pydantic I/O; decode guards (malformed/oversized → 422, never 500); per-snip timeout → `status=failed`; `asciimath` always null (M6). |
| 2.6 Hardware detect + device override | **DONE** | `GET /hardware` + `POST /hardware/device` (bearer); torch-based device detection; selection persisted in `setting`; unknown device → 422. Settings UI consumes it. |
| 2.5 Snip Tool UI | **DONE** (host-limited caveats) | Rust global hotkey Ctrl+Shift+M + `xcap` capture → base64 PNG → event; typed `engineClient` proxies to the engine via Rust commands (token/port stay in Rust); result popup with LaTeX/MathML/Markdown copy + authoritative KaTeX preview + confidence-unavailable state; i18next id+en. Live hotkey/capture/popup/latency are PENDING MANUAL (never faked). |

## Convergence summary (2026-10-18)

The Rust/Tauri build had been red (exit 101) purely because the `externalBin` sidecar did not
exist — the PyInstaller freeze never finished placing it. **Root cause:** PyInstaller's
Windows post-assembly rewrites the PE build-timestamp/checksum *in place*, which fails with
`OSError(22)` on this ~570 MB torch-bundled onefile because `pefile` had just memory-mapped
the path. **Fix (committed, in `scripts/build_engine.py`):** when PyInstaller exits non-zero
but the onefile exists on Windows, finish the timestamp/checksum fix-up ourselves via
temp-file + atomic replace, then place the sidecar. No engine behavior changed; no unverified
binary is shipped. The sidecar is gitignored (never committed).

With the sidecar present, all three stacks are green (full output in `docs/m2-verification.md`
§"Convergence re-run (2026-10-18)"):

- **Engine** (venv python, from `engine/`): `ruff check .` clean · `black --check . --line-length 100` clean · `mypy texora_engine` clean (32 files) · `pytest -q` → **59 passed** (incl. the real-model pix2tex inference on the committed fixture, NOT skipped, and the bad-hash rejection test).
- **Frontend** (worktree root): `pnpm --filter desktop lint` clean · `pnpm --filter desktop test -- --run` → **33 passed (8 files)** · `pnpm --filter desktop build` → strict tsc + vite build OK.
- **Rust** (`apps/desktop/src-tauri`, MSVC env loaded): `cargo fmt --check` clean · `cargo clippy --all-targets -- -D warnings` clean · `cargo build` OK · `cargo test` → **14 passed**.

### Invariants re-checked (no regressions)
- `engineClient.ts` is the ONLY production module importing `@tauri-apps/api` (`invoke`/`listen`); no production `fetch(`; enforced by `bridgeInvariant.test.ts`.
- JS→engine traffic only via Rust proxy commands; port + bearer token never reach the webview.
- i18n `en.json`/`id.json` parity: 33 keys each, identical sets.
- Bearer required on every non-health route; `/recognize/snip` bearer-protected with Pydantic I/O; SQLite only via `db/`; recognizer implements the `recognizers/base.py` Protocol.

## Toolchains (host: Windows, bash)

- **Node 24.x**, **pnpm 9.15.9**. **Rust cargo/rustc/clippy** in `~/.cargo/bin`. **Python 3.11.9** at `%LOCALAPPDATA%\Programs\Python\Python311`; engine venv at `engine/.venv` (gitignored) with the M2 runtime stack (pix2tex/torch-cpu/pyinstaller) installed.
- MSVC build env is required for cargo: load `vcvars64.bat` (BuildTools 2022) before any cargo command so `link.exe` + the Win10 SDK LIB are on PATH.

### Required PATH export for every build/test/git command
```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```
For engine work use the venv python at `engine/.venv/Scripts/python.exe`.

## PENDING MANUAL (host/interactive) — recorded honestly, never claimed passed
- Global hotkey **Ctrl+Shift+M** firing in a running `tauri dev` window.
- Live on-screen **region capture** + OS screen-capture permission.
- The **result popup** rendered over the desktop.
- User-perceived **CPU snip latency** (the ≤1.5 s R-UI-2 target is a GPU target).

These are satisfied structurally (green builds + unit/integration tests); no long-running dev
server/watcher was started by automation.

## Errors / blockers
- None active. M2 (2.1–2.6) is implemented and verified green at the local level; the only
  unverified items are genuinely host-limited and recorded as pending manual.

## Git state
- `main` untouched — do NOT merge yet.
- `feat/m2-formula-ocr`: M2 tasks committed (`2b7e070` → `f3283a9`), plus the convergence
  fix commits on top (engine freeze fix-up + rustfmt nit + refreshed verification/progress/
  license docs).

## Exact next step to resume
1. Reviewer writes `.agents/tasks/m2-review.json`. If findings exist, the convergence fixer
   applies them (ITERATION 2+) and re-runs the relevant checks until green.
2. Only after M2 is verified APPROVED: orchestrator fast-forwards `main`, removes the
   worktree, and starts M3. Do NOT re-run 2.1–2.6.
