# Coding Standards — Texora

## General
- No placeholder/stub code or fake outputs in production paths. No mocked OCR results outside tests.
- Pin dependency versions. Verify every library/model/API against current official docs before use;
  do not invent APIs.
- Small, testable units. Each task ships with tests and passes lint/type checks before completion.
- Fail gracefully: catch per-page errors, log with context, mark state, continue. Never crash a job
  on one bad page.

## Python (engine)
- Python 3.11, full type hints, `mypy` clean. Format with `black`; lint with `ruff`.
- Pydantic v2 models for all API I/O and config. No untyped dicts across module boundaries.
- Engine adapters implement the `Protocol` in `recognizers/base.py` (or `layout/base.py`); expose a
  stable `id` and pure `recognize(...)` with explicit result dataclasses.
- Structured logging via the shared logger (rotating files). No bare `print` in library code.
- Resource safety: per-page timeouts, bounded concurrency, free bitmaps/intermediates promptly.
- Tests: `pytest`; golden-file tests for exports; real fixtures for recognition (no mocked OCR in
  the production code path). Target >80% coverage on core logic.

## TypeScript / React (shell)
- Strict TS (`strict: true`), no `any` without justification. ESLint + Prettier.
- Functional components + hooks; state in Zustand/Redux Toolkit; server calls via TanStack Query.
- All engine calls go through the single typed client; components never call `fetch`/`invoke`
  directly.
- All user-facing strings via i18next (`id` default, `en` provided). No hard-coded UI text.
- Accessibility: keyboard-first, focus management, ARIA, scalable fonts, high-contrast theme.

## Rust (Tauri)
- `cargo fmt` + `clippy` clean. Supervisor handles token/port generation, spawn, health-check,
  restart-with-backoff. Keep business logic out of Rust; it is a secure client + process manager.

## Security
- Engine loopback-only + bearer token on every non-health route. Sanitize/validate all file paths.
- Secrets (BYOK keys) only in the OS credential vault; never in config files or logs.
- Guard against malicious PDFs: resource limits, timeouts, isolation.

## Git
- Small focused commits; conventional-commit style messages. Add license rows for new deps in the
  same change. Don't commit model weights or large binaries.
