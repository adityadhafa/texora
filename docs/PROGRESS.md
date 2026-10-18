# Texora — Build Progress Checkpoint

Last updated: 2026-10-18 (checkpoint 5) · Current milestone: **M2 (single-image formula OCR)** —
**implemented (self-reported), NOT yet reviewer-verified; build is RED at the stop point.** M1 is
**DONE and merged to `main`**.

> Paused by user request MID-IMPLEMENTATION. The M2 implement step committed all six tasks' code
> before the stop, but (a) the semantic reviewer never ran, so every `[x]` is self-reported not
> gate-verified, and (b) the Rust/Tauri build was FAILING (`cargo` exit 101) and the engine
> PyInstaller freeze was incomplete when stopped. So M2 is "mostly written but not green." Scratch
> build-wrapper files were cleaned up; the worktree is otherwise clean. See "Exact next step" below.

## Milestone status at a glance
- **M1 — Skeleton: DONE, merged to `main` @ `77e0114`.** All 7 tasks (1.1–1.7) implemented,
  reviewer-APPROVED, fast-forward merged. Worktree removed. Three host-limited items recorded as
  pending-manual (never faked): `tauri dev` window opening [1.2]; live status badge in a running
  window [1.4]; CI "installs and launches" on a real GitHub runner [1.6].
- **M2 — Single-image formula OCR: IMPLEMENTED (self-reported), NOT reviewer-verified, build RED.**
  Branch `feat/m2-formula-ocr` (worktree `.worktrees/m2-formula-ocr`) @ `f3283a9`. All six tasks
  2.1–2.6 have code committed and are ticked `[x]` in tasks.md BY THE CODER (not independently
  reviewed). `docs/m2-verification.md` exists (~15 KB). Engine files present:
  `models/{catalog,downloader,registry,store,bundle,progress,errors}.py`,
  `recognizers/{base,factory,formula_pix2tex}.py`; snip UI + Rust proxy + hotkey/capture committed.
  KNOWN RED at stop: `cargo` build exit 101 (Rust proxy/transport) and the engine freeze did not
  complete. The real pix2tex fetch/hash + real-inference evidence must be re-confirmed (the stop
  landed before the reviewer could check it). NOT merged.
- M3–M8: not started.

## Git state
- `main` @ `77e0114` — contains all of M1. This is the integration branch; milestones merge here
  after reviewer approval via fast-forward.
- `feat/m2-formula-ocr` @ `6463bdf` (worktree `.worktrees/m2-formula-ocr`): one docs commit on top
  of `main` holding the APPROVED M2 v4 design + plan + FEAT artifacts under `.agents/tasks/`. No
  engine/UI/Rust code yet. Do NOT merge — M2 implementation hasn't run.
- Backup copies of the M2 design + its review also live at `.agents/tasks/m2-salvage/` on `main`.

## M1 task status (all DONE, on `main`)
| Task | Status | Key evidence |
|---|---|---|
| 1.1 Monorepo scaffold | DONE | pnpm workspace (pnpm@9.15.9), desktop package named `desktop`. |
| 1.2 Tauri v2 app | DONE (host-limited) | React18+TS strict+Vite7+Tailwind3.4+Tauri2.12; pnpm lint/test/build + cargo fmt/clippy/build/test green. Pending-manual: `tauri dev` window. |
| 1.3 Python engine skeleton | DONE | FastAPI `/healthz` 200, constant-time bearer on `/engine/info`, loopback, rotating logs. ruff/black/mypy clean, pytest 4/4. |
| 1.4 Supervisor + IPC | DONE (host-limited) | `supervisor.rs` token+free-port+spawn+health+backoff; single typed `engineClient.ts` (grep-confirmed sole invoke/listen importer); `EngineStatusBadge` i18n id+en. 7 Rust + 6 FE tests. Pending-manual: live badge in a window. |
| 1.5 PyInstaller freeze | DONE | Frozen `texora-engine-x86_64-pc-windows-msvc.exe` (gitignored) smoke-served `/healthz` 200. |
| 1.6 CI Windows installer | DONE (host-limited) | `.github/workflows/ci.yml` (engine-checks/frontend-checks/build-installer, all `windows-latest`, pinned actions). Pending: real-runner install+launch. |
| 1.7 LICENSES.md bootstrap | DONE | One row per dep across all manifests; `reqwest`→`ureq` reconciled; no Surya/PyMuPDF. |

Full M1 verification evidence: `docs/m1-verification.md` (§1.2–§1.6).

## M2 status detail (branch `feat/m2-formula-ocr`, commit `6463bdf`)
- **Design: APPROVED (v4).** `.agents/tasks/m2-design.md` — design-reviewer verdict APPROVED
  (0 HIGH, 0 MEDIUM, 1 non-blocking nit). Review at `.agents/tasks/m2-design-review.md`.
- **Plan: written.** `.agents/tasks/m2-plan.md` — 24 ordered items; FEAT-001..005 under
  `.agents/tasks/task-m2-formula-ocr/`.
- **Code: NONE.** No engine recognizer, no model registry, no snip UI, no Rust proxy yet.

### Settled M2 decisions (FINAL — do not re-debate on resume)
1. **Default model = pix2tex / LaTeX-OCR** (MIT code + MIT weights, CPU-runnable). Surya/GPL/
   non-commercial excluded as default.
2. **SHA-256 = pin-on-first-fetch.** Bypass pix2tex's built-in auto-downloader; fetch weights from
   the immutable per-tag GitHub release-asset URL (lukas-blecher/LaTeX-OCR); on first fetch download
   once, compute our OWN SHA-256, record it in `catalog.py`, and verify every load + offline import
   against it. Honesty caveat to document: this is OUR hash of the upstream asset, not a vendor-
   signed checksum — an accepted, documented R-INST-2/3 satisfaction for the provisional M2 default.
   The coder MUST fetch real assets and compute real hashes — NEVER invent a hash.
3. **Confidence contract both ways** (AC-6): token_logprob ∈ (0,1] if scores exist, else
   `confidence=0.0` / `kind="unavailable"` with a vitest-asserted "confidence unavailable" UI state.
4. **KaTeX allow-list generator**: input pinned with a verified fallback (katex public API /
   `katex.mjs` registry primary; vendored source tarball + recorded SHA fallback).
5. **ModelProgress event**: Pydantic model + mirrored TS type; supervisor polls `GET /models/{id}`
   every 500 ms, emits `engine://model-progress`, stops on a terminal state.
- Spec errata flagged but NOT silently applied: tasks.md 2.2 still names PP-FormulaNet-S as default
  (pix2tex supersedes it per granted latitude); R-REC-6 wording "render check (KaTeX)". Owner to
  reconcile the spec text when convenient.
- AsciiMath and OMML copy deferred to M6 (permissive-first; OMML is an R-UI-2 erratum, flagged).

## Toolchains (host: Windows, bash) — ALL INSTALLED & VERIFIED
- **Node 24.14.0**, **pnpm** via corepack `pnpm@9.15.9` (also winget pnpm present).
- **Rust cargo/rustc/clippy 1.99.1** in `~/.cargo/bin`; **MSVC linker + Win10 SDK 10.0.26100.0
  installed** — cargo/tauri build run locally but need `vcvars64.bat` loaded first in a fresh shell.
- **Python 3.11.9 + pip** at `%LOCALAPPDATA%\Programs\Python\Python311`; engine venv at
  `engine/.venv` (gitignored). Use `engine/.venv/Scripts/python.exe` for engine work.

### Required PATH export for every build/test/git command
```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

## Standing orchestration decisions (from the user)
- Build the whole app milestone by milestone (M2→M8), each verified against its `done:` criteria,
  each accepted (fast-forward `main` + remove worktree) only after reviewer APPROVED.
- **Review gating:** FULL iterate-until-approved loop on correctness-critical milestones
  **M2–M5, M7**; a lighter single review pass on the mechanical ones **M6 (exporters), M8 (polish)**.
- **M2 model download + real CPU inference is approved** (real network fetch, multi-hundred-MB).
  No mocked OCR in production paths, ever.
- Honesty rule: never claim a check passed that wasn't run; host-limited items are documented as
  pending, not reported done.

## Errors / blockers
- **ACTIVE: Rust/Tauri build is RED.** At the stop point `cargo` exited 101 building the M2 Rust
  engine-proxy / transport additions in `apps/desktop/src-tauri`. Must be diagnosed and fixed first
  on resume (load vcvars64.bat before cargo). Likely a compile error in the new proxy command /
  model-poller code (commit `da780e9`), not an environment issue (M1 Rust built fine).
- **ACTIVE: engine PyInstaller freeze incomplete.** The freeze run was interrupted; not a failure
  per se, just unfinished. Re-run `scripts/build_engine.py` after the engine side is green.
- **UNVERIFIED (not a blocker, but do not trust as done):** all M2 `[x]` ticks are coder
  self-reports; the semantic reviewer never ran. The real pix2tex weight fetch + SHA-256 pin +
  real-CPU-inference evidence in `docs/m2-verification.md` needs independent confirmation. The
  earlier design-level HIGH (no pinnable SHA-256) is resolved by decision 2 (pin-on-first-fetch).

## Exact next step to resume (M2 — converge the existing implementation, do NOT restart it)
The code is already written on `feat/m2-formula-ocr` (`f3283a9`); the job now is to make it GREEN
and get it reviewer-APPROVED, NOT to reimplement. Relaunch an implement-and-review loop pointed at
the existing worktree `.worktrees/m2-formula-ocr` with this order:
1. **Fix the RED Rust build FIRST.** In `apps/desktop/src-tauri`, load vcvars64.bat, run
   `cargo build` + `cargo clippy -D warnings`, read the actual errors, fix the proxy/transport code
   (commit `da780e9` area). Do not proceed until cargo is green.
2. **Re-run the full per-stack verification** and record REAL output in `docs/m2-verification.md`
   (overwrite the self-reported sections with actually-run evidence): engine ruff/black/mypy/pytest
   (venv); frontend `pnpm --filter desktop lint/test/build`; cargo fmt/clippy/build/test.
3. **Confirm the pix2tex story for real:** that `catalog.py` holds a REAL computed SHA-256 (not a
   placeholder), that the downloader rejects a corrupt file (the required test), and that the
   recognizer runs REAL CPU inference on the committed fixture (no mocks). If pix2tex cannot run on
   this CPU host, pause and ask — do not fake output. Re-run the engine freeze when green.
4. **Then the semantic reviewer runs** and writes `.agents/tasks/m2-review.json`; loop back on any
   HIGH/MEDIUM finding. M2 is correctness-critical → full iterate-until-APPROVED loop.
5. Only after M2 is reviewer-APPROVED: fast-forward `main` to `feat/m2-formula-ocr`, remove the
   worktree + branch, then start M3. Do NOT re-run M1 tasks and do NOT discard the existing M2 code.
