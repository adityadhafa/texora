# Texora

Offline-first desktop OCR for mathematical and scientific documents (printed and
handwritten) — Mathpix-class UX running locally, with no cloud quota and no PDF page cap.

## Status

**Milestone M1 — runnable skeleton (in progress).** This repository currently contains the
monorepo scaffold: a pnpm workspace, the Tauri + React desktop shell, the Python FastAPI
engine sidecar, and CI. OCR pipeline stages (ingest, layout, recognition, ensemble, export)
land in later milestones (M2+).

## Architecture

Texora is two cooperating processes in one monorepo:

- **`apps/desktop`** — Tauri v2 (Rust) shell + React 18 / TypeScript / Vite / Tailwind UI. The
  Rust side is a supervisor and secure process manager; the UI holds no ML logic.
- **`engine`** — a Python 3.11 sidecar exposing a loopback-only FastAPI server (bound to
  `127.0.0.1`, ephemeral port, per-session bearer token). Packaged with PyInstaller into a
  self-contained binary and shipped as a Tauri `externalBin` sidecar, so the end user never
  installs Python.

See `.kiro/specs/texora/` for requirements, design, and the task breakdown, and
`.kiro/steering/` for the product, tech, structure, and coding-standards guardrails.

## Build from source

> Full build and packaging instructions arrive with later milestones (engine freeze in M1
> task 1.5, CI installer in M1 task 1.6). The outline below reflects the M1 skeleton.

Prerequisites: Node 20.19+ (or 22.12+), pnpm 9 (via `corepack enable pnpm`), Rust stable
toolchain, and Python 3.11 for the engine.

```sh
# install workspace dependencies
corepack enable pnpm
pnpm install

# frontend
pnpm --filter desktop lint
pnpm --filter desktop test -- --run
pnpm --filter desktop build

# engine (from engine/, inside a Python 3.11 virtualenv)
ruff check .
black --check .
mypy texora_engine
pytest -q
```

## Licensing

Texora is MIT-licensed (see [`LICENSE`](./LICENSE)). It is permissive-first: copyleft or
non-commercial components are opt-in only and never bundled as a shipped default. Every
dependency and its license verdict is tracked in [`docs/LICENSES.md`](./docs/LICENSES.md).
