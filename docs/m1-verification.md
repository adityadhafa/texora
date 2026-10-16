# M1 — Verification Log

Real command output captured while implementing M1. Each section is appended as its task
completes; earlier sections are not overwritten.

## Task 1.3 — Python engine skeleton (FastAPI + auth + logging + tests)

Environment: Windows + bash. Python **3.11.9** venv at
`c:\data\kucing\texora\.worktrees\m1-skeleton\engine\.venv`. Dev deps installed from
`engine/requirements-dev.txt` (exact pins below).

Installed versions (match `docs/LICENSES.md` rows exactly):

```
black             24.10.0
fastapi           0.143.2
httpx             0.28.1
mypy              1.11.2
pydantic          2.14.1
pydantic-settings 2.16.0
pytest            8.3.3
pytest-asyncio    0.24.0
ruff              0.6.9
uvicorn           0.54.0
```

Commands run from `c:\data\kucing\texora\.worktrees\m1-skeleton\engine` using
`.venv\Scripts\python.exe -m <tool>`:

```
### ruff check .
All checks passed!

### black --check .
All done! ✨ 🍰 ✨
11 files would be left unchanged.

### mypy texora_engine
Success: no issues found in 8 source files

### pytest -q
....                                                                    [100%]
```

`pytest` reports 4 passed. The 4 tests in `tests/test_health_and_auth.py` assert:

- `GET /healthz` → 200, body `{"status": "ok"}` (open, no auth).
- `GET /engine/info` with no `Authorization` header → 401.
- `GET /engine/info` with a wrong bearer token → 401.
- `GET /engine/info` with the correct bearer token → 200.

The only pytest warning is a third-party `StarletteDeprecationWarning` about httpx in the
TestClient (not Texora code); no project warnings.

Notes:
- Auth uses `secrets.compare_digest` (constant-time) in `texora_engine/security.py`; the
  expected token lives on `app.state.engine_token`, set by `create_app`.
- The engine binds `127.0.0.1` only; host/port/token come from CLI args (`--host/--port/--token`)
  with the token also readable from `TEXORA_ENGINE_TOKEN`. No server was left running (no
  `--reload`; uvicorn is invoked one-shot only from the CLI, not during verification).
- Logging is a shared rotating-file logger (`logging_config.py`); no bare `print` in library code.
- Scope: Task 1.3 only. The PyInstaller freeze (Task 1.5) is not part of this step.

## Task 1.5 — PyInstaller freeze of the engine sidecar

Environment: Windows + bash. Freeze performed with the engine's **Python 3.11.9** venv at
`c:\data\kucing\texora\.worktrees\m1-skeleton\engine\.venv` (NOT the system 3.14). Build /
packaging deps installed from `engine/requirements-dev.txt` (exact pins):

```
altgraph==0.17.5
pefile==2024.8.26
pyinstaller==6.22.3
pyinstaller-hooks-contrib==2026.8
```

Target triple resolved from `rustc -Vv`:

```
### rustc -Vv | grep host
host: x86_64-pc-windows-msvc
```

### scripts/build-engine.sh (PyInstaller --onefile)

Driver: `scripts/build_engine.py` (wrappers `scripts/build-engine.sh` / `.ps1`). It runs
PyInstaller `--onefile --name texora-engine` against `engine/texora_engine/__main__.py` with
`--collect-submodules` for uvicorn/pydantic/pydantic_settings plus explicit uvicorn
loop/protocol/lifespan hidden imports, then copies the result to the Tauri `externalBin`
location with the `-<TARGET_TRIPLE>` suffix.

```
### bash scripts/build-engine.sh  (tail)
58446 INFO: Building EXE from EXE-00.toc completed successfully.
58452 INFO: Build complete! The results are available in: ...\engine\.build\dist
[build_engine] python = ...\engine\.venv\Scripts\python.exe
[build_engine] triple = x86_64-pc-windows-msvc
[build_engine] frozen binary: ...\engine\.build\dist\texora-engine.exe
[build_engine] sidecar placed: ...\apps\desktop\src-tauri\binaries\texora-engine-x86_64-pc-windows-msvc.exe
```

Produced sidecar (gitignored; NOT committed):

```
### ls -la apps/desktop/src-tauri/binaries/
-rwxr-xr-x 14945013  texora-engine-x86_64-pc-windows-msvc.exe
```

The sidecar base name `texora-engine` is deliberately distinct from the Cargo crate
`texora-desktop`, so Tauri will not reject a sidecar/package name collision.

### One-shot smoke: launch frozen binary, curl /healthz, stop

`scripts/smoke_sidecar.py` launches the frozen binary on a free loopback port with a session
token, polls `/healthz`, prints the result, then ALWAYS tears down the whole process tree
(`taskkill /F /T` on Windows) so no server is left running.

```
### engine/.venv/Scripts/python.exe scripts/smoke_sidecar.py
SMOKE: launching texora-engine-x86_64-pc-windows-msvc.exe on 127.0.0.1:<free-port>
SMOKE: /healthz status = 200
SMOKE: /healthz body   = {"status":"ok"}
SMOKE PASS: frozen sidecar served /healthz with 200.

### tasklist //FI "IMAGENAME eq texora-engine-x86_64-pc-windows-msvc.exe"
INFO: No tasks are running which match the specified criteria.
```

`done` (tasks.md 1.5): the frozen binary runs standalone and serves `/healthz` → confirmed
(HTTP 200, body `{"status":"ok"}`). No PyInstaller host limitation hit: the freeze used real
Python **3.11.9**, which is the shipping runtime, so the result is representative (NOT faked,
NOT a 3.14 fallback).

Lint/type/format on the new build scripts (line-length 100, matching the engine config):

```
### ruff check scripts/build_engine.py scripts/smoke_sidecar.py  →  All checks passed!
### black --check --line-length 100 ...                          →  2 files unchanged
### mypy --ignore-missing-imports ...                            →  Success: no issues
```

Notes:
- `apps/desktop/src-tauri/binaries/*` stays gitignored except `.gitkeep`; the 14.9 MB frozen
  binary is NOT committed (regenerate with `scripts/build-engine.sh`).
- PyInstaller is GPL-2.0-with-bootloader-exception (build tool only; the exception permits
  shipping the frozen app under any license). Rows for `pyinstaller` 6.22.3 and
  `pyinstaller-hooks-contrib` 2026.8 are present in `docs/LICENSES.md`.

## Task 1.2 — Tauri v2 desktop app (verify + finish the WIP scaffold)

Environment: Windows + bash, PATH export applied before every command. The WIP scaffold
(commit `28be390`) was authored but committed **unverified**; this section records the real
verification and the minimal fixes required to make the checks pass.

### Frontend — PASS (lint + test + strict-TS build all green)

```
### pnpm install
Scope: all 2 workspace projects
Done in <6s using pnpm v9.15.9

### pnpm --filter desktop lint        (eslint .)
(no output, exit 0 — clean)

### pnpm --filter desktop test -- --run
 RUN  v3.2.7
 ✓ src/App.test.tsx (2 tests)
 Test Files  1 passed (1)
      Tests  2 passed (2)

### pnpm --filter desktop build       (tsc -p tsconfig.json && tsc -p tsconfig.node.json && vite build)
vite v7.0.0 building for production...
✓ 28 modules transformed.
dist/index.html                   0.42 kB
dist/assets/index-ChY-tLwj.css    7.09 kB
dist/assets/index-EK7pJJeu.js   144.91 kB
✓ built in ~2.4s
```

The two vitest cases assert: `App` renders the `Texora` heading, and the theme toggle flips the
`dark` class on the document root.

Minimal fixes applied to make the above pass (the WIP had never been built):

1. **vitest 2.1.8 → 3.2.7** (`apps/desktop/package.json`). Root cause: `vite.config.ts` carries a
   vitest `test` block, but vitest 2.x depends on `vite ^5` and installs a second `vite@5.4.21`
   alongside the project's pinned `vite@7.0.0`. The `declare module 'vite'` augmentation that adds
   `test` landed on vite 5's `UserConfig`, so `tsc -p tsconfig.node.json` rejected `test` as an
   unknown property on vite 7's config (`TS2769`). vitest 3.2.x lists `vite ^5 || ^6 || ^7` as a
   dependency and reuses the project's vite 7, resolving the type mismatch. vitest 3.2.7 is MIT and
   the `test` config shape we use (`globals`, `environment: 'jsdom'`, `include`) is unchanged v2→v3.
   Verified against vitest docs (vite is now a peer/compatible dependency). Content was rephrased
   for compliance with licensing restrictions.
2. **CSS `@import` ordering** (`apps/desktop/src/index.css`). `@import './styles/theme.css'` sat
   after the `@tailwind` directives; CSS requires `@import` to precede other statements, which
   emitted a PostCSS warning during `vite build`. Moved the import to the top of the file. Behavior
   is identical (theme tokens still load before `body` uses them) and the warning is gone.

`App.tsx` returning `JSX.Element` was checked and did NOT fail strict `tsc` (the `react-jsx`
transform + `@types/react` provide the global `JSX` namespace), so it was left unchanged per plan.

### Icons blocker — FIXED

`apps/desktop/src-tauri/icons/` did not exist, but `tauri.conf.json` `bundle.icon` references four
files there; on Windows `tauri-build` embeds the window icon during `cargo build`, so the missing
directory is a build blocker. Generated a committed square icon set from a stdlib-generated source
PNG (no Pillow on host; a tiny `zlib`/`struct` PNG writer produced a 1024×1024 source, then
`pnpm --filter desktop tauri icon <source.png>`), then trimmed the output to the desktop-relevant
files (removed the `android/`, `ios/`, and Windows-Store `Square*`/`StoreLogo` variants that nothing
references and that the `msi`/`nsis` targets do not need). Committed icon set:

```
### ls apps/desktop/src-tauri/icons/
32x32.png  64x64.png  128x128.png  128x128@2x.png  icon.ico  icon.icns  icon.png
```

All four `bundle.icon` paths (`32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.ico`) are present,
so `tauri.conf.json` needed no change. The source PNG was written to a temp path and deleted; the
scratch generator was removed.

### Rust crate version pins — FIXED (resolution verified)

The scaffold's `Cargo.toml` pinned floating `tauri = "2.12"` / `tauri-build = "2.12"`. After a
`crates.io` index refresh, `cargo generate-lockfile` resolves the latest stable 2.x: **tauri 2.12.4**
and **tauri-build 2.7.3**. Pinned those exact versions and generated `Cargo.lock` (407 packages
locked, resolution clean). `docs/LICENSES.md` rows updated to the exact versions.

```
### cargo fmt --check        (cwd apps/desktop/src-tauri)
(no output, exit 0 — clean)

### cargo generate-lockfile
Locking 407 packages to highest compatible versions
=> tauri 2.12.4, tauri-build 2.7.3 locked
```

### `cargo clippy` / `cargo build` — BLOCKED on this host (NOT run to completion; NOT claimed passed)

`cargo build` and `cargo clippy --all-targets -- -D warnings` cannot complete on this machine
because there is **no MSVC linker or Windows SDK installed** (the active and only Rust toolchain is
`stable-x86_64-pc-windows-msvc`, which requires MSVC `link.exe` + the Windows SDK import libs such
as `kernel32.lib`). Exhaustive checks found no Visual Studio / Build Tools install, no `link.exe`
or `cl.exe` under `Program Files`/`Program Files (x86)`, and no `Windows Kits` SDK libs. With no
MSVC linker on `PATH`, cargo falls through to the MSYS/Git-bash Unix `link` (`/usr/bin/link`), which
fails even when compiling build scripts / proc-macros (serde, thiserror, …):

```
### cargo check  (cwd apps/desktop/src-tauri, PATH exported)
error: linking with `link.exe` failed: exit code: 1
  = note: link: extra operand '...build_script_build...rcgu.o'
          Try 'link --help' for more information.
error: could not compile `serde` (build script) due to 1 previous error
...
```

This contradicts the task `context.json` claim that `cargo build`/`clippy` are runnable here; they
are not, because the MSVC toolchain's linker is absent. Per the project **honesty rule**, these two
checks are reported as **BLOCKED / pending**, NOT as passed. Resolving them requires either
installing the VS 2022 C++ Build Tools + Windows SDK (so the pinned `x86_64-pc-windows-msvc` target
can link) or running them on a GitHub `windows-latest` CI runner (which has MSVC preinstalled —
this is the same environment task 1.6's `build-installer` job targets). Switching to a GNU/mingw
toolchain was deliberately NOT done: it would change the project's pinned build target and the
sidecar triple, an out-of-scope architecture change.

### done-criterion mapping (tasks.md 1.2 "`tauri dev` opens a window")

- **Verified:** frontend lint/test/strict-TS build all green; theme tokens + blank Home present;
  icons generated and all `bundle.icon` paths exist; Tauri config + `externalBin`
  (`binaries/texora-engine`) + `targets ["msi","nsis"]` intact; crate dependency graph resolves and
  `Cargo.lock` is pinned; `cargo fmt --check` clean.
- **Pending MANUAL confirmation:** the interactive `tauri dev` WINDOW actually opening — NOT run,
  NOT claimed. It depends on a successful `cargo build`, which is blocked on this host (see above).
- **Blocked on this host (needs MSVC linker / CI):** `cargo clippy --all-targets -- -D warnings`
  and `cargo build`.
