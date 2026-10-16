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
