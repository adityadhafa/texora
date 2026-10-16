# Texora M1 — Runnable Skeleton: Implementation Plan

Scope: tasks 1.1–1.7 from `.kiro/specs/texora/tasks.md`. Build order is strict and dependency-driven.
Every item leaves the repo in a buildable/testable state. All paths are absolute under the worktree
root `c:\data\kucing\texora\.worktrees\m1-skeleton`.

Source of truth: this worktree's `.kiro/specs/texora/{requirements,design,tasks}.md` and
`.kiro/steering/{product,tech,structure,coding-standards}.md` (all present in the worktree; no
fallback to the main repo was needed).

> NOTE: This plan has also been decomposed into FEAT artifacts under
> `c:\data\kucing\texora\.worktrees\m1-skeleton\.agents\tasks\task-m1-skeleton\` and the workflow
> tail was replaced with one coder step per FEAT plus a convergence loop. This markdown file remains
> the human-readable fallback and the authoritative per-task detail; the FEAT files reference it.

---

## Host environment (verified) and what it means

Checked on this Windows + bash host:

- `node` v24.14.0 — OK for Vite 7 / React 18.
- `pnpm` — NOT installed. The coder MUST enable it via Corepack (`corepack enable pnpm`) or
  `npm i -g pnpm@9`. Pin pnpm via `packageManager` in root `package.json`.
- `python` — only Python **3.14** is on PATH. The engine targets **3.11** (steering/tech.md). The
  coder MUST create a 3.11 virtualenv (`py -3.11 -m venv` if the launcher has 3.11, else install
  Python 3.11 or use `uv python install 3.11`). If 3.11 cannot be provisioned on this host, FLAG it:
  run pytest on the available interpreter to prove the code works, and mark the "3.11-frozen binary"
  checks as host-limited rather than faking them.
- `rustc` / `cargo` — NOT installed. Tauri (1.2, 1.4) and PyInstaller→Tauri bundle (1.5, 1.6)
  Rust/`cargo build`/`cargo clippy`/`tauri build` checks are **UNVERIFIABLE on this host** unless the
  coder installs the Rust toolchain. If Rust cannot be installed, the coder MUST still author all
  Rust/Tauri source and config, verify everything that does not need cargo, and explicitly flag the
  cargo/tauri checks as host-limited (NOT faked).
- `cargo tauri` CLI — NOT installed; the Tauri CLI is consumed via the pnpm dev dependency
  `@tauri-apps/cli`, invoked as `pnpm tauri ...`.

Automation rule (steering/tech.md): one-shot commands only. NEVER leave `pnpm tauri dev`,
`pnpm dev`, or `uvicorn --reload` running. For 1.2's "window opens" check, build only
(`pnpm tauri build` or compile the frontend); do not launch a dev window in automation.

## Pinned versions (verified against current official sources)

Pin exact versions; the lockfiles (`pnpm-lock.yaml`, `Cargo.lock`, `requirements.txt`/`uv.lock`) are
the authoritative pins. Versions below were confirmed as current/real releases via official sources
(PyPI JSON, tauri.app releases) during planning; if a listed patch is unavailable at install time,
the coder picks the nearest existing patch in the same minor line and records the actual pin in
`docs/LICENSES.md`.

Frontend / shell (apps/desktop):
- Tauri: `tauri` + `tauri-build` `2.12.x` (Rust), `@tauri-apps/cli` `2.12.x`, `@tauri-apps/api`
  `2.x` — Tauri 2.12.0 confirmed on tauri.app/release. Pin to `2.12.0` (or latest 2.12 patch).
- React `18.3.1` + `react-dom` `18.3.1`; `@types/react` `18.3.x`, `@types/react-dom` `18.3.x`.
- TypeScript `5.6.x` (strict).
- Vite `7.x` (needs Node ≥20.19/22.12; Node 24 OK) + `@vitejs/plugin-react` `4.x`.
- Tailwind CSS `3.4.x` (stable, well-documented JIT). (v4 exists but 3.4 is the lower-risk pin for a
  skeleton; coder may use v4 only if it confirms the official v4 Vite setup and records it.)
- vitest `2.x` + `@testing-library/react` `16.x` + `jsdom`.
- ESLint `9.x` (flat config) + `typescript-eslint` `8.x` + Prettier `3.x`.
- State/data libs are NOT added in M1 (no Zustand/TanStack yet) — skeleton only. The typed engine
  client is hand-written over `@tauri-apps/api` invoke/event.

Engine (engine/):
- Python `3.11` (target runtime).
- fastapi `0.11x–0.143.x` — pin to a current release (FastAPI 0.143.2 observed on PyPI). Pin exact,
  e.g. `fastapi==0.143.2` (or nearest available).
- uvicorn `0.3x.x` (standard extra): `uvicorn[standard]==<current>`.
- pydantic `2.13.x` + pydantic-settings `2.x` (observed pydantic 2.13.x on PyPI).
- httpx `0.27.x` (for pytest TestClient / async client) — dev dep.
- pytest `8.x`, pytest-asyncio `0.24.x` — dev deps.
- ruff `0.6.x+`, black `24.x+`, mypy `1.11.x+` — dev deps.
- PyInstaller `6.x` (6.19/6.20/6.21 observed) + `pyinstaller-hooks-contrib` kept in sync — build dep.

Record every one of these in `docs/LICENSES.md` (task 1.7) with license + personal-use/redistribute
verdict in the SAME change that introduces the dependency.

---

## Task 1.1 — Monorepo scaffold

**What:** Create the monorepo skeleton exactly per `steering/structure.md`, with pnpm workspace at
root and base tooling. Empty-but-present stage folders under `engine/texora_engine/` so later
milestones drop in without restructuring. No app/engine code yet beyond directory placeholders.

**Files/dirs to create (absolute):**
- `c:\data\kucing\texora\.worktrees\m1-skeleton\package.json` — root, `"private": true`,
  `"packageManager": "pnpm@9.x.x"`, workspace scripts (`lint`, `test`, `build` delegating to
  `apps/desktop`).
- `c:\data\kucing\texora\.worktrees\m1-skeleton\pnpm-workspace.yaml` — packages: `apps/*`.
- `c:\data\kucing\texora\.worktrees\m1-skeleton\.editorconfig`
- `c:\data\kucing\texora\.worktrees\m1-skeleton\.gitignore` — node_modules, dist, target,
  `__pycache__`, `.venv`, `*.spec` build dirs, `apps/desktop/src-tauri/binaries/*` (frozen sidecars),
  `.agents/` is already outside the worktree so no rule needed, but ignore local logs.
- `c:\data\kucing\texora\.worktrees\m1-skeleton\LICENSE` — project license file (MIT or Apache-2.0;
  choose MIT to match "permissive-first" and record the choice in README).
- `c:\data\kucing\texora\.worktrees\m1-skeleton\README.md` — stub: name, one-line description, M1
  status, build-from-source placeholder pointing at later milestones.
- `c:\data\kucing\texora\.worktrees\m1-skeleton\pipeline.yaml` — placeholder with commented stage
  keys (ingest/layout/recognize/ensemble/export) and `# defaults set by M7 benchmarks`.
- Directory tree (create with a `.gitkeep` where otherwise empty):
  `apps\desktop\`, `engine\texora_engine\api\`, `engine\texora_engine\ingest\`,
  `engine\texora_engine\layout\`, `engine\texora_engine\recognizers\`,
  `engine\texora_engine\ensemble\`, `engine\texora_engine\export\`, `engine\texora_engine\jobs\`,
  `engine\texora_engine\models\`, `engine\texora_engine\db\`, `engine\tests\`,
  `benchmarks\`, `docs\`, `scripts\`.

**Verify:**
- `pnpm install` at root succeeds (workspace resolves; no package errors). Expected: lockfile
  written, exit 0.
- `node -e "require('fs').accessSync('pnpm-workspace.yaml')"` or a `ls`-equivalent confirms the tree
  — but the real done-check is deferred to after 1.2/1.3 add buildable code.
- **done (tasks.md 1.1):** "repo builds frontend + engine lint with no errors" — satisfied once 1.2
  (frontend builds) and 1.3 (engine ruff/mypy clean) exist. At 1.1 completion, verify the tree
  matches `structure.md` and `pnpm install` succeeds.

---

## Task 1.7 — docs/LICENSES.md bootstrap (done early, kept updated by every later task)

Placed right after 1.1 because `coding-standards.md` requires a license row in the SAME change that
adds a dependency. Seed it now; each later task appends its deps.

**What:** Create `docs/LICENSES.md` with a table listing every pinned dependency added in M1, its
license, and a personal-use-vs-redistribute verdict. Document the policy risks: PyMuPDF is AGPL and
is NOT a default (pypdfium2 is the chosen renderer, added in M3 not M1); Surya is GPL code +
non-commercial RAIL weights and is opt-in only. Explicitly state that NO Surya/PyMuPDF dependency is
added in M1.

**Files:**
- `c:\data\kucing\texora\.worktrees\m1-skeleton\docs\LICENSES.md`

**Table columns:** Dependency | Version | Ecosystem | License | Personal use | Redistribute | Notes.
Rows for every M1 dep (FastAPI MIT, uvicorn BSD-3, pydantic MIT, httpx BSD-3, pytest MIT, ruff MIT,
black MIT, mypy MIT, PyInstaller GPL-2.0-with-bootloader-exception — note the exception lets you ship
frozen apps freely, Tauri Apache-2.0/MIT, React MIT, Vite MIT, Tailwind MIT, TypeScript Apache-2.0,
Vitest MIT, ESLint MIT, Prettier MIT). Verify each license against the package's official metadata
before writing the row; do not guess.

**Policy section:** a short "Deferred / opt-in only" subsection naming PyMuPDF (AGPL → opt-in local
only, never default) and Surya (GPL + non-commercial weights → opt-in local only, not
redistributable), with a line stating neither is a dependency in M1.

**Verify:**
- `node`/grep check that every dependency named in `package.json`, `engine/requirements.txt`, and
  `apps/desktop/src-tauri/Cargo.toml` has a matching row in `docs/LICENSES.md` (the coder writes a
  tiny check script in `scripts/` or does it manually and records the result).
- **done (tasks.md 1.7):** file lists each dependency + license + verdict. Confirmed by the row-vs-
  manifest cross-check passing.

---

## Task 1.3 — Python engine skeleton (FastAPI + auth + logging + tests)

**What:** Build a real FastAPI engine package `engine/texora_engine` with: Pydantic v2 settings
(`pydantic-settings`), a `GET /healthz` returning 200 (no auth), a bearer-token auth dependency/
middleware that returns 401 for missing/wrong token on every non-health route, loopback bind to an
arg-provided port, and structured rotating-file logging. Provide a CLI entrypoint
(`python -m texora_engine` / `texora_engine.__main__`) accepting `--host 127.0.0.1 --port <p>
--token <t>` (token also readable from env `TEXORA_ENGINE_TOKEN`). Add a trivial protected route
(e.g. `GET /engine/info`) solely so auth has something to guard. NO OCR logic.

**Files/dirs:**
- `engine\pyproject.toml` — project metadata, Python 3.11 constraint, ruff/black/mypy config,
  pytest config; declare runtime deps and `[project.optional-dependencies] dev`.
- `engine\requirements.txt` (or `uv.lock`) — pinned runtime deps.
- `engine\requirements-dev.txt` — pinned dev deps (pytest, ruff, black, mypy, httpx, pytest-asyncio).
- `engine\texora_engine\__init__.py`
- `engine\texora_engine\__main__.py` — argparse CLI → uvicorn.run bound to 127.0.0.1:<port>.
- `engine\texora_engine\settings.py` — `Settings(BaseSettings)` (host, port, token, log dir/level).
- `engine\texora_engine\logging_config.py` — `RotatingFileHandler` + console; structured formatter;
  returns configured logger; no bare prints.
- `engine\texora_engine\security.py` — `require_token` FastAPI dependency: reads
  `Authorization: Bearer <t>`, 401 on missing/mismatch (constant-time compare).
- `engine\texora_engine\app.py` — `create_app(settings) -> FastAPI`; mounts `/healthz` (open) and an
  auth-protected router; wires logging on startup.
- `engine\texora_engine\api\__init__.py`, `engine\texora_engine\api\routes.py` — health + protected
  `info` routes using the `require_token` dependency.
- `engine\tests\__init__.py`, `engine\tests\conftest.py` — TestClient fixture with a known token.
- `engine\tests\test_health_and_auth.py` — tests: `/healthz` → 200; protected route without token →
  401; with correct token → 200; with wrong token → 401.

**Verify (run inside the 3.11 venv at `engine/`):**
- `ruff check .` → no errors.
- `black --check .` → no reformat needed.
- `mypy texora_engine` → no type errors.
- `pytest -q` → all tests pass (health 200, 401 without/with-wrong token, 200 with token).
- **done (tasks.md 1.3):** pytest hits `/healthz` (200) and rejects missing token (401). ✔ covered.

---

## Task 1.5 — PyInstaller freeze

**What:** A build script in `scripts/` that freezes the engine into a single self-contained binary
and places it where Tauri's `externalBin` expects it, with the `-$TARGET_TRIPLE` suffix (plus `.exe`
on Windows). The frozen binary runs standalone and serves `/healthz`.

Key naming facts (verified via tauri.app sidecar docs): the sidecar binary must be named
`<name>-<TARGET_TRIPLE>` where the triple is the `host:` value from `rustc -Vv`
(e.g. `x86_64-pc-windows-msvc`), and the file goes under `apps/desktop/src-tauri/binaries/`. The
sidecar name MUST differ from the Cargo package name (Tauri rejects a collision). Use base name
`texora-engine` (Cargo crate will be `texora` or `texora-desktop`, kept distinct).

**Files:**
- `scripts\build-engine.(sh|ps1)` and a cross-platform `scripts\build_engine.py` driver — resolves
  the target triple from `rustc -Vv` (fallback: a `--triple` arg so it works without a built app),
  runs PyInstaller against `engine/texora_engine/__main__.py` with `--onefile --name texora-engine`,
  then copies/renames the output to
  `apps\desktop\src-tauri\binaries\texora-engine-<TRIPLE>[.exe]`.
- `engine\texora-engine.spec` (optional) — PyInstaller spec if hidden imports (uvicorn workers,
  pydantic) need declaring. Add `--collect-submodules`/hidden-imports for `uvicorn` as needed.
- Update `engine\requirements-dev.txt` / build extras to include `pyinstaller` + hooks-contrib.
- Append PyInstaller rows to `docs\LICENSES.md`.

**Verify:**
- Run the build script → produces `apps/desktop/src-tauri/binaries/texora-engine-<triple>[.exe]`.
- Launch the frozen binary one-shot: `texora-engine-<triple> --host 127.0.0.1 --port <p>
  --token <t>` in the background briefly, `curl http://127.0.0.1:<p>/healthz` → 200, then stop it.
  (This is a one-shot smoke, not a left-running server.)
- **done (tasks.md 1.5):** frozen binary runs standalone and serves `/healthz`. ✔
- **HOST LIMITATION:** requires a working PyInstaller against **Python 3.11**. If only 3.14 is
  available, a 3.14-frozen binary still proves the mechanism but is not the shipping runtime — FLAG
  this. If `rustc` is absent, pass `--triple x86_64-pc-windows-msvc` explicitly and note the triple
  was hard-provided rather than probed.

---

## Task 1.2 — Tauri v2 app (React + TS strict + Vite + Tailwind)

**What:** Scaffold the Tauri 2.12.x desktop app in `apps/desktop` with React 18 + TypeScript
(strict) + Vite + Tailwind. A blank Home screen with dark/light theme tokens (CSS variables +
`prefers-color-scheme` or a manual toggle). No ML/business logic in the UI.

**Files/dirs:**
- `apps\desktop\package.json` — deps/devDeps pinned (React, Vite, Tailwind, TS, vitest, eslint,
  prettier, `@tauri-apps/cli`, `@tauri-apps/api`); scripts: `dev`, `build`, `lint`, `test`,
  `tauri`.
- `apps\desktop\tsconfig.json` + `tsconfig.node.json` — `"strict": true`, no implicit any.
- `apps\desktop\vite.config.ts` — React plugin; Tauri-friendly (fixed port, `clearScreen:false`).
- `apps\desktop\index.html`, `apps\desktop\src\main.tsx`, `apps\desktop\src\App.tsx` — blank Home.
- `apps\desktop\src\styles\theme.css` (or Tailwind config tokens) — dark/light tokens.
- `apps\desktop\tailwind.config.(js|ts)` + `postcss.config.js` + `apps\desktop\src\index.css`
  (`@tailwind` directives). Enable `darkMode: 'class'`.
- `apps\desktop\.eslintrc`/`eslint.config.js` (flat) + `.prettierrc`.
- `apps\desktop\src-tauri\Cargo.toml` — crate name `texora-desktop` (distinct from sidecar
  `texora-engine`); `tauri`/`tauri-build` `2.12`.
- `apps\desktop\src-tauri\tauri.conf.json` — product name, window, `bundle.externalBin:
  ["binaries/texora-engine"]`, bundle targets (`msi`,`nsis` on Windows).
- `apps\desktop\src-tauri\build.rs`, `apps\desktop\src-tauri\src\main.rs`,
  `apps\desktop\src-tauri\src\lib.rs` — minimal Tauri entrypoint (supervisor added in 1.4).
- `apps\desktop\src-tauri\binaries\.gitkeep` — where the frozen sidecar lands (gitignored contents).
- One trivial vitest test, e.g. `apps\desktop\src\App.test.tsx`, so `pnpm test -- --run` has a test.
- Append all these deps to `docs\LICENSES.md`.

**Verify:**
- `pnpm install` → ok.
- `pnpm --filter desktop lint` (eslint) → clean.
- `pnpm --filter desktop test -- --run` (vitest) → passes.
- `pnpm --filter desktop build` (vite build / `tsc`) → frontend compiles with strict TS.
- `cargo fmt --check` + `cargo clippy` in `src-tauri` → clean (REQUIRES Rust toolchain).
- **done (tasks.md 1.2):** `tauri dev` opens a window — in automation DO NOT run the dev window;
  instead verify `pnpm tauri build` (or at minimum `cargo build` in `src-tauri`) succeeds, and note
  the window-open check as a manual/host step. FLAG if Rust/tauri CLI absent.

---

## Task 1.4 — Sidecar supervisor + secure IPC + typed TS client + live status

**What:** Rust supervisor that (1) generates a 256-bit random token, (2) finds a free loopback port,
(3) spawns the engine — in dev runs Python directly, in prod uses the `externalBin` frozen sidecar —
(4) health-checks `/healthz`, (5) restarts with exponential backoff on crash. Expose Tauri commands/
events so a single typed TS engine client in `apps/desktop/src` can query engine status; the Home
screen shows live engine status polled from `/healthz`. Components never call `fetch`/`invoke`
directly — only through the typed client.

**Files:**
- `apps\desktop\src-tauri\src\supervisor.rs` — token gen (`rand`), free-port pick
  (bind `127.0.0.1:0`), spawn (dev: `python -m texora_engine ...`; prod: resolve sidecar via Tauri
  shell/`tauri::process::Command`), health-check loop, backoff restart, status broadcast via Tauri
  events.
- `apps\desktop\src-tauri\src\lib.rs`/`main.rs` — register supervisor, expose
  `#[tauri::command]` e.g. `engine_status()` and emit `engine://status` events.
- `apps\desktop\src-tauri\Cargo.toml` — add `rand`, `reqwest` (or `tauri-plugin-http`)/`ureq`,
  `tokio`, `serde`; pin versions. Add rows to LICENSES.md.
- `apps\desktop\src-tauri\capabilities\*.json` — Tauri v2 permissions for the commands/events used.
- `apps\desktop\src\lib\engineClient.ts` — the SINGLE typed client: wraps `invoke('engine_status')`
  and subscribes to `engine://status` events; exports typed `EngineStatus`. No bare invoke elsewhere.
- `apps\desktop\src\App.tsx` (+ a small `EngineStatusBadge.tsx`) — render live status from the client.
- Tests: `apps\desktop\src\lib\engineClient.test.ts` (mock `@tauri-apps/api`), Rust unit tests in
  `supervisor.rs` for free-port and backoff logic.

**Verify:**
- `pnpm --filter desktop lint` + `pnpm --filter desktop test -- --run` → pass (client test green).
- `cargo fmt --check` + `cargo clippy` + `cargo test` in `src-tauri` → clean/pass (REQUIRES Rust).
- Integration smoke (host-permitting): start engine one-shot on a known port, confirm the supervisor
  health-check path reports healthy; or a Rust unit test that hits a stub 200 endpoint.
- **done (tasks.md 1.4):** UI shows live engine status from `/healthz`. Verified by the client test
  + (manual/host) a built app showing the badge. FLAG the live-window check if Rust absent.

---

## Task 1.6 — CI: Windows installer + checks

**What:** GitHub Actions workflow(s) under `.github/workflows/` that, on `windows-latest`: set up
Node+pnpm, Python 3.11, and Rust; run engine lint+pytest and frontend lint+vitest as checks; build
the PyInstaller engine freeze; build the Tauri `.msi`/`.exe`; upload the installer as an artifact.

**Files:**
- `c:\data\kucing\texora\.worktrees\m1-skeleton\.github\workflows\ci.yml` — jobs:
  - `engine-checks` (windows-latest): `actions/setup-python@v5` py3.11 → install dev deps →
    `ruff check` + `black --check` + `mypy` + `pytest -q`.
  - `frontend-checks` (windows-latest): setup-node@v4 + corepack pnpm → `pnpm install` →
    `pnpm --filter desktop lint` + `pnpm --filter desktop test -- --run`.
  - `build-installer` (windows-latest, needs the two check jobs): setup Python 3.11 + Node/pnpm +
    `dtolnay/rust-toolchain@stable` → run `scripts/build-engine` freeze → `pnpm --filter desktop
    tauri build` → `actions/upload-artifact@v4` the `.msi`/`.exe` from
    `apps/desktop/src-tauri/target/release/bundle/`.
- Pin action versions (e.g. `@v5`, `@v4`) and tool versions in the workflow.
- Add any CI-only tool rows to `docs/LICENSES.md` if applicable (GH Actions themselves need no row).

**Verify:**
- Lint the workflow YAML locally (`node`-based `yaml` parse, or `pnpm dlx @action-validator` if
  chosen) → valid.
- **done (tasks.md 1.6):** CI artifact installs and launches — this is **UNVERIFIABLE on this local
  host** (requires GitHub-hosted Windows runners actually executing the workflow). The coder MUST
  author the workflow correctly, validate YAML syntax locally, and FLAG that the end-to-end
  "artifact installs and launches" check can only be confirmed by a real CI run / manual install —
  do not fake a green CI.

---

## Final verification checklist (tasks.md `done:` → concrete command → expected)

Run from the worktree root unless noted. Engine commands run in the Python 3.11 venv at `engine/`.

| Task | done-check | Command | Expected | Host-verifiable? |
|---|---|---|---|---|
| 1.1 | repo builds frontend + engine lint, no errors | `pnpm install` then 1.2/1.3 checks below | exit 0; tree matches structure.md | Yes |
| 1.7 | file lists each dep + license + verdict | cross-check script: every manifest dep has a row in `docs/LICENSES.md` | all deps matched | Yes |
| 1.3 | pytest hits `/healthz` 200, rejects missing token 401 | `cd engine && ruff check . && black --check . && mypy texora_engine && pytest -q` | all green; auth tests assert 200/401 | Yes (needs py3.11 venv) |
| 1.5 | frozen binary runs standalone, serves `/healthz` | run `scripts/build-engine` → launch binary one-shot → `curl .../healthz` | binary exists `texora-engine-<triple>[.exe]`; curl 200 | Partial — needs PyInstaller on py3.11; FLAG if only 3.14 |
| 1.2 | `tauri dev` opens a window | `pnpm --filter desktop lint && pnpm --filter desktop test -- --run && pnpm --filter desktop build`; then `pnpm --filter desktop tauri build` | frontend compiles; bundle builds | Partial — build yes if Rust present; actual window = manual. FLAG if no Rust |
| 1.4 | UI shows live engine status from `/healthz` | `pnpm --filter desktop test -- --run` (client test); `cargo test` in src-tauri | client+supervisor tests pass | Partial — Rust tests need toolchain; live window manual. FLAG if no Rust |
| 1.6 | CI artifact installs and launches | local YAML validation; real check = CI run | YAML valid locally | NO (local) — real check needs CI/manual install. FLAG, do not fake |

### Explicitly host-limited / flag-don't-fake checks
1. Any `cargo`/`clippy`/`cargo test`/`tauri build` step — `rustc`/`cargo` are NOT installed here.
2. The actual Tauri window opening (1.2) and the live status badge end-to-end (1.4) — need a built,
   launched app (manual).
3. PyInstaller freeze on Python **3.11** (1.5) — only 3.14 is on PATH; provision 3.11 or flag.
4. The full CI "artifact installs and launches" (1.6) — requires GitHub runners / a manual install.

The coder MUST surface each of these as a clearly labelled limitation in its findings and MUST NOT
report a faked success for any of them. Everything that CAN be verified on this host (pnpm install,
frontend lint/test/build, engine ruff/black/mypy/pytest, YAML validity, LICENSES cross-check) MUST
actually be run and shown green before the task is marked done.

## Assumptions made (gaps filled, per planner rules)
- Project license = **MIT** (permissive-first, matches steering). Recorded in README + LICENSE.
- Tailwind pinned at **3.4.x** for lower skeleton risk; v4 allowed only if coder confirms official v4
  Vite integration and records it.
- No state/data libraries (Zustand/TanStack) added in M1 — skeleton stays minimal; they arrive when
  first needed (M2+).
- Cargo crate `texora-desktop`, sidecar base name `texora-engine` — deliberately distinct to avoid
  Tauri's "sidecar name == package name" rejection.
- Dev-mode engine spawn runs `python -m texora_engine`; prod uses the frozen `externalBin`. Both
  paths are real (no mocks); the engine is a real FastAPI server throughout.
