# Texora — Build Progress Checkpoint

Last updated: 2026-10-16 (checkpoint 2) · Milestone: **M1 (skeleton)** · Branch: `feat/m1-skeleton`
(worktree `.worktrees/m1-skeleton`). NOT merged into `main`. M2 not started.

## M1 task status (tasks 1.1–1.7)

| Task | Status | Notes |
|---|---|---|
| 1.1 Monorepo scaffold | **DONE** | pnpm workspace (pinned pnpm@9.15.9), full `structure.md` tree. Desktop app package MUST be named `desktop` (root scripts use `--filter desktop`). Commit `8a61f72`. |
| 1.7 LICENSES.md bootstrap | **DONE** (seed, kept updated) | `docs/LICENSES.md` seeded + extended as deps were added (engine + PyInstaller rows reconciled). No Surya/PyMuPDF deps. Commit `8a61f72` + later. |
| 1.3 Python engine skeleton | **DONE** | Real FastAPI + Uvicorn + Pydantic v2 `engine/texora_engine`: open `GET /healthz` (200); bearer-token auth (constant-time) guarding `GET /engine/info`; loopback bind; CLI `--host/--port/--token` + `TEXORA_ENGINE_TOKEN`; rotating-file logging. Verified in 3.11 venv: ruff/black/mypy clean, pytest 4/4 (healthz 200; /engine/info 401 missing, 401 wrong, 200 correct). Commit `5b4c882`. Evidence: `docs/m1-verification.md` §1.3. |
| 1.5 PyInstaller freeze | **DONE** | `scripts/build_engine.py` + `.sh`/`.ps1` + optional `engine/texora-engine.spec` + `scripts/smoke_sidecar.py`. Froze against **real Python 3.11.9** → `apps/desktop/src-tauri/binaries/texora-engine-x86_64-pc-windows-msvc.exe` (14.9 MB, gitignored). Smoke PASS: frozen binary served `/healthz` 200 then torn down. Pinned pyinstaller==6.22.3 + hooks-contrib==2026.8. Commit `d35e595`. Evidence: `docs/m1-verification.md` §1.5. |
| 1.2 Tauri v2 app | **PARTIAL / NOT VERIFIED** | Scaffold files authored (React 18 + TS strict + Vite + Tailwind + Tauri 2.12 config, crate `texora-desktop`, externalBin wired, vitest test) but committed as WIP `28be390` when the run was stopped **before any build/lint/test verification**. MUST run `pnpm install` + `pnpm --filter desktop lint/test/build` + `cargo build/clippy` in src-tauri and fix any failures before marking DONE. |
| 1.4 Rust supervisor + IPC | **NOT STARTED** | Token + free-port gen, spawn engine (dev: python; prod: externalBin), health-check, backoff restart; Tauri `engine_status()` cmd + `engine://status` events; single typed `engineClient.ts`; Home live status badge; Rust + client tests. |
| 1.6 CI Windows installer | **NOT STARTED** | `.github/workflows/ci.yml`: engine-checks, frontend-checks, build-installer (freeze + `pnpm --filter desktop tauri build` + upload .msi/.exe). Pin action/tool versions; valid YAML. CI end-to-end "installs and launches" is host-limited (needs real runner). |

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
- None active. Both M1 workflows (`wf_1f435fd8ca33c86b`, `wf_898fdadb8116e289`) were **aborted on
  user request**, not failures. 1.2 is simply unverified because the stop landed mid-task.

## Git state
- `main` @ `1eda554` (specs/steering/hooks) — untouched, do NOT merge yet.
- `feat/m1-skeleton` commits: `8a61f72` scaffold+LICENSES → `33f3bb8` WIP checkpoint →
  `5b4c882` engine(1.3) → `d35e595` freeze(1.5) → `28be390` WIP Tauri scaffold(1.2, unverified).

## Exact next step to resume
1. Shell in `.worktrees/m1-skeleton`, apply the PATH export above.
2. **Finish & VERIFY task 1.2**: `pnpm install`, then `pnpm --filter desktop lint`,
   `pnpm --filter desktop test -- --run`, `pnpm --filter desktop build`, and `cargo build` +
   `cargo clippy` + `cargo fmt --check` in `apps/desktop/src-tauri`. Fix failures. Record output in
   `docs/m1-verification.md` §1.2, then commit 1.2 as done (promote the WIP).
3. Then **1.4** (supervisor + typed client + live status) → **1.6** (CI) in order, each verified
   against its `tasks.md` `done:` check.
4. Run the converge/verify + review loop over the whole skeleton; update this file to final status.
5. Only after M1 is verified APPROVED: orchestrator fast-forwards `main`, removes the worktree, and
   starts M2. Do NOT re-run 1.1/1.3/1.5/1.7.
