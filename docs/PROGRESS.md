# Texora — Build Progress Checkpoint

Last updated: 2026-10-16 · Milestone: **M1 (skeleton)** · Branch: `feat/m1-skeleton` (worktree
`.worktrees/m1-skeleton`). NOT merged into `main`. M2 not started.

## M1 task status (tasks 1.1–1.7)

| Task | Status | Notes |
|---|---|---|
| 1.1 Monorepo scaffold | **DONE** | pnpm workspace (pinned pnpm@9.15.9), root tooling, full `structure.md` tree with `.gitkeep` in empty stage dirs. `pnpm install` exits 0, `pnpm-lock.yaml` written. Root scripts delegate via `--filter desktop` → the desktop package MUST be named `desktop`. Committed `8a61f72`. |
| 1.7 LICENSES.md bootstrap | **DONE** (seed) | `docs/LICENSES.md` seeded with every M1 dep (licenses verified vs PyPI/npm/crates.io) + PyMuPDF/Surya opt-in policy. No Surya/PyMuPDF deps added. Will grow as later tasks add deps. Committed `8a61f72`. |
| 1.2 Tauri v2 app | **NOT STARTED** | Tauri 2.12.x + React 18 + TS(strict) + Vite + Tailwind in `apps/desktop`; blank Home + dark/light tokens. Package must be named `desktop`. Add `@tauri-apps/cli` (pin 2.x) as a pnpm devDependency; invoke via `pnpm tauri`. |
| 1.3 Python engine skeleton | **NOT STARTED** | FastAPI + Uvicorn + Pydantic v2 in `engine/texora_engine`; `GET /healthz`; bearer-token middleware (401 w/o token, 200 with); loopback bind; rotating logging; pytest. Use Python **3.11** venv. |
| 1.4 Rust supervisor + IPC | **NOT STARTED** | Rust token+free-port gen, spawn engine, health-check, restart-with-backoff; typed TS client; Home shows live `/healthz` status. |
| 1.5 PyInstaller freeze | **NOT STARTED** | `scripts/` build → self-contained engine binary; Tauri `externalBin` naming `<name>-$TARGET_TRIPLE`; frozen binary serves `/healthz`. |
| 1.6 CI Windows installer | **NOT STARTED** | GitHub Actions: engine freeze + Tauri `.msi/.exe` on windows-latest + lint/test checks. |

## Toolchains (host: Windows, bash)

Installed & verified this session:
- **Node 24.14.0** — on default PATH.
- **pnpm 12.11.2** (winget) AND project pins **pnpm@9.15.9** via corepack. ⚠️ `corepack enable pnpm`
  fails EPERM (writes to `C:\Program Files\nodejs`). Use `corepack prepare pnpm@9.15.9 --activate`
  then `corepack pnpm`, OR the winget pnpm on PATH.
- **Rust: cargo/rustc/clippy 1.99.1** — in `~/.cargo/bin` (NOT on default bash PATH).
- **Python 3.11.9 + pip 24.0** — at `%LOCALAPPDATA%\Programs\Python\Python311` (NOT on default
  PATH; system `python` is 3.14 — do not use it for the engine).

**Missing:** Tauri CLI (intentionally — install per-project as a pnpm devDependency, not system-wide).

### Required PATH export for every build/test command
```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

## Errors / blockers
- `corepack enable pnpm` → `Internal Error: EPERM: operation not permitted, open
  'C:\Program Files\nodejs\pnpm'`. Workaround above. Not blocking.
- No other active blockers. The M1 workflow (`wf_1f435fd8ca33c86b`) was **aborted on user request**
  after FEAT-001; it was NOT a failure.

## Git state
- `main` @ `1eda554` (specs/steering/hooks) — untouched.
- `feat/m1-skeleton` @ `8a61f72` (scaffold + LICENSES seed) + this checkpoint commit.
- Do NOT merge into `main` until M1 is complete and verified.

## Exact next step to resume
1. Open shell in `.worktrees/m1-skeleton`, apply the PATH export above.
2. Start **task 1.2**: scaffold Tauri 2.12.x app in `apps/desktop` (package name `desktop`),
   React 18 + TS strict + Vite + Tailwind, blank Home + theme tokens, add `@tauri-apps/cli` 2.x
   devDep; verify `pnpm --filter desktop build` and `pnpm tauri` resolve.
3. Then 1.3 → 1.4 → 1.5 → 1.6 in order, each verified against its `tasks.md` `done:` check.
4. Relaunch the implement-and-review workflow for the remaining M1 tasks (1.2–1.6) OR continue
   inline; do not re-run 1.1/1.7.
