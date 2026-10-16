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
