# Texora — Build Progress Checkpoint

Last updated: 2026-10-17 (checkpoint 4) · Current milestone: **M2 (single-image formula OCR)** —
design APPROVED + planned, **implementation not yet started**. M1 is **DONE and merged to `main`**.

> Paused by user request at a clean boundary (M2 design approved, plan written, zero code written).
> Nothing is half-finished. Safe to leave. See "Exact next step to resume" to pick up M2.

## Milestone status at a glance
- **M1 — Skeleton: DONE, merged to `main` @ `77e0114`.** All 7 tasks (1.1–1.7) implemented,
  reviewer-APPROVED, fast-forward merged. Worktree removed. Three host-limited items recorded as
  pending-manual (never faked): `tauri dev` window opening [1.2]; live status badge in a running
  window [1.4]; CI "installs and launches" on a real GitHub runner [1.6].
- **M2 — Single-image formula OCR: design APPROVED, plan written, NOT implemented.** Lives on
  branch `feat/m2-formula-ocr` (worktree `.worktrees/m2-formula-ocr`), commit `6463bdf` — design +
  plan artifacts only, no production code. NOT merged.
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
- None active. The earlier M2 HIGH blocker (pix2tex weights had no pinnable SHA-256) is resolved by
  decision 2 above (pin-on-first-fetch).

## Exact next step to resume (M2 implementation)
1. The design is APPROVED and the plan is written on `feat/m2-formula-ocr` (`6463bdf`). Relaunch the
   M2 **implementation** only (skip the design loop — it's done). Point the implement-and-review
   loop at the existing worktree `.worktrees/m2-formula-ocr` and `.agents/tasks/m2-plan.md` /
   `m2-design.md` / the FEAT artifacts. Full review loop (M2 is correctness-critical).
2. Implement tasks 2.1→2.6 + the JS→engine Rust-proxy transport per the plan, honoring the five
   settled decisions. Task 2.2 does the REAL pix2tex fetch + CPU inference (no mocks); if it can't
   run on this CPU host, pause and ask rather than faking output.
3. Verify per task (engine ruff/black/mypy/pytest; frontend pnpm lint/test/build; cargo
   fmt/clippy/build with vcvars loaded). Record evidence in a new `docs/m2-verification.md`. Tick
   M2 tasks `[x]` in `.kiro/specs/texora/tasks.md`; add LICENSES.md rows (deps + model).
4. Reviewer writes `.agents/tasks/m2-review.json` verdict APPROVED when all `done:` criteria are met
   or host-limitations are honestly documented.
5. Only after M2 APPROVED: orchestrator fast-forwards `main` to `feat/m2-formula-ocr`, removes the
   worktree + branch, then starts M3. Do NOT re-run M1 tasks.
