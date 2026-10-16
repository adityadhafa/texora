# Dependency Licenses — Texora

Every third-party dependency Texora ships or builds with is listed here with its pinned
version, ecosystem, license, and a personal-use / redistribute verdict. A row **must** be
added in the same change that introduces a dependency (see
`.kiro/steering/coding-standards.md`).

Texora is **permissive-first**: we prefer Apache-2.0 / MIT / BSD components. Copyleft or
non-commercial pieces are opt-in only and are never bundled as the shipped default
(see the "Deferred / opt-in only" section below).

Licenses below were verified against official package metadata (PyPI JSON, the npm registry,
and crates.io) during M1 planning/implementation. Versions are the M1 pins; if a listed patch
is unavailable at install time, pick the nearest existing patch in the same minor line and
update the row.

> Scope note: this table seeds every dependency that M1 will add across its tasks. The
> row-vs-manifest cross-check becomes fully enforceable once the Python (`engine/`,
> FEAT-003), frontend (`apps/desktop/package.json`, FEAT-002), and Rust
> (`apps/desktop/src-tauri/Cargo.toml`, FEAT-004) manifests exist. At FEAT-001 the manifests
> are not yet present, so the rows below are authoritative pins the later manifests must match.

## Engine (Python 3.11) — runtime

| Dependency        | Version   | Ecosystem | License       | Personal use | Redistribute | Notes |
|-------------------|-----------|-----------|---------------|--------------|--------------|-------|
| fastapi           | 0.143.2   | PyPI      | MIT           | Yes          | Yes          | Web framework for the loopback engine API. |
| uvicorn[standard] | 0.54.0    | PyPI      | BSD-3-Clause  | Yes          | Yes          | ASGI server hosting the FastAPI app. |
| pydantic          | 2.14.1    | PyPI      | MIT           | Yes          | Yes          | Pydantic v2 models for all API I/O. |
| pydantic-settings | 2.16.0    | PyPI      | MIT           | Yes          | Yes          | Typed settings loading (host/port/token). |

## Engine (Python 3.11) — dev / test

| Dependency      | Version | Ecosystem | License      | Personal use | Redistribute | Notes |
|-----------------|---------|-----------|--------------|--------------|--------------|-------|
| httpx           | 0.28.1  | PyPI      | BSD-3-Clause | Yes          | Yes          | Async client / FastAPI TestClient in tests. |
| pytest          | 8.3.3   | PyPI      | MIT          | Yes          | Yes          | Test runner. Dev-only, not shipped. |
| pytest-asyncio  | 0.24.0  | PyPI      | Apache-2.0   | Yes          | Yes          | Async test support. Dev-only. |
| ruff            | 0.6.9   | PyPI      | MIT          | Yes          | Yes          | Linter. Dev-only. |
| black           | 24.10.0 | PyPI      | MIT          | Yes          | Yes          | Formatter. Dev-only. |
| mypy            | 1.11.2  | PyPI      | MIT          | Yes          | Yes          | Static type checker. Dev-only. |

## Engine (Python 3.11) — build / packaging

| Dependency                | Version | Ecosystem | License                                   | Personal use | Redistribute | Notes |
|---------------------------|---------|-----------|-------------------------------------------|--------------|--------------|-------|
| pyinstaller               | 6.22.3  | PyPI      | GPL-2.0-or-later WITH Bootloader-exception | Yes          | Yes          | The bootloader exception explicitly permits shipping the frozen app under any license; PyInstaller itself is a build tool, not linked into the engine. |
| pyinstaller-hooks-contrib | 2026.8  | PyPI      | Apache-2.0 AND GPL-2.0-or-later           | Yes          | Yes          | Hook collection used by PyInstaller at build time. Not shipped. |

## Shell / frontend (`apps/desktop`) — npm

| Dependency               | Version | Ecosystem | License            | Personal use | Redistribute | Notes |
|--------------------------|---------|-----------|--------------------|--------------|--------------|-------|
| react                    | 18.3.1  | npm       | MIT                | Yes          | Yes          | UI runtime. |
| react-dom                | 18.3.1  | npm       | MIT                | Yes          | Yes          | React DOM renderer. |
| @types/react             | 18.3.12 | npm       | MIT                | Yes          | Yes          | React type definitions. Dev-only. |
| @types/react-dom         | 18.3.1  | npm       | MIT                | Yes          | Yes          | React DOM type definitions. Dev-only. |
| @types/node              | 22.12.0 | npm       | MIT                | Yes          | Yes          | Node type definitions for `tsconfig.node.json`. Dev-only. |
| @tauri-apps/api          | 2.9.0   | npm       | Apache-2.0 OR MIT  | Yes          | Yes          | Typed JS bridge to Tauri commands/events. |
| @tauri-apps/cli          | 2.12.0  | npm       | Apache-2.0 OR MIT  | Yes          | Yes          | Tauri CLI, invoked as `pnpm tauri`. Dev-only. |
| vite                     | 7.0.0   | npm       | MIT                | Yes          | Yes          | Dev server + bundler. Dev-only. |
| @vitejs/plugin-react     | 4.7.0   | npm       | MIT                | Yes          | Yes          | React plugin for Vite. Dev-only. |
| tailwindcss              | 3.4.17  | npm       | MIT                | Yes          | Yes          | Utility CSS. |
| typescript               | 5.6.3   | npm       | Apache-2.0         | Yes          | Yes          | TypeScript compiler. Dev-only. |
| vitest                   | 3.2.7   | npm       | MIT                | Yes          | Yes          | Unit test runner. Dev-only. Pinned to 3.2.7 (vite 7 is a supported peer; vitest 2.x only supported vite ≤6 and produced a config type mismatch). |
| @testing-library/react   | 16.3.0  | npm       | MIT                | Yes          | Yes          | React test utilities. Dev-only. |
| jsdom                    | 25.0.1  | npm       | MIT                | Yes          | Yes          | DOM for vitest. Dev-only. |
| eslint                   | 9.17.0  | npm       | MIT                | Yes          | Yes          | Linter. Dev-only. |
| @eslint/js               | 9.17.0  | npm       | MIT                | Yes          | Yes          | ESLint JS recommended config. Dev-only. |
| typescript-eslint        | 8.18.1  | npm       | MIT                | Yes          | Yes          | TS ESLint tooling (parser + plugin). Dev-only. |
| eslint-plugin-react-hooks   | 5.1.0  | npm    | MIT                | Yes          | Yes          | React Hooks lint rules. Dev-only. |
| eslint-plugin-react-refresh | 0.4.16 | npm    | MIT                | Yes          | Yes          | Fast-refresh lint rules for Vite. Dev-only. |
| globals                  | 15.14.0 | npm       | MIT                | Yes          | Yes          | Global identifier sets for ESLint flat config. Dev-only. |
| prettier                 | 3.4.2   | npm       | MIT                | Yes          | Yes          | Formatter. Dev-only. |
| postcss                  | 8.4.49  | npm       | MIT                | Yes          | Yes          | CSS transform pipeline (Tailwind). Dev-only. |
| autoprefixer             | 10.4.20 | npm       | MIT                | Yes          | Yes          | PostCSS vendor-prefixing plugin. Dev-only. |
| pnpm                     | 9.15.9  | npm       | MIT                | Yes          | Yes          | Package manager, pinned via `packageManager`. |
| @tauri-apps/plugin-shell | 2.5.0   | npm       | Apache-2.0 OR MIT  | Yes          | Yes          | JS side of the Tauri shell plugin, paired with the Rust `tauri-plugin-shell`. |
| i18next                  | 26.4.7  | npm       | MIT                | Yes          | Yes          | Internationalization core (`id` default + `en`). |
| react-i18next            | 17.0.20 | npm       | MIT                | Yes          | Yes          | React bindings for i18next (`useTranslation`). |

## Shell / frontend (`apps/desktop/src-tauri`) — Rust crates

| Dependency  | Version | Ecosystem | License            | Personal use | Redistribute | Notes |
|-------------|---------|-----------|--------------------|--------------|--------------|-------|
| tauri       | 2.12.4  | crates.io | Apache-2.0 OR MIT  | Yes          | Yes          | Desktop shell runtime. Latest stable 2.x crate (the npm `@tauri-apps/cli` is 2.12.0; the Rust crate versions independently). |
| tauri-build | 2.7.3   | crates.io | Apache-2.0 OR MIT  | Yes          | Yes          | Tauri build script dep. Latest stable 2.x crate paired with tauri 2.12.4. |
| tokio       | 1.53.3  | crates.io | MIT                | Yes          | Yes          | Async runtime for the supervisor (spawn/health-check/backoff loop). |
| serde       | 1.x     | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Serialization for commands/events. |
| serde_json  | 1.x     | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | JSON (status payloads). |
| rand        | 0.8.8   | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | 256-bit session token generation (`rand::rngs::OsRng`). |
| ureq        | 2.12.1  | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Lightweight blocking HTTP client for the supervisor `/healthz` probe (chosen over `reqwest`: no async TLS stack needed for loopback HTTP). |
| tauri-plugin-shell | 2.5.0 | crates.io | MIT OR Apache-2.0 | Yes       | Yes          | Official Tauri sidecar/process spawn (handles externalBin `-$TARGET_TRIPLE` resolution). |

## Deferred / opt-in only

These are **not** dependencies in M1 and are not bundled as defaults anywhere in Texora. They
are documented here so the permissive-first policy is explicit.

| Component | Ecosystem | License                                         | Personal use | Redistribute | Policy |
|-----------|-----------|-------------------------------------------------|--------------|--------------|--------|
| PyMuPDF (fitz) | PyPI | AGPL-3.0 (or commercial)                     | Yes (local)  | No (as default) | **Opt-in only, never default.** The chosen PDF renderer is `pypdfium2` (BSD/Apache), added in M3. PyMuPDF may only be enabled by the user for local personal use. |
| Surya (OCR / layout) | PyPI / GitHub | GPL-3.0 code + non-commercial RAIL weights | Yes (local, personal) | No | **Opt-in only, not redistributable.** Code is GPL and the weights are non-commercial RAIL; never shipped as a default. |

**Neither PyMuPDF nor Surya is a dependency in M1.** No Surya or PyMuPDF reference appears in
any M1 manifest (`engine/` requirements, `apps/desktop/package.json`, or `Cargo.toml`).
