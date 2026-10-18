# Texora — Build Progress Checkpoint

Last updated: 2026-10-18 (M2 convergence) · Milestone: **M2 (single-image formula OCR)** ·
Branch: `feat/m2-formula-ocr` (worktree `.worktrees/m2-formula-ocr`). NOT merged into `main`.
M1 is complete and merged; M2 is implemented and **converged to green** on this host.

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
