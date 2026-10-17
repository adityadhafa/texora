# Texora M2 — Single-image formula OCR: Implementation Plan

Source of truth for HOW: `.agents/tasks/m2-design.md` (APPROVED v4). Task list + `done:` criteria:
`.kiro/specs/texora/tasks.md` §M2. This plan sequences that design faithfully; it does not redesign.

Worktree (pass this absolute path to every read/git/build command; the default cwd is the MAIN
workspace, NOT the worktree): `c:\data\kucing\texora\.worktrees\m2-formula-ocr`

Prepend this PATH export before EVERY shell command:

```bash
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

Engine commands use the venv interpreter `engine/.venv/Scripts/python.exe -m <tool>` run from the
`engine/` directory. Frontend commands run from the worktree root (`pnpm --filter desktop …`). Rust
commands run from `apps/desktop/src-tauri` inside a `cmd.exe` session that first `call`s
`vcvars64.bat` (MSVC env), per `docs/m1-verification.md` §1.4.

Standing rules honored throughout: no mocked OCR in production paths; pin every dep and verify
against official docs before use; add a `docs/LICENSES.md` row in the SAME change that adds a dep or
model; SQLite only through `db/`; engine adapters implement the `recognizers/base.py` Protocol and
register in the factory; UI reaches the engine only through the single typed `engineClient`; all
user-facing strings via i18next (`id` default + `en`); loopback-only + bearer token on every
non-health route; fail per-item gracefully. Append real command output to a new
`docs/m2-verification.md` as tasks complete (mirror `docs/m1-verification.md` structure), and record
honest "pending (host/interactive)" items there rather than claiming them passed.

---

## Phase 0 — dependency pins + license rows (do first; touched by every later task)

- [ ] 1. Pin and install the new engine runtime deps, promoting `httpx` to runtime (design §B.2).
      Verify each exact version exists on PyPI before pinning; if a listed patch is unavailable, pick
      the nearest patch in the same minor and record the real version. Move `httpx==0.28.1` from
      `requirements-dev.txt` into `requirements.txt`; add `pix2tex==0.1.4`, `torch==2.3.1+cpu` (from
      the PyTorch CPU wheel index — document the `--index-url`/`--extra-index-url` used),
      `pillow==10.4.0`, `pylatexenc==2.10`, `latex2mathml==3.77.0`. Mirror the same deps into
      `engine/pyproject.toml` (`[project].dependencies`) and move `httpx` out of the `dev` extra.
      Install into `engine/.venv`.
      Files: `engine/requirements.txt`, `engine/requirements-dev.txt`, `engine/pyproject.toml`,
      `docs/LICENSES.md` (move `httpx` dev→runtime; add rows for `pix2tex` MIT, `torch` BSD-3-Clause,
      `pillow` HPND, `pylatexenc` MIT, `latex2mathml` MIT — all with the real installed versions).
      Verify: `engine/.venv/Scripts/python.exe -m pip install -r engine/requirements.txt -r engine/requirements-dev.txt`
      succeeds; `engine/.venv/Scripts/python.exe -c "import pix2tex, torch, PIL, pylatexenc, latex2mathml, httpx; print('ok')"`
      prints `ok`; `black --check` / `ruff` still clean on unchanged files.

- [ ] 2. Add the frontend deps (design §B.2): `katex@0.16.11` and
      `@tauri-apps/plugin-global-shortcut` (the `2.x` matching the 2.12 CLI line — verify the exact
      version on npm). Add their `docs/LICENSES.md` rows (`katex` MIT; plugin Apache-2.0 OR MIT).
      Files: `apps/desktop/package.json`, `pnpm-lock.yaml`, `docs/LICENSES.md`.
      Verify: `pnpm install` resolves the lockfile; `pnpm --filter desktop build` still passes
      (typecheck + vite) with no new imports yet.

- [ ] 3. Add the new Rust crate deps (design §B.10): `tauri-plugin-global-shortcut` (2.x matching the
      Tauri 2.12 line) and `xcap` (Apache-2.0); `ureq` already present. Pin exact versions verified
      on crates.io; add their `docs/LICENSES.md` rows.
      Files: `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/Cargo.lock`,
      `docs/LICENSES.md`.
      Verify (vcvars64 loaded): `cargo fetch` resolves; `cargo build` compiles the unchanged crate
      with the new deps present.

---

## Task 2.1 — Model registry + downloader (R-INST-2/3/4; AC-1, AC-2, AC-9)

Design: §B.5, §B.3 (pin-on-first-fetch), §B.2b (progress). Depends on Phase 0 item 1.

- [ ] 4. Create the SQLite `db/` layer for M2's minimal schema (design §B.5, structure.md: SQLite
      only through `db/`). `schema.py` opens the DB in WAL mode and creates the `MODEL` and `SETTING`
      tables with a tiny migration guard; `models_dao.py` and `settings_dao.py` expose typed
      get/upsert helpers (no raw SQL in callers). Add `db_path`, `models_dir`, `device` to
      `Settings`.
      Files: `engine/texora_engine/db/schema.py`, `engine/texora_engine/db/models_dao.py`,
      `engine/texora_engine/db/settings_dao.py`, `engine/texora_engine/db/__init__.py`,
      `engine/texora_engine/settings.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_db.py -q` — a new test creates a
      temp DB, upserts + reads a MODEL and a SETTING row, and asserts WAL mode (`PRAGMA
      journal_mode` == `wal`).

- [ ] 5. Create the model registry types + pinned catalog (design §B.5, §B.3). `registry.py` defines
      the Pydantic `ModelSpec` (`id`, `version`, `files: list[ModelFile]`, `license`, `target_dir`)
      and `ModelFile` (`name`, `url`, `sha256`, `size`), plus `ModelSpec.file_path(name)`.
      `catalog.py` holds the single pinned pix2tex spec. **Adoption step (NEVER invent a hash):**
      confirm against the pinned pix2tex release the exact PyPI version, the exact GitHub release
      tag, each asset's exact filename and its direct, non-redirecting, immutable per-tag URL; then
      fetch each asset once, compute its real SHA-256, and bake the real values into `catalog.py`. If
      the real shape differs from the design's assumption (`weights.pth` / `image_resizer.pth` at tag
      `v0.0.1`), use the real filenames/URLs and update `ModelFile`/`file_path(...)` lookups to match.
      Files: `engine/texora_engine/models/registry.py`, `engine/texora_engine/models/catalog.py`,
      `engine/texora_engine/models/__init__.py`, `docs/m2-verification.md` (record the confirmed
      version/tag/URLs/SHA-256 and the pin-on-first-fetch honesty note).
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_registry.py -q` — a test loads the
      catalog, asserts the pix2tex spec validates and `file_path` composes the expected target path.

- [ ] 6. Implement the checksum-verifying downloader (design §B.5, §B.2b). `downloader.py` streams
      each file via `httpx.stream("GET", url)` to `<target_dir>/.incoming/<name>.part`, hashing with
      `hashlib.sha256` while writing, enforcing a connect/read timeout and a max-size guard, and
      emitting `ModelProgress` (define it in `models/progress.py` per §B.2b:
      `ModelDownloadState`/`ModelFileProgress`/`ModelProgress`). On completion compare digest to the
      pinned `sha256`: **mismatch → delete the part, raise `ChecksumMismatch`, mark the row `corrupt`,
      surface an error, allow retry**; match → atomic `os.replace` into place, mark `ready`.
      `store.py` persists MODEL rows via `db/` and exposes `require_ready(id)` raising typed
      `ModelNotReady`.
      Files: `engine/texora_engine/models/downloader.py`, `engine/texora_engine/models/progress.py`,
      `engine/texora_engine/models/store.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_downloader.py -q` — against a
      local fake HTTP server (not mocking OCR), one test downloads a small fixture and promotes it to
      `ready`; a **bad-hash** test asserts the `.part` is deleted, the row is `corrupt`, and
      `ChecksumMismatch` is raised (this is the task 2.1 `done:` bad-hash test, AC-1).

- [ ] 7. Implement offline-bundle import (design §B.5, FR-1, AC-2). `bundle.py` imports model files
      from a local dir/zip with **no network access**, verifying each file against the same pinned
      SHA-256 via the shared verify routine before promoting to `ready`; raises `BundleIncomplete`
      (missing files) or `ChecksumMismatch`.
      Files: `engine/texora_engine/models/bundle.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_bundle.py -q` — a test with a
      local fixture bundle promotes to `ready` with zero network calls (networking stubbed to fail so
      any accidental egress fails loudly); a missing-file and a bad-hash bundle are rejected.

---

## Task 2.2 — FormulaRecognizer adapter + default engine (R-REC-2/8, R-HW-2; AC-3, AC-3a, AC-4)

Design: §B.4 (Protocol + factory), §B.3 (adapter suppression). Depends on 2.1.

- [ ] 8. Define the stable Protocol + shared types (design §B.4). `recognizers/base.py` declares the
      `RecognitionStatus` StrEnum (`ok`/`needs_review`/`failed` — the single source of truth shared by
      the validator and the API), `RegionContext` (with the documented `is_display` passthrough and
      `device`), `FormulaResult` (Pydantic, never a fabricated guess), and the `@runtime_checkable`
      `FormulaRecognizer` Protocol (`id: str`, `model_ids: tuple[str, ...]`,
      `recognize(image, ctx) -> FormulaResult`).
      Files: `engine/texora_engine/recognizers/base.py`, `engine/texora_engine/recognizers/__init__.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_recognizers_base.py -q` — a test
      asserts `RecognitionStatus` values and that `FormulaResult` enforces `0.0 ≤ confidence ≤ 1.0`.

- [ ] 9. Add the typed pipeline config (design §B.4). `pipeline_config.py` defines
      `PipelineConfig`/`Stages`/`RecognizeStage` (recognize is a MAP of sub-stages) and
      `load_pipeline_config()` parsing `pipeline.yaml` via Pydantic. Replace the ENTIRE commented
      placeholder body of `pipeline.yaml` (every `#`-commented line, including `# version: 1`) with
      the real minimal config setting `stages.recognize.formula: pix2tex`, keeping the
      permissive-first comment. Do not leave the old commented lines beside the new block.
      Files: `engine/texora_engine/pipeline_config.py`, `pipeline.yaml`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_pipeline_config.py -q` — loads
      `pipeline.yaml`, asserts `stages.recognize.formula == "pix2tex"`.

- [ ] 10. Implement the pix2tex adapter (design §B.3, §B.4) — REAL inference, local-weights-only.
      `formula_pix2tex.py` sets `id = "pix2tex"`, `model_ids = ("pix2tex",)`, and constructs pix2tex
      pointed ONLY at registry-resolved local checkpoint/resizer paths so pix2tex's built-in
      downloader is NEVER triggered (raise `ModelNotReady` if a weight file is absent). `recognize`
      is pure, catches its own inference errors → `status=FAILED` with `detail` (never raises).
      Confidence: probe the pinned pix2tex for per-token scores and record the outcome in
      `docs/m2-verification.md`; if reachable, `confidence = exp(mean token logprob)`,
      `confidence_kind="token_logprob"`; if not, `confidence=0.0`, `confidence_kind="unavailable"` with
      a `detail` — NEVER fabricate a number.
      **Host gate:** this downloads the model (user-approved) and runs real inference on this CPU
      host. If pix2tex genuinely cannot run on this host, STOP and send a warning (pause) — never mock
      or fake. Commit a small real formula-image fixture under `engine/tests/fixtures/`.
      Files: `engine/texora_engine/recognizers/formula_pix2tex.py`,
      `engine/tests/fixtures/<formula>.png`, `docs/m2-verification.md`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_formula_pix2tex.py -q` — the
      real-model fixture test asserts a non-empty LaTeX string via the production path (AC-4;
      `pytest.skip("pix2tex weights absent; run model prefetch")` with an explicit reason if weights
      are absent — never mocked). A second test asserts constructing the adapter with weights absent
      raises `ModelNotReady` and makes NO network call (networking stubbed to fail).

- [ ] 11. Implement the factory + typed errors (design §B.4). `factory.py` holds `_REGISTRY` keyed by
      adapter `id`, `UnknownEngineError` and `FormulaStageNotConfigured`, and
      `build_formula_recognizer(settings, model_registry)` that reads
      `load_pipeline_config().stages.recognize.formula`, raises `FormulaStageNotConfigured` when None,
      `UnknownEngineError(stage_id, known)` (logged, never a bare `KeyError`) when unregistered,
      resolves weights via `ctor.model_ids[0]` → `require_ready`, and passes explicit local weight
      paths.
      Files: `engine/texora_engine/recognizers/factory.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_factory.py -q` — asserts the
      pix2tex ctor is registered and `isinstance(adapter, FormulaRecognizer)` (AC-3); an unknown id in
      `pipeline.yaml` raises `UnknownEngineError` carrying the offending + known ids (AC-3a); a
      None/absent key raises `FormulaStageNotConfigured`.

---

## Task 2.3 — LaTeX normalize + validate (R-REC-6/7; AC-5)

Design: §B.6. Depends on 2.2 (uses `RecognitionStatus`).

- [ ] 12. Generate the KaTeX allow-list (design §B.6). `scripts/gen_katex_allowlist.py` derives the
      supported command/environment names from the pinned `katex@0.16.11`: primary input = the
      installed package's public function registry (`katex.mjs`); verified fallback = the vendored
      pinned katex SOURCE tarball (devDependency-only; record its SHA-256). Confirm the real input
      path against the installed katex and record it in `docs/m2-verification.md`. The script writes
      `engine/texora_engine/ensemble/katex_allowlist.json` with a header recording the katex version
      it was generated from.
      Files: `scripts/gen_katex_allowlist.py`,
      `engine/texora_engine/ensemble/katex_allowlist.json`, `docs/m2-verification.md`.
      Verify: `node scripts/gen_katex_allowlist.py`-equivalent run (document the exact invocation)
      regenerates the JSON; then
      `engine/.venv/Scripts/python.exe -m pytest tests/test_katex_allowlist.py -q` asserts the JSON's
      recorded version equals the `katex` pin in `apps/desktop/package.json`.

- [ ] 13. Implement validate + normalize (design §B.6). `ensemble/latex.py` exposes
      `validate_and_normalize(latex) -> tuple[str, RecognitionStatus]`: parse with `pylatexenc`'s
      `LatexWalker`; structurally check balanced `{}`, matched `\left`/`\right`, matched
      `\begin{env}`/`\end{env}`; check every command/env against the loaded allow-list (outside the
      set → `needs_review`; parse/structure failure → `failed`); then normalize (canonical `\frac`,
      spacing, `\operatorname`/`\mathrm`) such that the normalized output still validates.
      Files: `engine/texora_engine/ensemble/latex.py`, `engine/texora_engine/ensemble/__init__.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_latex.py -q` — golden tests:
      invalid cases (unbalanced braces, mismatched `\left\right`, bad env, out-of-allow-list macro)
      flagged `needs_review`/`failed`; valid cases pass; each normalization rule's output still
      validates (AC-5 engine side).

- [ ] 14. Implement MathML conversion (design §B.9). `export/mathml.py` converts a validated LaTeX
      string to MathML via `latex2mathml`. No `asciimath.py`, no OMML/XSLT in M2 (both deferred to
      M6).
      Files: `engine/texora_engine/export/mathml.py`, `engine/texora_engine/export/__init__.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_mathml.py -q` — a golden test
      asserts the fixture LaTeX converts to the expected MathML.

---

## Task 2.4 — POST /recognize/snip (R-UI-2, R-SEC-2/3; AC-6)

Design: §B.7. Depends on 2.2, 2.3.

- [ ] 15. Add snip config knobs to `Settings` (design §B.7): `max_snip_bytes`, `max_snip_pixels`,
      `max_snip_edge`, `snip_timeout_s`, `snip_concurrency` (default 1). Set Pillow's
      `Image.MAX_IMAGE_PIXELS` backstop at engine startup.
      Files: `engine/texora_engine/settings.py`, `engine/texora_engine/app.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_settings.py -q` — asserts the new
      fields default as designed and accept env overrides.

- [ ] 16. Implement the `recognize` router (design §B.7, §B.9). `api/recognize.py` defines
      `SnipRequest` (`image_base64`, `is_display`) and `SnipResponse` (`latex`, `confidence`,
      `confidence_kind`, `status`, `validation`, `mathml`, `asciimath=None` in M2, `detail`). Flow:
      decode/validate image (base64 valid, ≤ `max_snip_bytes`; after `Image.open`, reject
      `width*height > max_snip_pixels` or edge `> max_snip_edge` → **422**; wrap every Pillow decode so
      `UnidentifiedImageError`/`DecompressionBombError`/any decode error → **422**, never 500) →
      cached-singleton `build_formula_recognizer()` → run `recognize` in a `ThreadPoolExecutor(max_workers=1)`
      under `asyncio.wait_for(SNIP_TIMEOUT_S)` (timeout → 200 with `status=failed`,
      `detail="recognition timed out"`) → `validate_and_normalize` (downgrade `status` to
      `needs_review`/`failed` on failure) → `latex2mathml` → assemble `SnipResponse`. Mount on
      `protected_router`. Map `UnknownEngineError`/`FormulaStageNotConfigured` → clear 500.
      Files: `engine/texora_engine/api/recognize.py`, `engine/texora_engine/app.py` (include router),
      `engine/texora_engine/api/__init__.py`.
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_recognize_api.py -q` — integration
      (TestClient): no/invalid token → 401; valid token + fixture image → 200 with a valid
      `{latex, confidence, confidence_kind, status, validation, mathml}` and `asciimath == null`
      (AC-6, asserting whichever confidence branch the pinned pix2tex yields, recorded in
      `docs/m2-verification.md`); an oversized decoded image → 422; malformed base64 → 422.

---

## Task 2.6 — Hardware detect + device override (R-HW-1/3; AC-7)

Design: §B.7 (hardware routes). Depends on 2.2. (Planned before 2.5 because the Snip UI's Settings
section consumes `getHardware`/`setDevice`.)

- [ ] 17. Implement the `hardware` router (design §B.7). `api/hardware.py` defines
      `Device`/`HardwareResponse`. `GET /hardware` reports devices from `torch.cuda.is_available()` /
      `torch.backends.mps.is_available()` else CPU, plus the current selection read from the `SETTING`
      table. `POST /hardware/device` validates the device is in the detected set (**422** otherwise),
      persists it via `settings_dao`, and the recognizer factory reads it on the next build. Both on
      `protected_router`.
      Files: `engine/texora_engine/api/hardware.py`, `engine/texora_engine/app.py` (include router).
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_hardware_api.py -q` — with torch
      availability monkeypatched: `GET /hardware` returns the detected set + selection; a valid
      override changes the selection reported on the next call (AC-7); an unknown device → 422; no
      token → 401.

- [ ] 18. Implement the `models` status/download router (design §B.2a/§B.2b). `api/models.py`:
      `GET /models/{id}` returns the current `ModelProgress`; a download trigger starts the
      server-side download as a background task and returns the initial `downloading` status
      immediately (non-blocking). On `protected_router`.
      Files: `engine/texora_engine/api/models.py`, `engine/texora_engine/app.py` (include router).
      Verify: `engine/.venv/Scripts/python.exe -m pytest tests/test_models_api.py -q` — `GET
      /models/{id}` returns a valid `ModelProgress`; the download trigger returns immediately with
      `downloading`; no token → 401.

---

## JS→engine transport + Rust capture/hotkey (design §B.2a, §B.2b, §B.10) — the HIGH-1 seam

Depends on 2.4, 2.6 (the engine routes the proxy forwards to exist). Rust-only; needs vcvars64.

- [ ] 19. Store port+token in the supervisor and add the authenticated proxy helper (design §B.2a).
      Extend `SupervisorState` to hold the live `port` + session `token`; add
      `engine_request(method, path, body) -> Result<Bytes, Error>` building a `ureq` request against
      the live port with `Authorization: Bearer <token>`, returning a typed "engine not ready" error
      when no healthy port exists. Add the model-download poller (§B.2b): an in-flight id map on
      `SupervisorState`, a 500 ms `GET /models/{id}` poll emitting `engine://model-progress`, stopping
      on a terminal state (`ready`/`corrupt`/`error`).
      Files: `apps/desktop/src-tauri/src/supervisor.rs`.
      Verify (vcvars64): `cargo test` in `apps/desktop/src-tauri` — a unit test asserts
      `engine_request` builds the correct URL + bearer header against a stub port and returns the
      not-ready error when no port is set (all existing supervisor tests still pass).

- [ ] 20. Add the proxy commands + shortcut + capture (design §B.2a, §B.10). New `snip.rs` registers
      Ctrl+Shift+M via `tauri-plugin-global-shortcut`, opens a transparent overlay for region select,
      captures the monitor rect via `xcap`, crops, PNG-encodes, and emits `engine://snip-captured`
      (base64). `lib.rs` registers the global-shortcut plugin and the new thin commands
      (`recognize_snip`, `get_hardware`, `set_device`, `model_status`, `model_download`) in
      `generate_handler!`, each forwarding via `engine_request` (`model_download` returns immediately,
      then registers the poller). Add the command `allow` entries + global-shortcut
      register/unregister scope + overlay window scope to `capabilities/default.json` (NO new network
      capability — HTTP stays in Rust).
      Files: `apps/desktop/src-tauri/src/snip.rs`, `apps/desktop/src-tauri/src/lib.rs`,
      `apps/desktop/src-tauri/capabilities/default.json`.
      Verify (vcvars64): `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`,
      `cargo test` — unit tests cover shortcut registration and `xcap`-encode of a known fixture
      buffer to PNG; the proxy commands' not-ready error path. (Live hotkey/capture is
      host/interactive — document pending in `docs/m2-verification.md`, never claimed passed.)

---

## Task 2.5 — Snip Tool UI (R-UI-2/10/11; AC-8, host-pending for live hotkey/capture/popup)

Design: §B.11, §B.2a/§B.2b. Depends on the transport above + 2.4/2.6.

- [ ] 21. Extend `engineClient.ts` with the typed wrappers (design §B.11) — it stays the ONLY module
      importing `invoke`/`listen` and makes NO `fetch`. Add `recognizeSnip(pngBase64, isDisplay)`,
      `getHardware()`, `setDevice(device)`, `modelStatus(id)`, `modelDownload(id)` as `invoke`
      wrappers and `subscribeSnipCaptured(cb)`, `subscribeModelProgress(cb)` as `listen` wrappers.
      Add the shared TS types mirroring the engine Pydantic models exactly: `RecognitionStatus`
      (`'ok' | 'needs_review' | 'failed'`), `SnipResult`, `Hardware`/`Device`, `confidenceKind`, and
      the `ModelProgress`/`ModelFileProgress`/`ModelDownloadState` mirror (§B.2b).
      Files: `apps/desktop/src/engineClient.ts`.
      Verify: `pnpm --filter desktop test -- --run src/engineClient.test.ts` — tests assert each
      wrapper invokes the right command / listens on the right event (bridge mocked); a grep test (as
      in M1) confirms `engineClient.ts` is the sole production importer of `invoke`/`listen` and no
      `fetch` is used.

- [ ] 22. Add the M2 i18n keys with id/en parity (design §B.11). Add exactly the `snip.*` and
      `hardware.*` keys enumerated in §B.11 (no `snip.copyOmml` — OMML is M6) to BOTH
      `locales/id.json` (default) and `locales/en.json`. Add `locales.test.ts` asserting the
      recursively-flattened key sets of id.json and en.json are identical.
      Files: `apps/desktop/src/locales/id.json`, `apps/desktop/src/locales/en.json`,
      `apps/desktop/src/locales.test.ts`.
      Verify: `pnpm --filter desktop test -- --run src/locales.test.ts` — the parity test passes.

- [ ] 23. Build the Snip popup + Settings/hardware UI (design §B.11). `SnipPopup.tsx` shows the LaTeX
      (read-only code box), a live **KaTeX** preview (the authoritative render), the
      confidence/validation badge (colored by `ok|needs_review|failed`; renders "confidence
      unavailable" when `confidenceKind === 'unavailable'`), and LaTeX/MathML/Markdown copy buttons
      (Markdown wraps `$$…$$`/`$…$` by `isDisplay`); keyboard-first (Esc close, Enter copy LaTeX,
      focus trap, ARIA live region); a `needs_review`/`failed` result renders a clear "could not
      recognize" state, never fabricated LaTeX. `SettingsHardware.tsx` renders `getHardware()` + a
      device `<select>` calling `setDevice` + the "CPU slower" note. All strings via i18next; all
      engine calls via `engineClient`. Wire capture→recognize via `subscribeSnipCaptured` →
      `recognizeSnip`.
      Files: `apps/desktop/src/SnipPopup.tsx`, `apps/desktop/src/SnipPopup.test.tsx`,
      `apps/desktop/src/SettingsHardware.tsx`, `apps/desktop/src/SettingsHardware.test.tsx`,
      `apps/desktop/src/katexRender.test.ts`, `apps/desktop/src/App.tsx` (mount).
      Verify: `pnpm --filter desktop lint`, `pnpm --filter desktop test -- --run`,
      `pnpm --filter desktop build` — vitest asserts the popup renders LaTeX + copy buttons from
      i18next, the `needs_review` review state, the "confidence unavailable" rendering, and the
      real-`katex` render over the fixture + golden LaTeX (no `ParseError` on valid, `ParseError` on
      invalid — AC-5 UI side + AC-8). Live hotkey/region-capture/on-screen popup are host/interactive
      → documented pending in `docs/m2-verification.md`, never claimed passed.

---

## Phase 9 — cross-cutting verification + honest docs (AC-9, AC-10, B.13)

- [ ] 24. Run the full gate and finalize docs. Engine (from `engine/`, venv python):
      `ruff check .`, `black --check . --line-length 100`, `mypy texora_engine`, `pytest -q`.
      Frontend (root): `pnpm --filter desktop lint`, `pnpm --filter desktop test -- --run`,
      `pnpm --filter desktop build`. Rust (vcvars64, `apps/desktop/src-tauri`): `cargo fmt --check`,
      `cargo clippy --all-targets -- -D warnings`, `cargo test`. Confirm every new dep + the pix2tex
      model has a `docs/LICENSES.md` row (AC-9). Run the benchmark smoke per steering now that the
      real model is fetched (OCR-affecting completion gate). Finish `docs/m2-verification.md` with
      real command output, the confidence-branch outcome, the katex allow-list input path, and the
      host/interactive pending items; tick M2 tasks in `tasks.md`; update `docs/PROGRESS.md`. Clean up
      any temp files.
      Files: `docs/m2-verification.md`, `docs/LICENSES.md`, `.kiro/specs/texora/tasks.md`,
      `docs/PROGRESS.md`.
      Verify: all three stacks' commands above pass (or are honestly recorded pending for
      host/interactive items); no stray temp files remain (`git status` clean except intended
      changes).

---

## Done-criterion coverage map

- 2.1 `done:` (corrupt file rejected, bad-hash test) → item 6 (AC-1); offline import → item 7 (AC-2).
- 2.2 `done:` (real image→LaTeX, no mocks) → item 10 (AC-4); Protocol+factory → items 8, 11 (AC-3/3a).
- 2.3 `done:` (invalid flagged, valid passes, golden) → items 12–13 engine (AC-5) + item 23 real-katex.
- 2.4 `done:` (integration returns valid result) → item 16 (AC-6).
- 2.5 `done:` (hotkey→select→LaTeX shown; copy works) → items 21–23; live hotkey/capture/popup are
  host/interactive, documented pending in `docs/m2-verification.md` (never claimed passed).
- 2.6 `done:` (reports device; override takes effect) → item 17 (AC-7).
- JS→engine transport (HIGH-1 seam) → items 19–20 (AC-8 Rust side) + item 21 (AC-8 client side).
- AC-9 (license rows) → Phase 0 + item 24; AC-10 (all gates green) → item 24.
