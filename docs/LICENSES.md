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
| httpx             | 0.28.1    | PyPI      | BSD-3-Clause  | Yes          | Yes          | **Promoted dev→runtime in M2.** Streaming HTTP client for the model downloader (R-INST-2). |
| pix2tex           | 0.1.4     | PyPI      | MIT           | Yes          | Yes          | Default M2 formula OCR model package (LaTeX-OCR). MIT code; its weights are a separate row under "ML models". |
| torch             | 2.3.1+cpu | PyPI (PyTorch CPU index) | BSD-3-Clause | Yes | Yes | Tensor runtime backing pix2tex. CPU wheel from `https://download.pytorch.org/whl/cpu` (no CUDA payload). |
| torchvision       | 0.18.1+cpu | PyPI (PyTorch CPU index) | BSD-3-Clause | Yes | Yes | torch companion required by the pix2tex/timm stack; version matched to torch 2.3.1. |
| pillow            | 10.4.0    | PyPI      | HPND (MIT-CMU) | Yes         | Yes          | Decode snip images; feed the model. Decompression-bomb guard via `Image.MAX_IMAGE_PIXELS`. |
| pypdfium2         | 5.14.0    | PyPI      | BSD-3-Clause / Apache-2.0 | Yes | Yes       | **M3.** PDF renderer (shipped default; permissive-first choice over AGPL PyMuPDF). Adaptive-DPI page render + born-digital text-layer extraction. |
| pillow-heif       | 0.18.0    | PyPI      | BSD-3-Clause  | Yes          | Yes          | **M3.** HEIC/HEIF image decode via `register_heif_opener()`. Bundled `libheif` is LGPL-3.0, dynamically linked (redistributable); no static LGPL linkage. |
| onnxruntime       | 1.19.2    | PyPI      | MIT           | Yes          | Yes          | **M3.** CPU-default inference runtime for the PP-DocLayout / PP-OCRv5 ONNX paths (CUDA EP selected via `settings.device`). Resolved to latest 1.19 patch (1.19.2) on PyPI. |
| pytesseract       | 0.3.13    | PyPI      | Apache-2.0    | Yes          | Yes          | **M3.** Wrapper for the permissive Tesseract fallback text OCR. The system/bundled **Tesseract 5.x** engine it drives is also Apache-2.0. |
| shapely           | 2.0.6     | PyPI      | BSD-3-Clause  | Yes          | Yes          | **M3 (FEAT-004).** Polygon geometry for the PP-OCRv5 ONNX detection post-process (DB box area/length → unclip distance). Verified BSD-3-Clause against official PyPI/GitHub metadata. |
| pyclipper         | 1.3.0.post6 | PyPI    | MIT           | Yes          | Yes          | **M3 (FEAT-004).** Vatti polygon-offset (unclip) for the PP-OCRv5 ONNX detection post-process. Verified MIT against official PyPI metadata. Resolved to the latest cp311 wheel `1.3.0.post6`. |
| pylatexenc        | 2.10      | PyPI      | MIT           | Yes          | Yes          | LaTeX parse/structure validation (`LatexWalker`). |
| latex2mathml      | 3.77.0    | PyPI      | MIT           | Yes          | Yes          | LaTeX→MathML for the snip result. |
| transformers      | 4.42.4    | PyPI      | Apache-2.0    | Yes          | Yes          | Transitive (pix2tex tokenizer); pinned to the era-matched line for torch 2.3.1. |
| tokenizers        | 0.19.1    | PyPI      | Apache-2.0    | Yes          | Yes          | Transitive (pix2tex `PreTrainedTokenizerFast`). |
| huggingface-hub   | 0.24.6    | PyPI      | Apache-2.0    | Yes          | Yes          | Transitive (transformers). Not used for model fetch — our registry does that. |
| numpy             | 1.26.4    | PyPI      | BSD-3-Clause  | Yes          | Yes          | Transitive (torch/opencv/pix2tex); numpy-1.x line for torch 2.3.1 compatibility. |
| opencv-python-headless | 4.10.0.84 | PyPI | Apache-2.0    | Yes          | Yes          | Transitive (pix2tex/albumentations preprocessing). Headless (no GUI libs). |
| albumentations    | 1.4.15    | PyPI      | MIT           | Yes          | Yes          | Transitive (pix2tex `test_transform`). |
| albucore          | 0.0.16    | PyPI      | MIT           | Yes          | Yes          | Transitive (albumentations core); version matched to albumentations 1.4.15. |
| timm              | 0.5.4     | PyPI      | Apache-2.0    | Yes          | Yes          | Transitive (pix2tex image resizer backbone). |
| x-transformers    | 0.15.0    | PyPI      | MIT           | Yes          | Yes          | Transitive (pix2tex decoder wrapper). |
| einops            | 0.8.2     | PyPI      | MIT           | Yes          | Yes          | Transitive (pix2tex/x-transformers tensor ops). |
| entmax            | 1.3       | PyPI      | MIT           | Yes          | Yes          | Transitive (x-transformers). |
| munch             | 4.0.0     | PyPI      | MIT           | Yes          | Yes          | Transitive (pix2tex config object). |
| pandas            | 2.2.2     | PyPI      | BSD-3-Clause  | Yes          | Yes          | Transitive (pix2tex). |
| scipy             | 1.13.1    | PyPI      | BSD-3-Clause  | Yes          | Yes          | Transitive (albumentations/scikit-image). |
| PyYAML            | 6.0.3     | PyPI      | MIT           | Yes          | Yes          | Transitive (pix2tex config loader). |

## Engine (Python 3.11) — dev / test

| Dependency      | Version | Ecosystem | License      | Personal use | Redistribute | Notes |
|-----------------|---------|-----------|--------------|--------------|--------------|-------|
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
| pefile                    | 2024.8.26 | PyPI    | MIT                                       | Yes          | Yes          | Transitive (PyInstaller). Used directly in `scripts/build_engine.py` only to finish the Windows PE build-timestamp/checksum fix-up via temp+replace (works around the large-onefile `OSError 22`). Build-time only, not shipped. |

## ML models (downloaded at runtime, not bundled in the installer)

| Model | Version / tag | Source | License | Personal use | Redistribute | Notes |
|-------|---------------|--------|---------|--------------|--------------|-------|
| pix2tex weights (`weights.pth` + `image_resizer.pth`) | release tag `v0.0.1` | GitHub release assets on `lukas-blecher/LaTeX-OCR` | MIT | Yes | Yes | Default M2 formula model weights. Fetched through Texora's own checksum-verified downloader (never pix2tex's built-in fetcher). **SHA-256 is pin-on-first-fetch:** upstream publishes no vendor-signed checksum, so the pinned hash in `models/catalog.py` is *our* SHA-256 of the upstream asset at the pinned tag, not a vendor attestation. It guarantees integrity/immutability relative to the bytes we first pinned (tamper/corruption detection on every later fetch + offline import), which is the accepted, documented R-INST-2/3 satisfaction for the provisional M2 default. A vendor-pinned / content-addressed hash is an M7 option. See `docs/m2-verification.md` for the recorded values. |
| PP-DocLayout (`doclayout.onnx` + `label_map.txt`) | pin-on-first-fetch (upstream export tag stamped at adoption) | ONNX export of the official Apache-2.0 **PaddleOCR / PaddleX** PP-DocLayout release (or the Apache-2.0 `rapid-layout` redistribution of the same weights if a stable official ONNX URL is unavailable — same license + file-name contract) | Apache-2.0 | Yes | Yes | **M3.** Default (permissive) layout detector weights, run through ONNX Runtime. File names are pinned now in `models/catalog.py`; **URL + SHA-256 are pin-on-first-fetch** (same honesty note as pix2tex: our hash of the pinned bytes, computed on first fetch, not an upstream attestation). Fetched only through Texora's checksum-verified downloader. The AGPL DocLayout-YOLO alternative stays opt-in only (see "Deferred / opt-in only"). |
| PP-OCRv5 text detection (`det.onnx`) | pin-on-first-fetch (upstream export tag stamped at adoption) | ONNX export of the official Apache-2.0 **PaddleOCR** PP-OCRv5 detection model (or the Apache-2.0 `rapidocr-onnxruntime` redistribution — same license + file-name contract) | Apache-2.0 | Yes | Yes | **M3.** Default text-detection weights (EN + ID), ONNX Runtime. File name pinned now; URL + SHA-256 pin-on-first-fetch. |
| PP-OCRv5 text recognition (`rec.onnx` + `rec_keys.txt`) | pin-on-first-fetch (upstream export tag stamped at adoption) | ONNX export of the official Apache-2.0 **PaddleOCR** PP-OCRv5 recognition model + its character dictionary (or the Apache-2.0 `rapidocr-onnxruntime` redistribution — same license + file-name contract) | Apache-2.0 | Yes | Yes | **M3.** Default text-recognition weights (EN + ID); `rec_keys.txt` is the required character dictionary to decode the rec head's class indices. File names pinned now; URL + SHA-256 pin-on-first-fetch. |

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
| @tauri-apps/plugin-global-shortcut | 2.3.0 | npm | Apache-2.0 OR MIT | Yes      | Yes          | JS side of the global-shortcut plugin (Ctrl+Shift+M snip hotkey), paired with the Rust `tauri-plugin-global-shortcut`. |
| katex                    | 0.16.11 | npm       | MIT                | Yes          | Yes          | Math render in the snip popup (authoritative KaTeX render) + the generator input for the engine's supported-macro allow-list. |
| @types/katex             | 0.16.7  | npm       | MIT                | Yes          | Yes          | KaTeX type definitions for strict TS. Dev-only. |
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
| ureq        | 2.12.1  | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Lightweight blocking HTTP client for the supervisor `/healthz` probe + the authenticated engine proxy (chosen over `reqwest`: no async TLS stack needed for loopback HTTP). |
| base64      | 0.22.1  | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Base64-encode the captured snip PNG before it crosses to the webview / engine (`snip.rs`). |
| tauri-plugin-shell | 2.5.0 | crates.io | MIT OR Apache-2.0 | Yes       | Yes          | Official Tauri sidecar/process spawn (handles externalBin `-$TARGET_TRIPLE` resolution). |
| tauri-plugin-global-shortcut | 2.4.1 | crates.io | MIT OR Apache-2.0 | Yes | Yes     | Rust side of the global-shortcut plugin; registers the Ctrl+Shift+M snip hotkey. Resolved to 2.4.1 (latest 2.x) from the `2.3.0` floor matching the JS plugin line. |
| xcap        | 0.9.8   | crates.io | Apache-2.0         | Yes          | Yes          | Cross-platform monitor capture for the snip region grab (Windows/macOS/Linux). |
| image       | 0.25.10 | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Transitive (xcap) — PNG encode of the captured region. |
| global-hotkey | 0.8.0 | crates.io | MIT OR Apache-2.0  | Yes          | Yes          | Transitive (tauri-plugin-global-shortcut) — OS hotkey registration. |

## Deferred / opt-in only

These are **not** dependencies in M1 and are not bundled as defaults anywhere in Texora. They
are documented here so the permissive-first policy is explicit.

| Component | Ecosystem | License                                         | Personal use | Redistribute | Policy |
|-----------|-----------|-------------------------------------------------|--------------|--------------|--------|
| PyMuPDF (fitz) | PyPI | AGPL-3.0 (or commercial)                     | Yes (local)  | No (as default) | **Opt-in only, never default.** The chosen PDF renderer is `pypdfium2` (BSD/Apache), added as the M3 shipped default. PyMuPDF may only be enabled by the user for local personal use. M3 adds no PyMuPDF dependency. |
| DocLayout-YOLO (`doclayout-yolo`) | PyPI / GitHub | AGPL-3.0 (code + `ultralytics` lineage runtime) | Yes (local, personal) | No (as default) | **M3. Opt-in only, never the shipped default, not bundled** (`R-LIC-2`). `doclayout-yolo` 0.0.4 PyPI classifier is `GNU Affero General Public License v3 or later`; the `opendatalab/DocLayout-YOLO` repo and the `ultralytics` 8.4.x lineage are AGPL-3.0. Verified 2026-10-18; re-confirm the classifier from the official source at adoption. The `layout/doclayout_yolo.py` adapter exists so a user can *locally* choose it, but it is never registered in the default factory and never written as a `pipeline.yaml` default. The permissive shipped default is `pp_doclayout_onnx` (Apache-2.0). |
| Surya (OCR / layout) | PyPI / GitHub | GPL-3.0 code + non-commercial RAIL weights | Yes (local, personal) | No | **Opt-in only, not redistributable.** Code is GPL and the weights are non-commercial RAIL; never shipped as a default. |

**Neither PyMuPDF, DocLayout-YOLO, nor Surya is a shipped default anywhere.** No PyMuPDF or
Surya reference appears in any manifest; `doclayout-yolo` is not in `engine/requirements.txt`
and its adapter is never registered in the default factory.
