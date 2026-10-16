# Texora — Requirements

> Offline-first desktop app for high-accuracy OCR of mathematical and scientific documents
> (printed + handwritten), with unlimited PDF page count and no cloud quota.

Status: Draft v1 (SPEC phase). Acceptance criteria use EARS (Easy Approach to Requirements
Syntax). Each requirement has a stable ID (`R-<area>-<n>`) referenced by `design.md` and `tasks.md`.

Keywords: WHEN (event), WHILE (state), IF/THEN (conditional), WHERE (feature-dependent), THE
SYSTEM SHALL (mandated behavior).

---

## 1. Scope & Personas

- **Primary persona:** a single technical end user installing Texora on their own machine
  (Windows 10/11 x64 primary; Linux AppImage and macOS arm64 secondary) for personal use.
- **Non-goals (v1):** multi-user servers, SaaS deployment, mandatory cloud, redistribution of
  non-permissive model weights, chemistry (deferred to a later module), EPUB (optional/stretch).
- **Guiding constraint:** 100% offline by default. Any network egress is explicit and opt-in.

---

## 2. Functional Requirements

### 2.1 Installation & Runtime (R-INST)

- **R-INST-1** — WHEN the user runs the platform installer (.msi/.exe on Windows, .AppImage on
  Linux, .dmg/.app on macOS arm64), THE SYSTEM SHALL install and launch Texora without requiring
  the user to install Python, Node, or any model runtime manually.
- **R-INST-2** — WHILE launching for the first time with no models present, THE SYSTEM SHALL
  present a first-run flow that downloads the default model set with a progress UI, per-file size,
  overall ETA, and a cancel control.
- **R-INST-3** — WHEN a model file finishes downloading, THE SYSTEM SHALL verify its integrity
  against a pinned SHA-256 checksum, and IF the checksum mismatches, THEN THE SYSTEM SHALL discard
  the file, surface an error, and offer retry.
- **R-INST-4** — WHERE an offline-install model bundle is provided alongside the installer, THE
  SYSTEM SHALL import models from that bundle without any network access.
- **R-INST-5** — WHEN the app starts, THE SYSTEM SHALL start the Python engine sidecar bound to
  `127.0.0.1` on an ephemeral port with a per-session auth token, and SHALL NOT expose it on any
  non-loopback interface.
- **R-INST-6** — IF the sidecar fails to start or becomes unresponsive, THEN THE SYSTEM SHALL
  surface a clear error, keep the UI responsive, and offer a restart action plus an "export
  diagnostics" control.

### 2.2 Hardware & Engine Selection (R-HW)

- **R-HW-1** — WHEN the engine starts, THE SYSTEM SHALL auto-detect available accelerators (NVIDIA
  CUDA, Apple MPS, else CPU) and select GPU with fp16 batch inference where available.
- **R-HW-2** — WHERE no supported GPU is detected, THE SYSTEM SHALL fall back to CPU execution
  (ONNX Runtime / OpenVINO optimized paths where available) and SHALL clearly communicate that CPU
  mode is slower.
- **R-HW-3** — THE SYSTEM SHALL display detected hardware in Settings and SHALL allow the user to
  override the execution device and per-stage engine selection.

### 2.3 Ingestion (R-ING)

- **R-ING-1** — THE SYSTEM SHALL accept PDF, PNG, JPG/JPEG, multi-page TIFF, WEBP, BMP, HEIC,
  clipboard images, and screen-region captures as input.
- **R-ING-2** — WHEN rendering a PDF page, THE SYSTEM SHALL render at an adaptive DPI (default
  220–300) and SHALL raise DPI automatically when small fonts are detected.
- **R-ING-3** — THE SYSTEM SHALL detect whether a PDF is born-digital or scanned; WHERE born-digital
  text is reliably extractable THE SYSTEM SHALL use it for plain text, but SHALL STILL run formula
  recognition on math regions.
- **R-ING-4** — THE SYSTEM SHALL apply preprocessing (deskew, denoise, contrast/binarization,
  perspective correction, auto-crop, print-vs-handwriting detection) when it improves recognition,
  and SHALL be able to disable each step via configuration.

### 2.4 Layout Analysis (R-LAY)

- **R-LAY-1** — THE SYSTEM SHALL detect region types: title, paragraph, inline math, display math,
  equation number, table, figure, caption, footnote, header/footer, list, code, and handwriting.
- **R-LAY-2** — THE SYSTEM SHALL compute reading order correctly for single- and multi-column
  layouts, including side-by-side equation numbering.
- **R-LAY-3** — Each detected region SHALL carry a bounding box, region-type label, and a detection
  confidence score.

### 2.5 Recognition (R-REC)

- **R-REC-1** — THE SYSTEM SHALL recognize body text with first-class support for English and
  Indonesian, and SHALL support additional languages via optional packs.
- **R-REC-2** — THE SYSTEM SHALL convert math region images to LaTeX via a swappable formula
  recognizer, and SHALL assign a confidence score to each formula.
- **R-REC-3** — THE SYSTEM SHALL recognize tables and emit them as LaTeX `tabular`, Markdown, and
  HTML.
- **R-REC-4** — THE SYSTEM SHALL provide a dedicated handwritten-math recognition path.
- **R-REC-5** — IF a formula's confidence is below a configurable threshold, THEN THE SYSTEM SHALL
  re-run recognition with a second engine, compare candidates by normalized-LaTeX similarity, and
  select the best by a vote of validity + confidence.
- **R-REC-6** — THE SYSTEM SHALL validate each LaTeX result by parsing it (balanced braces, valid
  `\left`/`\right`, valid environments) and by a render check (KaTeX), and SHALL flag results that
  fail validation as "needs review" rather than silently emitting them.
- **R-REC-7** — THE SYSTEM SHALL normalize LaTeX output (consistent `\frac`/`\dfrac`, spacing,
  `\operatorname`, `\mathrm`) and correct common OCR confusions while keeping output compilable.
- **R-REC-8** — THE SYSTEM SHALL NOT emit fabricated or placeholder recognition results in any
  production path; a region that cannot be recognized SHALL be marked failed/needs-review.

### 2.6 Assembly & Export (R-EXP)

- **R-EXP-1** — THE SYSTEM SHALL reassemble a document preserving structure, reading order,
  equation numbering, figures (cropped and saved), and tables.
- **R-EXP-2** — THE SYSTEM SHALL export to: LaTeX (.tex, compilable with preamble options),
  Markdown (`$...$`/`$$...$$`), DOCX with native editable Word equations (OMML), HTML (KaTeX),
  MathML, AsciiMath, plain text, JSON (bboxes + confidence + reading order), and searchable PDF
  (invisible text layer). EPUB is optional.
- **R-EXP-3** — WHEN the user requests a per-formula copy, THE SYSTEM SHALL offer LaTeX, MathML,
  OMML, and AsciiMath (Typst optional).
- **R-EXP-4** — A generated LaTeX export SHALL compile with the documented preamble; a generated
  DOCX SHALL open in Word with equations editable as native OMML (verified by golden-file tests).

### 2.7 Unlimited Pages & Jobs (R-JOB)

- **R-JOB-1** — THE SYSTEM SHALL process PDFs of arbitrary page count (verified on a synthetic
  5,000+ page document) WHILE keeping memory usage approximately constant (streaming, bounded work
  queue, back-pressure); it SHALL NOT load the whole document into memory.
- **R-JOB-2** — THE SYSTEM SHALL checkpoint per-page progress in SQLite such that WHEN the app
  crashes, is killed, or the machine reboots mid-job, THEN resuming SHALL continue from the last
  completed page with no duplicated or lost pages.
- **R-JOB-3** — THE SYSTEM SHALL support pause, resume, cancel, and reprioritize on jobs, and SHALL
  process a full document, a page range, or an explicit page list.
- **R-JOB-4** — THE SYSTEM SHALL run pipeline stages concurrently (render ‖ layout ‖ recognition ‖
  export) with GPU batch scheduling and a CPU worker pool sized to cores, configurable in Settings.
- **R-JOB-5** — WHILE a job runs, THE SYSTEM SHALL display per-page status, ETA, and pages/min, and
  SHALL write incremental output as pages complete.
- **R-JOB-6** — IF a single page fails, THEN THE SYSTEM SHALL log it, mark the page failed, continue
  the job, and allow a later retry of only failed pages.
- **R-JOB-7** — THE SYSTEM SHALL support batch input (multiple files/folders) and a watch-folder
  mode that auto-processes newly added files.

### 2.8 User Interface (R-UI)

- **R-UI-1** — THE SYSTEM SHALL provide a Home/Library with drag-and-drop, recent documents, and
  full-text search across all recognized content (SQLite FTS5).
- **R-UI-2** — THE SYSTEM SHALL provide a Snip Tool bound to a global hotkey (default
  Ctrl+Shift+M) that captures a screen region and returns LaTeX in a popup with one-click copy
  (LaTeX / MathML / Markdown / OMML); on a mid-range GPU a single equation SHALL return in ≤1.5 s.
- **R-UI-3** — THE SYSTEM SHALL provide a Document Workspace with a split view: original page
  (zoom/pan, bbox overlay colored by region type and confidence) and an editable result (Monaco
  editor + live KaTeX preview); selecting a box SHALL highlight the matching output and vice versa.
- **R-UI-4** — THE SYSTEM SHALL provide a "Needs review" panel listing low-confidence/invalid items
  with keyboard shortcuts (next/prev/accept/edit).
- **R-UI-5** — THE SYSTEM SHALL provide a handwriting canvas (mouse/pen/touch) that returns LaTeX
  with live preview.
- **R-UI-6** — THE SYSTEM SHALL provide a Batch/Queue screen with global progress, throughput,
  errors, and retry-failed-pages.
- **R-UI-7** — THE SYSTEM SHALL provide a Settings screen: model manager (download/update/delete,
  disk usage, per-stage engine choice), hardware, DPI, output defaults, LaTeX preamble templates,
  language packs, privacy, keyboard shortcuts, and theme (dark + light).
- **R-UI-8** — THE SYSTEM SHALL provide a Compare/Benchmark view that runs a sample through multiple
  engines side by side and shows a diff.
- **R-UI-9** — THE SYSTEM SHALL support undo/redo and autosave, and SHALL store user corrections
  locally; WHERE enabled, corrections SHALL feed a local correction dictionary for post-correction.
- **R-UI-10** — THE SYSTEM SHALL default its UI language to Indonesian with an English option and an
  i18n system for adding languages.
- **R-UI-11** — THE SYSTEM SHALL be keyboard-first and SHALL support scalable fonts and a
  high-contrast mode.

### 2.9 Optional Cloud / BYOK (R-BYOK)

- **R-BYOK-1** — THE SYSTEM SHALL provide a plugin interface for optional recognizer/tie-breaker
  backends (Gemini, OpenAI, Anthropic, any OpenAI-compatible endpoint, local Ollama/LM Studio/vLLM),
  disabled by default.
- **R-BYOK-2** — THE SYSTEM SHALL store API keys in the OS credential vault, never in plaintext
  config.
- **R-BYOK-3** — WHILE a BYOK backend is enabled, THE SYSTEM SHALL display a clear warning wherever
  data would leave the machine, before sending it.

---

## 3. Non-Functional Requirements

### 3.1 Privacy & Security (R-SEC)

- **R-SEC-1** — WITH default settings, THE SYSTEM SHALL make no network calls except explicit model
  downloads and explicitly user-enabled BYOK backends; THE SYSTEM SHALL emit zero telemetry.
- **R-SEC-2** — THE SYSTEM SHALL bind the engine to loopback only and require the session token on
  every request.
- **R-SEC-3** — THE SYSTEM SHALL sanitize and validate file paths and SHALL guard against malicious
  PDFs via resource limits and per-page timeouts, isolating a hostile document to a failed page.
- **R-SEC-4** — THE SYSTEM SHALL keep crash reporting local (no auto-upload) and provide an "export
  diagnostics" action.

### 3.2 Performance (R-PERF)

- **R-PERF-1** — On a mid-range NVIDIA GPU, a single-equation snip SHALL complete in ≤1.5 s
  (measured; recorded in docs).
- **R-PERF-2** — On a mid-range NVIDIA GPU, typical text+math pages SHALL process at ≥20 pages/min
  (measured; recorded in docs).
- **R-PERF-3** — CPU-only mode SHALL be functional and its slower throughput SHALL be measured and
  documented.

### 3.3 Quality & Testing (R-QA)

- **R-QA-1** — THE SYSTEM SHALL include a reproducible benchmark harness in `/benchmarks` with
  metrics: formula (CDM, BLEU, normalized edit distance, exact-match-after-normalization), layout
  (mAP), tables (TEDS), full-document (text edit distance, reading-order).
- **R-QA-2** — The default `pipeline.yaml` configuration SHALL be chosen by measured benchmark
  results, documented in `docs/BENCHMARKS.md` with real numbers (no unsupported accuracy claims).
- **R-QA-3** — THE SYSTEM SHALL have unit tests (pytest, vitest), integration tests, golden-file
  export tests, and E2E tests (Tauri driver / Playwright), targeting >80% coverage on core logic.
- **R-QA-4** — THE SYSTEM SHALL use structured, rotating-file logging.

### 3.4 Licensing (R-LIC)

- **R-LIC-1** — Before adopting any model or library, its license SHALL be recorded in
  `docs/LICENSES.md` with a redistribution verdict (OK for personal use vs. OK to redistribute).
- **R-LIC-2** — THE DEFAULT shipped configuration SHALL prefer permissive (Apache-2.0/MIT/BSD)
  components; copyleft (GPL/AGPL) or non-commercial components SHALL be opt-in behind an explicit
  acknowledgment and SHALL NOT be bundled in the redistributable installer by default.

---

## 4. Definition of Done (traceable)

- **DoD-1** (R-INST-1, R-JOB-1/2) — Install via normal installer on Windows, OCR a 1,000+ page
  math-heavy PDF end-to-end with no manual Python setup and no page cap.
- **DoD-2** (R-JOB-2) — Killing the app mid-job and reopening resumes correctly.
- **DoD-3** (R-EXP-4) — LaTeX exports compile; DOCX opens with editable equations.
- **DoD-4** (R-QA-1/2, R-LIC-1) — Benchmarks and license docs exist and are honest.
- **DoD-5** — README covers install, build-from-source, model setup, troubleshooting, architecture.
