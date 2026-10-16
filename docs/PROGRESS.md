# Texora — Build Progress Checkpoint

Last updated: 2026-10-16 (checkpoint 3) · Milestone: **M1 (skeleton)** · Branch: `feat/m1-skeleton`
(worktree `.worktrees/m1-skeleton`). NOT merged into `main`. M2 not started.

## M1 task status (tasks 1.1–1.7)

| Task | Status | Notes |
|---|---|---|
| 1.1 Monorepo scaffold | **DONE** | pnpm workspace (pinned pnpm@9.15.9), full `structure.md` tree. Desktop app package MUST be named `desktop` (root scripts use `--filter desktop`). Commit `8a61f72`. |
| 1.7 LICENSES.md bootstrap | **DONE** (seed, kept updated) | `docs/LICENSES.md` seeded + extended as deps were added (engine + PyInstaller rows reconciled). No Surya/PyMuPDF deps. Commit `8a61f72` + later. |
| 1.3 Python engine skeleton | **DONE** | Real FastAPI + Uvicorn + Pydantic v2 `engine/texora_engine`: open `GET /healthz` (200); bearer-token auth (constant-time) guarding `GET /engine/info`; loopback bind; CLI `--host/--port/--token` + `TEXORA_ENGINE_TOKEN`; rotating-file logging. Verified in 3.11 venv: ruff/black/mypy clean, pytest 4/4 (healthz 200; /engine/info 401 missing, 401 wrong, 200 correct). Commit `5b4c882`. Evidence: `docs/m1-verification.md` §1.3. |
| 1.5 PyInstaller freeze | **DONE** | `scripts/build_engine.py` + `.sh`/`.ps1` + optional `engine/texora-engine.spec` + `scripts/smoke_sidecar.py`. Froze against **real Python 3.11.9** → `apps/desktop/src-tauri/binaries/texora-engine-x86_64-pc-windows-msvc.exe` (14.9 MB, gitignored). Smoke PASS: frozen binary served `/healthz` 200 then torn down. Pinned pyinstaller==6.22.3 + hooks-contrib==2026.8. Commit `d35e595`. Evidence: `docs/m1-verification.md` §1.5. |
| 1.2 Tauri v2 app | **DONE** (host-limited caveat) | React 18 + TS strict + Vite 7 + Tailwind 3.4 + Tauri 2.12 scaffold; crate `texora-desktop`; `externalBin` wired to `binaries/texora-engine`; dark/light theme tokens. Verified: `pnpm --filter desktop lint/test/build` pass, `cargo fmt --check/clippy -D warnings/build/test` pass in src-tauri. Commits `106a188`+`fbc7498`. **Host-limited:** the interactive `tauri dev` window opening is a manual check (never faked). |
| 1.4 Rust supervisor + IPC | **DONE** (host-limited caveat) | `supervisor.rs`: 256-bit session token, free loopback port, dev (`python -m texora_engine`)/prod (externalBin) spawn via `tauri-plugin-shell`, `ureq` `/healthz` polling, capped exponential backoff; `lib.rs` exposes `engine_status` + emits `engine://status`; single typed `engineClient.ts` (the ONLY module importing invoke/listen — grep-confirmed); `EngineStatusBadge` on Home via i18next (id+en). 7 Rust unit tests + 6 frontend tests pass. Commit `333ba44`. **Host-limited:** live badge observed in a running window is a manual check. |
| 1.6 CI Windows installer | **DONE** (host-limited caveat) | `.github/workflows/ci.yml`: `engine-checks` (ruff/black/mypy/pytest), `frontend-checks` (lint/test/build), `build-installer` (PyInstaller freeze → `pnpm --filter desktop tauri build` → upload .msi/.exe). All jobs `windows-latest`; actions pinned; Python 3.11.9 / Node 24.x / pnpm 9.15.9. Commit `52fd51a`. **Host-limited:** the "artifact installs and launches" end-to-end is only provable on a real GitHub runner (never faked locally). |

## Toolchains (host: Windows, bash) — ALL INSTALLED & VERIFIED

- **Node 24.14.0** (default PATH), **pnpm 12.11.2** (winget) + corepack `pnpm@9.15.9` activated.
- **Rust cargo/rustc/clippy 1.99.1** in `~/.cargo/bin`.
- **Python 3.11.9 + pip** at `%LOCALAPPDATA%\Programs\Python\Python311`. Engine venv already created
  at `engine/.venv` (gitignored, bare — deps installed per task).
- Tauri CLI = per-project pnpm devDependency (not system). `corepack enable pnpm` fails EPERM → use
  `corepack prepare pnpm@9.15.9 --activate` or the winget pnpm.

### Required PATH export for every build/test/git command
```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```
For engine work use the venv python at `engine/.venv/Scripts/python.exe`.

## Errors / blockers
- None active. All seven M1 tasks (1.1–1.7) are implemented and verified at the local level. The
  only unverified items are genuinely host-limited and recorded honestly as pending manual/CI
  confirmation (never faked): (a) `tauri dev` window opening [1.2]; (b) live status badge observed
  in a running window [1.4]; (c) CI "artifact installs and launches" on a real GitHub runner [1.6].

## Cross-feature integration verification (checkpoint 3, whole skeleton)
Full suite re-run green across all three stacks with the PATH export:
- Frontend (worktree root): `pnpm install` (up to date), `pnpm --filter desktop lint` (clean),
  `pnpm --filter desktop test -- --run` (6/6), `pnpm --filter desktop build` (typecheck + vite).
- Rust (`apps/desktop/src-tauri`): `cargo fmt --check` (clean), `cargo clippy --all-targets -- -D
  warnings` (clean), `cargo build`, `cargo test` (7/7 supervisor unit tests).
- Engine (venv python): `ruff check .` (clean), `black --check . --line-length 100` (clean),
  `mypy texora_engine` (clean), `pytest -q` (4/4).

Seams checked between FEAT-M1C-002 (Tauri app) / -004 (supervisor + client) / -006 (CI):
- Rust `EngineState`/`EngineStatus` serialize `camelCase` and match the TS `EngineState` union +
  `EngineStatus` interface in `engineClient.ts`; command name `engine_status` and event name
  `engine://status` agree on both sides.
- `engineClient.ts` is the ONLY production module importing `invoke`/`listen` (grep-confirmed; test
  files only mock them).
- Dev-mode engine spawn (`python -m texora_engine`) is a Rust-core spawn via `tauri-plugin-shell`,
  not a WebView `Command` call, so the sidecar-only `shell:allow-execute` capability scope is
  correct and does not block dev spawning (capability scope gates WebView→core calls).
- `tauri.conf.json` `externalBin: ["binaries/texora-engine"]` matches the supervisor `SIDECAR_NAME`
  and the freeze output name in `scripts/build_engine.py`; CI invokes `build_engine.py --python
  python --triple x86_64-pc-windows-msvc`, which the script's argparse accepts.
- `docs/LICENSES.md` reconciled: every row in `engine/requirements*.txt`, `engine/pyproject.toml`,
  `apps/desktop/package.json`, and `apps/desktop/src-tauri/Cargo.toml` now has a matching row
  (added the previously-missing npm dev-tooling: `@types/react`, `@types/react-dom`, `@types/node`,
  `@eslint/js`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`, `postcss`,
  `autoprefixer`; loose `x` versions pinned to manifest values). The `reqwest` candidate is resolved
  to `ureq` (the sole `/healthz` client) with no leftover candidate row.

## Git state
- `main` @ `1eda554` (specs/steering/hooks) — untouched, do NOT merge yet.
- `feat/m1-skeleton` commits: `8a61f72` scaffold+LICENSES → `33f3bb8` WIP → `5b4c882` engine(1.3) →
  `d35e595` freeze(1.5) → `28be390` WIP Tauri → `9d447e8` checkpoint 2 → `106a188`+`fbc7498`
  Tauri(1.2) → `333ba44` supervisor+client+badge(1.4) → `52fd51a` CI(1.6) → (this) converge+docs.

## Exact next step to resume
1. Reviewer writes `.agents/tasks/m1-review.json`. If findings exist, the convergence fixer applies
   them (ITERATION 2+) and re-runs the relevant checks until green.
2. Only after M1 is verified APPROVED: orchestrator fast-forwards `main`, removes the worktree, and
   starts M2. Do NOT re-run any of 1.1–1.7.
