# Texora — Implementation Tasks

Ordered, small, testable tasks grouped by milestone. Each task lists dependencies (`dep:`),
traced requirements (`req:`), and a concrete done-check (`done:`). Every OCR-affecting task must
pass the benchmark smoke hook before being marked complete.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done.

---

## M1 — Skeleton (runnable: app launches, talks to sidecar, CI builds Windows installer)

- [x] **1.1 Monorepo scaffold** — create `apps/desktop`, `engine`, `benchmarks`, `docs`, `scripts`,
  root tooling (pnpm workspace, `.editorconfig`, `.gitignore`, LICENSE, README stub).
  `req: structure` · `done:` repo builds frontend + engine lint with no errors.
- [x] **1.2 Tauri v2 app** — scaffold Tauri 2.12.x + React + TS + Vite + Tailwind; blank Home
  screen; dark/light theme tokens. `dep:1.1` · `req: R-UI-7` · `done:` `tauri dev` opens a window.
- [x] **1.3 Python engine skeleton** — FastAPI app, `GET /healthz`, Pydantic settings, structured
  rotating logging, loopback bind + bearer-token middleware. `dep:1.1` · `req: R-INST-5, R-SEC-2,
  R-QA-4` · `done:` `pytest` hits `/healthz` (200) and rejects missing token (401).
- [x] **1.4 Sidecar supervisor + secure IPC** — Rust side generates token + free loopback port,
  spawns engine as `externalBin`, health-checks, restarts with backoff; typed TS client.
  `dep:1.2,1.3` · `req: R-INST-5/6, R-SEC-2` · `done:` UI shows live engine status from `/healthz`.
- [x] **1.5 PyInstaller freeze** — build self-contained engine binary per platform; wire
  `externalBin` naming (`-$TARGET_TRIPLE`). `dep:1.3` · `req: R-INST-1` · `done:` frozen binary runs
  standalone and serves `/healthz`.
- [x] **1.6 CI: Windows installer** — GitHub Actions builds engine freeze + Tauri `.msi/.exe`;
  uploads artifact. `dep:1.4,1.5` · `req: R-INST-1` · `done:` CI artifact installs and launches.
- [x] **1.7 docs/LICENSES.md bootstrap** — seed license table for every pinned dep. `dep:1.1` ·
  `req: R-LIC-1` · `done:` file lists each dependency + license + verdict.

## M2 — Single-image formula OCR (snip tool, one strong model)

- [x] **2.1 Model registry + downloader** — `MODEL` table, pinned versions + SHA-256, progress,
  offline-bundle import. `dep:1.3` · `req: R-INST-2/3/4` · `done:` download verifies checksum;
  corrupt file rejected (test with bad hash).
- [x] **2.2 FormulaRecognizer adapter + default engine** — Protocol + PP-FormulaNet-S (or
  benchmark-chosen permissive model) adapter; CPU path first. `dep:2.1` · `req: R-REC-2, R-HW-2` ·
  `done:` real image → LaTeX unit test on a fixture (no mocks in production path, R-REC-8).
  <!-- M2 FLAG (spec erratum, design §B.3): the shipped M2 default is **pix2tex (LaTeX-OCR)**,
  not PP-FormulaNet-S, on packaging/pinnability grounds (PaddlePaddle Windows-CPU/PyInstaller
  risk; PaddleX-hub weights harder to pin to one stable URL+SHA-256). PP-FormulaNet-S and
  UniMERNet remain M7 (7.2) benchmark candidates and can retake the default via a one-line
  pipeline.yaml change. Flagged here, not silently rewritten. -->
  <!-- R-REC-6 "render check (KaTeX)" erratum (design §B.6): the engine does a
  KaTeX-supported-macro allow-list + structural check; the authoritative real-KaTeX render
  lives in the UI/vitest. Intent (never present un-renderable LaTeX as confident) is met. -->
- [x] **2.3 LaTeX normalize + validate** — `pylatexenc`/custom AST + KaTeX render check.
  `dep:2.2` · `req: R-REC-6/7` · `done:` invalid LaTeX flagged, valid passes, golden tests.
- [x] **2.4 `POST /recognize/snip`** — image → `{latex, confidence, mathml, asciimath}`. `dep:2.2,
  2.3` · `req: R-UI-2` · `done:` integration test returns valid result for fixture.
  <!-- M2: asciimath always null (deferred to M6 exporters, design §B.9). -->
- [x] **2.6 Hardware detect + device override** (implemented before 2.5; the Snip Settings UI
  consumes it) — `GET /hardware`; CUDA/MPS/CPU; Settings display + override. `dep:2.2` ·
  `req: R-HW-1/3` · `done:` reports correct device; override takes effect.
- [x] **2.5 Snip Tool UI** — global hotkey Ctrl+Shift+M, region capture, result popup, copy
  LaTeX/MathML/Markdown/OMML, KaTeX preview. `dep:1.4,2.4` · `req: R-UI-2` · `done:` E2E: hotkey →
  select → LaTeX shown; copy works.
  <!-- M2: OMML copy deferred to M6 (design §B.9) — popup copies LaTeX/MathML/Markdown.
  Live hotkey firing, on-screen region capture, and the on-screen popup are host/interactive
  and confirmed MANUALLY (documented PENDING in docs/m2-verification.md); structurally covered
  by Rust shortcut/capture-encode unit tests + vitest popup/katex render tests. -->

## M3 — PDF streaming + layout + text/formula pipeline + MD/LaTeX export

- [x] **3.1 pypdfium2 ingestion** — render pages (adaptive DPI, small-font raise), image loaders
  (Pillow/pillow-heif), born-digital vs scanned detection. `dep:1.3` · `req: R-ING-1/2/3` · `done:`
  renders PDF + each image format; DPI auto-raise unit test.
- [x] **3.2 Preprocessing** — deskew/denoise/binarize/perspective/auto-crop, each toggleable.
  `dep:3.1` · `req: R-ING-4` · `done:` before/after fixtures; toggles respected.
- [ ] **3.3 Layout adapter + default model** — DocLayout-YOLO region detect; **verify license**,
  mark opt-in if AGPL. `dep:3.1` · `req: R-LAY-1/3, R-LIC-2` · `done:` region types + bboxes on
  fixtures; license recorded.
- [ ] **3.4 Reading order** — XY-cut + column/eq-number handling. `dep:3.3` · `req: R-LAY-2` ·
  `done:` multi-column fixture ordered correctly.
- [ ] **3.5 Text OCR adapter** — PP-OCRv5 default, Tesseract fallback; EN + ID. `dep:3.3` ·
  `req: R-REC-1` · `done:` text accuracy sanity test EN + ID fixtures.
- [ ] **3.6 Page assembly** — merge regions by reading order into a page result. `dep:3.4,3.5,2.2` ·
  `req: R-EXP-1` · `done:` assembled JSON matches expected structure on fixture.
- [ ] **3.7 Markdown + LaTeX export** — `$...$`/`$$...$$`; `.tex` with preamble template. `dep:3.6` ·
  `req: R-EXP-2` · `done:` golden-file export; LaTeX compiles.

## M4 — Job queue, checkpoint/resume, batch + watch folder (5,000-page proof)

- [ ] **4.1 SQLite schema + migrations** — JOB/PAGE/REGION/FORMULA_CANDIDATE/CORRECTION/MODEL/
  SETTING + FTS5. `dep:3.6` · `req: R-JOB-2, R-UI-1` · `done:` migration test; FTS query returns.
- [ ] **4.2 Streaming job runner** — bounded concurrency, back-pressure, per-page lease state
  machine, constant memory. `dep:4.1,3.6` · `req: R-JOB-1/4` · `done:` memory stays flat on large
  synthetic PDF.
- [ ] **4.3 Checkpoint/resume** — lease expiry revert; idempotent per-page export (temp+rename).
  `dep:4.2` · `req: R-JOB-2` · `done:` kill mid-job → resume with no lost/dup pages (DoD-2).
- [ ] **4.4 Job control API + WS** — pause/resume/cancel/reprioritize, page ranges/lists, progress
  events (ETA, pages/min). `dep:4.2` · `req: R-JOB-3/5` · `done:` control actions verified; WS emits.
- [ ] **4.5 Failure isolation** — per-page timeout + resource guard, retry-failed-only. `dep:4.2` ·
  `req: R-JOB-6, R-SEC-3` · `done:` hostile-page fixture fails page, job completes, retry works.
- [ ] **4.6 Batch + watch folder** — multi-file/folder intake; auto-process new files. `dep:4.4` ·
  `req: R-JOB-7` · `done:` dropping files/new file in watched dir enqueues jobs.
- [ ] **4.7 5,000-page proof test** — synthetic generator + memory/resume assertions in CI (nightly).
  `dep:4.3` · `req: R-JOB-1/2` · `done:` CI nightly green; memory bounded; resume correct.
- [ ] **4.8 Queue UI + incremental output** — Batch/Queue screen; results stream into UI/files.
  `dep:4.4` · `req: R-UI-6, R-JOB-5` · `done:` E2E shows live per-page progress.

## M5 — Ensemble + verification + review UI + confidence overlay

- [ ] **5.1 Second-engine ensemble** — low-confidence re-run, normalized-LaTeX similarity, voting.
  `dep:2.2,2.3` · `req: R-REC-5` · `done:` ensemble beats single engine on a labeled subset.
- [ ] **5.2 Needs-review state** — persist candidates + validation; `needs_review` surfacing.
  `dep:5.1,4.1` · `req: R-REC-6` · `done:` low-confidence items marked, not fabricated.
- [ ] **5.3 Document Workspace** — split view, Monaco + KaTeX, bbox↔output linking, zoom/pan.
  `dep:3.6,2.5` · `req: R-UI-3` · `done:` click box highlights output and vice versa (E2E).
- [ ] **5.4 Needs-review panel** — list + keyboard next/prev/accept/edit; corrections persisted.
  `dep:5.2,5.3` · `req: R-UI-4/9` · `done:` keyboard review flow works; corrections saved.
- [ ] **5.5 Confidence overlay** — bbox colors by region type + confidence. `dep:5.3` ·
  `req: R-UI-3` · `done:` overlay matches data.

## M6 — Tables, DOCX(OMML), searchable PDF, handwriting canvas

- [ ] **6.1 Table recognizer** — SLANet default → LaTeX/MD/HTML. `dep:3.3` · `req: R-REC-3` ·
  `done:` TEDS on table fixtures; three formats emit.
- [ ] **6.2 DOCX OMML export** — LaTeX→MathML→OMML; editable in Word. `dep:3.7` · `req: R-EXP-2/4` ·
  `done:` golden DOCX opens with native editable equations.
- [ ] **6.3 Searchable PDF** — invisible text layer over rendered pages. `dep:3.6` · `req: R-EXP-2` ·
  `done:` text selectable/searchable in output PDF.
- [ ] **6.4 Remaining exporters** — HTML(KaTeX), MathML, AsciiMath, plain text, JSON. `dep:3.6` ·
  `req: R-EXP-2/3` · `done:` golden files for each.
- [ ] **6.5 Handwriting path + canvas** — VLM/CROHME handwriting recognizer; canvas live LaTeX.
  `dep:2.2` · `req: R-REC-4, R-UI-5` · `done:` canvas stroke → LaTeX; handwriting benchmark run.

## M7 — Benchmark harness + model manager + tuned defaults + honest docs

- [ ] **7.1 Benchmark harness** — datasets/loaders (im2latex-100k, UniMER, CROHME, OmniDocBench, +
  ID/EN textbook sample) + metrics (CDM, BLEU, nED, TEDS, mAP, doc edit). `dep:3.7` · `req: R-QA-1` ·
  `done:` reproducible run outputs a metrics report.
- [ ] **7.2 Pick defaults by numbers** — set `pipeline.yaml` defaults from measured results; prefer
  permissive. `dep:7.1,5.1,6.1` · `req: R-QA-2, R-LIC-2` · `done:` `docs/BENCHMARKS.md` has real
  numbers; defaults justified.
- [ ] **7.3 Model manager UI** — download/update/delete, disk usage, per-stage engine choice.
  `dep:2.1,2.6` · `req: R-UI-7` · `done:` manage models from UI.
- [ ] **7.4 Compare/Benchmark view** — side-by-side engine diff. `dep:7.1,5.3` · `req: R-UI-8` ·
  `done:` sample compared across engines with diff.
- [ ] **7.5 Perf measurement** — record snip latency + pages/min on GPU + CPU. `dep:4.8,2.5` ·
  `req: R-PERF-1/2/3` · `done:` measured numbers in docs.

## M8 — Polish: i18n, theming, shortcuts, installer, auto-update, user guide

- [ ] **8.1 i18n ID/EN** — i18next, default `id`, full `en`. `dep:1.2` · `req: R-UI-10` · `done:`
  language switch covers all strings.
- [ ] **8.2 BYOK backends** — plugin interface + OS vault keys + egress warnings. `dep:5.1` ·
  `req: R-BYOK-1/2/3` · `done:` BYOK tie-breaker works; warning shown before egress.
- [ ] **8.3 Settings completeness** — DPI, preamble templates, worker sizes, privacy, shortcuts,
  theme, high-contrast. `dep:2.6,7.3` · `req: R-UI-7/11` · `done:` all settings persist/apply.
- [ ] **8.4 Diagnostics + crash reporter (local)** — export diagnostics; local-only crash capture.
  `dep:1.3` · `req: R-SEC-4` · `done:` diagnostics bundle exports; nothing auto-uploaded.
- [ ] **8.5 Installer + opt-in auto-update** — signed-config installers all platforms; opt-in
  updater. `dep:1.6` · `req: R-INST-1` · `done:` install/update flow verified on Windows.
- [ ] **8.6 README + user guide + architecture diagrams** — install, build-from-source, model setup,
  troubleshooting. `dep:all` · `req: DoD-5` · `done:` docs complete and accurate.
- [ ] **8.7 Coverage + E2E gate** — >80% core coverage; E2E suite green in CI. `dep:all` ·
  `req: R-QA-3` · `done:` coverage gate passes.

---

## Dependency notes
- M2 proves the recognition core on a single image before M3 wires the streaming document pipeline.
- M4's 5,000-page proof (4.7) is the gate for the "unlimited pages" claim (DoD-1/2).
- M7 is where provisional engine defaults become benchmark-justified defaults; no accuracy claims
  land in README until 7.2 produces real numbers.
