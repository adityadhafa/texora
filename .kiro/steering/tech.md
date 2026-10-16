# Tech — Texora

## Stack (pin all versions; verify against official docs before use)
- **Shell:** Tauri v2 (2.12.x) + Rust. React 18 + TypeScript + Vite + Tailwind. Monaco editor,
  KaTeX (MathJax fallback), i18next.
- **Engine:** Python 3.11 sidecar, FastAPI + Uvicorn, Pydantic v2. Packaged with PyInstaller as a
  single self-contained binary, embedded as a Tauri `externalBin` sidecar (naming:
  `<name>-$TARGET_TRIPLE`). End user never installs Python.
- **Storage:** SQLite (WAL) with FTS5. Files on disk.
- **ML runtimes:** PyTorch (CUDA fp16 / Apple MPS), ONNX Runtime / OpenVINO for CPU paths.

## Engine defaults (provisional until M7 benchmarks)
- **PDF render:** `pypdfium2` (BSD/Apache). PyMuPDF is AGPL → optional, opt-in only, never default.
- **Images:** Pillow + pillow-heif. Preprocess: OpenCV.
- **Layout:** DocLayout-YOLO (VERIFY license at adoption — Ultralytics lineage may be AGPL; if so,
  opt-in only and find a permissive default).
- **Text OCR:** PaddleOCR PP-OCRv5 default, Tesseract (Apache-2.0) fallback. EN + ID first-class.
- **Formula:** PP-FormulaNet-S/-L or UniMERNet (Apache-2.0 pkg); evaluate Texify, pix2tex, VLMs.
- **Table:** SLANet. **Handwriting:** VLM (Qwen2.5/3-VL, GOT-OCR2.0) or CROHME-tuned.
- **Surya:** code GPL + weights non-commercial RAIL → opt-in only (personal use OK, not
  redistributable). Never shipped as default.

## Architecture rules
- Engine adapters implement a stable Python Protocol; pipeline wired via `pipeline.yaml`. UI never
  depends on a specific engine.
- Engine binds `127.0.0.1` + ephemeral port + per-session bearer token. No non-loopback exposure.
- Jobs are a per-page SQLite state machine (`pending→leased→done|failed`) with lease expiry for
  crash-safe resume; per-page export is idempotent (temp + atomic rename). Memory stays ~constant.
- Per-page timeout + resource guard; a failed page never kills a job.

## Commands (adapt to Windows/bash)
- Frontend: pnpm; `pnpm dev`, `pnpm build`, `pnpm lint`, `pnpm test` (vitest), `pnpm e2e`.
- Tauri: `pnpm tauri dev`, `pnpm tauri build`.
- Engine: `ruff`, `black --check`, `mypy`, `pytest` (run via the engine venv/uv).
- Never start long-running dev servers/watchers via automation; the user runs those manually.

## Verification
- After any change: run the relevant build/lint/tests. OCR-affecting changes must pass the
  benchmark smoke before completion. Clean up temp files.
