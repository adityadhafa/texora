# Texora M1 — Continue (1.2 → 1.4 → 1.6 → converge/finalize)

Resume plan for the remaining M1 work in the EXISTING worktree. Authoritative source: the
verbatim user request ("read docs/PROGRESS.md and continue M1 from there"), `docs/PROGRESS.md`,
`.kiro/specs/texora/tasks.md` (§"M1 — Skeleton"), the four steering files, `docs/LICENSES.md`,
and `docs/m1-verification.md`.

All paths are absolute under the worktree root:
`c:\data\kucing\texora\.worktrees\m1-skeleton`. Do NOT touch the main checkout
`c:\data\kucing\texora`. Do NOT merge into `main`.

## Already DONE and verified (do NOT redo)
1.1 monorepo scaffold · 1.3 engine skeleton (pytest 4/4) · 1.5 PyInstaller freeze (frozen
Windows sidecar at `apps/desktop/src-tauri/binaries/texora-engine-x86_64-pc-windows-msvc.exe`,
gitignored) · 1.7 LICENSES.md seed. WIP `28be390` authored the 1.2 Tauri scaffold but committed
it unverified.

## Host facts VERIFIED during this planning pass (supersede the stale `m1-plan.md`)
The earlier `m1-plan.md`/`context.json` assumed pnpm/rust/py311 were missing. That is NO LONGER
true. Confirmed on this host (Windows + bash), with the PATH export below applied:
- node v24.14.0 · pnpm 9.15.9 · cargo 1.99.1 · rustc host triple `x86_64-pc-windows-msvc`.
- engine venv python = Python 3.11.9 at `engine/.venv/Scripts/python.exe`.
- `apps/desktop/node_modules` already present; frozen sidecar already present.
=> cargo / clippy / `cargo test` / `pnpm tauri build` / pytest ARE all runnable here. The only
genuinely host-limited checks are: the interactive `tauri dev` WINDOW opening (1.2 done-criterion),
the live status badge shown in a running window (1.4), and the real CI "artifact installs and
launches" (1.6). Those are documented as pending manual/CI confirmation — never reported as passed.

### PATH export — prepend before EVERY build/test/git command
```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```
Default cwd for frontend/git = `c:\data\kucing\texora\.worktrees\m1-skeleton`.
cwd for cargo = `c:\data\kucing\texora\.worktrees\m1-skeleton/apps/desktop/src-tauri`.
Automation rule (steering/tech.md): ONE-SHOT commands only — never leave `pnpm tauri dev`,
`pnpm dev`, or `uvicorn --reload` running.

## Known blocker found by inspection (must fix in 1.2)
`apps/desktop/src-tauri/tauri.conf.json` sets `bundle.icon` to four `icons/*` paths, but
`apps/desktop/src-tauri/icons/` does NOT exist. On Windows, `tauri-build` embeds the window icon
into a Windows resource file during `cargo build`; a missing icon path fails the build. So even
`cargo build` (not just bundling) will fail until real square icons exist. Fix by generating icons
with `pnpm --filter desktop tauri icon <source.png>` (produces `32x32.png`, `128x128.png`,
`128x128@2x.png`, `icon.ico`, `icon.icns` under `src-tauri/icons/`) from a simple committed source
PNG, OR by committing a valid square `icon.ico` + PNGs and aligning `bundle.icon` to the exact
files present. The icons MUST be committed (they are build inputs, and `.gitignore` does not
exclude `src-tauri/icons/`). Secondary candidate fix: `App.tsx` returns `JSX.Element` with the new
JSX transform and no React import — if `tsc` strict flags the missing global `JSX` namespace,
switch the return type to `React.JSX.Element` (import `React`) or `ReactElement`. Verify by actually
running the typecheck; only change it if it fails.

---

## Item 1 — Task 1.2: finish + VERIFY the Tauri v2 app, promote WIP to done
`dep: none new` · `done:` (tasks.md 1.2) "`tauri dev` opens a window".

What: make the already-authored scaffold actually build, lint, typecheck, and test clean; fix the
missing-icons blocker and any strict-TS/clippy failures. Do NOT re-architect — the scaffold
(React 18 + TS strict + Vite 7 + Tailwind 3.4 + Tauri 2.12, crate `texora-desktop`, externalBin
`binaries/texora-engine`, dark/light tokens, one vitest test) is already in place and correct in
shape; this item is verification + minimal fixes.

Files to touch (only as needed to make checks pass):
- `apps/desktop/src-tauri/icons/` — NEW: `32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.ico`
  (generated via `pnpm --filter desktop tauri icon`), committed.
- `apps/desktop/src-tauri/tauri.conf.json` — only if the generated icon set differs from the four
  listed paths; keep `bundle.externalBin: ["binaries/texora-engine"]` and `targets: ["msi","nsis"]`.
- `apps/desktop/src/App.tsx` — only if strict `tsc` fails on `JSX.Element`.
- `docs/LICENSES.md` — reconcile ANY dep whose installed version differs from its row (the
  `apps/desktop/package.json` pins `@tauri-apps/api` 2.9.0, `vite` 7.0.0, `tailwindcss` 3.4.17,
  etc. — ensure each has a matching row; add/update rows in THIS change). No new runtime dep is
  expected for 1.2.

Commands (cwd = worktree root unless noted; PATH exported):
```bash
pnpm install
pnpm --filter desktop lint
pnpm --filter desktop test -- --run
pnpm --filter desktop build
# then, cwd = apps/desktop/src-tauri:
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo build
```
Verify / done-mapping:
- lint clean; vitest passes (App renders "Texora" heading + theme toggle test); `pnpm build`
  compiles under strict TS; `cargo fmt --check` clean; `cargo clippy` clean with warnings denied;
  `cargo build` succeeds (proves icons + Tauri config + externalBin wiring + crate compile).
- The done-criterion "`tauri dev` opens a window" is satisfied STRUCTURALLY (successful frontend
  build + Tauri crate build; config, externalBin, and the blank Home screen with dark/light theme
  tokens present and correct). Interactive window-open is left for MANUAL user confirmation — record
  it as pending, do not claim it passed.
Record all command output + outcomes in `docs/m1-verification.md` §1.2. Commit (promote WIP),
e.g. `feat(desktop): verify + finish Tauri v2 skeleton (task 1.2)`. Commit locally; never push.

## Item 2 — Task 1.4: sidecar supervisor + secure IPC + typed client + live status
`dep: 1.2, 1.3` · `done:` (tasks.md 1.4) "UI shows live engine status from `/healthz`".

What (Rust, `apps/desktop/src-tauri`, thin secure client + process manager — NO business logic):
a supervisor that (1) generates a per-session 256-bit bearer token (`rand`), (2) binds
`127.0.0.1:0` to grab a FREE ephemeral port then releases it for the child, (3) spawns the engine —
DEV mode: run the venv module `python -m texora_engine --host 127.0.0.1 --port <p> --token <t>`
(token also via `TEXORA_ENGINE_TOKEN` env to avoid argv leakage); PROD mode: the frozen
`externalBin` sidecar (`texora-engine`, resolved with the `-$TARGET_TRIPLE` suffix) — (4)
health-checks `GET /healthz` until 200, (5) restarts with exponential backoff on crash/failed
health, (6) broadcasts status as `engine://status` Tauri events and exposes a
`#[tauri::command] engine_status()` returning the current typed status. Engine binds loopback only;
bearer token used on non-health routes.

Rust files:
- `apps/desktop/src-tauri/src/supervisor.rs` — NEW: token gen, free-port pick, spawn (dev/prod),
  health-check loop, backoff, status struct + event emit. Pure helpers (`free_loopback_port()`,
  token generator, backoff schedule) are unit-testable without spawning.
- `apps/desktop/src-tauri/src/lib.rs` — register supervisor on setup, manage state, expose
  `engine_status` command, emit `engine://status`.
- `apps/desktop/src-tauri/Cargo.toml` — add pinned deps: `tokio` (rt-multi-thread + process +
  time + macros), `rand` 0.8, and ONE HTTP client for the health check — DECISION: use `ureq` 2.x
  (tiny, blocking, no async TLS stack needed for loopback HTTP) run on a blocking task; remove the
  `reqwest` candidate row from LICENSES.md so exactly one client ships. Add the Tauri shell plugin
  for sidecar spawn: `tauri-plugin-shell` 2.x (Rust) — DECISION: use the official shell plugin's
  sidecar API rather than hand-rolling `std::process` so externalBin resolution + `-$TARGET_TRIPLE`
  suffixing is handled by Tauri.
- `apps/desktop/src-tauri/capabilities/default.json` — add the permissions the command/events and
  `shell:allow-execute`/sidecar scope require (minimal; scope the sidecar to `binaries/texora-engine`).

TypeScript files (the SINGLE typed client is the only place that calls invoke/events/fetch):
- `apps/desktop/src/engineClient.ts` — NEW: exported `EngineStatus` type (e.g.
  `{ state: 'starting'|'healthy'|'unhealthy'|'restarting'|'stopped'; port?: number; detail?: string }`),
  `getEngineStatus()` wrapping `invoke('engine_status')`, and `subscribeEngineStatus(cb)` wrapping
  `listen('engine://status')`. No other component calls `invoke`/`listen`/`fetch`.
- `apps/desktop/src/EngineStatusBadge.tsx` — NEW: live status badge consuming the client; all
  user-facing strings via i18next (`id` default + `en`).
- `apps/desktop/src/App.tsx` — render `<EngineStatusBadge />` on the Home screen.
- i18n: add minimal i18next setup — DECISION: introduce `i18next` + `react-i18next` now (tasks.md
  8.1 formalizes it, but 1.4's badge needs real strings and coding-standards forbids hard-coded UI
  text). Files: `apps/desktop/src/i18n.ts` + `apps/desktop/src/locales/{id,en}.json`, initialized in
  `main.tsx` with `id` default. Add `@tauri-apps/plugin-shell` (JS) to match the Rust plugin.
- `docs/LICENSES.md` — add rows (same change): Rust `tokio`, `rand`, `ureq`, `tauri-plugin-shell`;
  npm `i18next`, `react-i18next`, `@tauri-apps/plugin-shell`. Remove the `reqwest` candidate row.
  Pin exact versions; verify each license against official metadata before writing the row.

Tests:
- Rust: `cargo test` unit tests in `supervisor.rs` — free-port returns a usable loopback port,
  token is 256-bit/non-empty/unique across calls, backoff schedule increases and caps. Do NOT spawn
  a real long-running engine in tests.
- Frontend: `apps/desktop/src/engineClient.test.ts` (mock `@tauri-apps/api` invoke + event) and a
  badge render test driving it through `engine_status`/`engine://status`. Keep the existing App
  tests green.

Commands (PATH exported):
```bash
pnpm --filter desktop lint
pnpm --filter desktop test -- --run
pnpm --filter desktop build
# cwd = apps/desktop/src-tauri:
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build
```
Verify / done-mapping: client + badge unit tests prove the UI consumes live status from the
supervisor (which health-checks `/healthz`); Rust unit tests prove token/port/backoff. The
end-to-end "UI shows live engine status in a running window" is confirmed STRUCTURALLY + by unit
tests; the actual running-window observation is MANUAL — record as pending, do not claim it passed.
Record in `docs/m1-verification.md` §1.4. Commit, e.g.
`feat(desktop): sidecar supervisor + typed engine client + live status badge (task 1.4)`.

## Item 3 — Task 1.6: CI Windows installer
`dep: 1.4, 1.5` · `done:` (tasks.md 1.6) "CI artifact installs and launches".

What: `.github/workflows/ci.yml` (windows-latest, pinned action + tool versions) with jobs:
- `engine-checks`: `actions/checkout@<pin>`, `actions/setup-python@<pin>` Python 3.11.9 → install
  `engine/requirements.txt` + `engine/requirements-dev.txt` → `ruff check .`, `black --check .`
  (line-length 100 to match engine config), `mypy texora_engine`, `pytest -q` (run from `engine/`).
- `frontend-checks`: `actions/checkout@<pin>`, `actions/setup-node@<pin>` Node 24.x,
  `pnpm/action-setup@<pin>` with `version: 9.15.9` → `pnpm install` →
  `pnpm --filter desktop lint`, `pnpm --filter desktop test -- --run`, `pnpm --filter desktop build`.
- `build-installer` (`needs: [engine-checks, frontend-checks]`): setup Python 3.11.9 + Node/pnpm +
  `dtolnay/rust-toolchain@stable` (and `Swatinem/rust-cache@<pin>` if used) → `pnpm install` →
  `python scripts/build_engine.py` (freeze the sidecar into
  `apps/desktop/src-tauri/binaries/texora-engine-x86_64-pc-windows-msvc.exe`) → `pnpm --filter
  desktop tauri build` → `actions/upload-artifact@<pin>` the `.msi`/`.exe` from
  `apps/desktop/src-tauri/target/release/bundle/{msi,nsis}/`.

Pin EVERY action to a fixed major/tag per the versions in PROGRESS.md. Keep YAML valid.

Files: `.github/workflows/ci.yml` (NEW). No new dependency rows (GitHub Actions need no LICENSES row;
note that in findings).

Verify / done-mapping:
- Parse the YAML locally and confirm it is valid, e.g.:
  `pnpm --filter desktop exec node -e "const fs=require('fs');const yaml=require('yaml');yaml.parse(fs.readFileSync('../../.github/workflows/ci.yml','utf8'));console.log('ok')"`
  — or `pnpm dlx js-yaml .github/workflows/ci.yml`. Expected: parses, prints ok.
- Confirm every script/command the workflow references exists in the repo: `scripts/build_engine.py`,
  the engine requirements files, root `pnpm --filter desktop` scripts, the Tauri bundle output path.
- The done-criterion "CI artifact installs and launches" runs ONLY on a real GitHub Windows runner.
  State this limitation EXPLICITLY in `docs/m1-verification.md` §1.6 — do NOT claim it passed.
Record in `docs/m1-verification.md` §1.6. Commit, e.g.
`ci: windows installer build + engine/frontend checks (task 1.6)`.

## Item 4 — Converge + finalize
What: run the full cross-feature verification once more as a whole, fix any seams, then update docs
to final M1 status and have the reviewer sign off.
- Cross-feature build/test (PATH exported): `pnpm install`; `pnpm --filter desktop lint`;
  `pnpm --filter desktop test -- --run`; `pnpm --filter desktop build`; in `apps/desktop/src-tauri`:
  `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo build`, `cargo test`;
  engine (from `engine/`, venv python): `ruff check .`, `black --check . --line-length 100`,
  `mypy texora_engine`, `pytest -q`.
- Update `docs/PROGRESS.md`: mark 1.2/1.4/1.6 DONE with the host-limited caveats noted; tick the
  M1 checkboxes in `.kiro/specs/texora/tasks.md` (1.2, 1.4, 1.6 → `[x]`). Ensure every manifest dep
  has a `docs/LICENSES.md` row (cross-check) and the `reqwest` candidate row is resolved.
- Clean up any temp files (icon source scratch, PyInstaller `.build/`, etc.).
- The reviewer writes `c:\data\kucing\texora\.worktrees\m1-skeleton\.agents\tasks\m1-review.json`
  with `{"verdict": "APPROVED"}` once the whole skeleton is coherent and all non-host-limited checks
  are green; otherwise `{"verdict": "CHANGES_REQUESTED", ...}`.

## Honesty rule (project principle)
Never claim a verification passed that was not run. The three host-limited checks (interactive
`tauri dev` window, live badge in a running window, real CI install+launch) are documented as
pending manual/CI confirmation, NOT reported as done. No placeholder/stub/fake code in production
paths — the engine is a real FastAPI server; the supervisor really spawns and health-checks it.

## New dependencies that MUST get a `docs/LICENSES.md` row (in the same change)
- 1.2: none expected (reconcile existing rows to installed versions).
- 1.4: Rust `tokio`, `rand`, `ureq`, `tauri-plugin-shell`; npm `i18next`, `react-i18next`,
  `@tauri-apps/plugin-shell`. Remove the `reqwest` candidate row (ureq is the chosen client).
- 1.6: none (GitHub Actions need no row).
