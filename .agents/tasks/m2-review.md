# M2 single-image formula OCR — final-gate semantic review

Milestone M2 wires Texora's first real recognition path: a pix2tex (LaTeX-OCR) formula
recognizer behind a stable `FormulaRecognizer` Protocol, a checksum-verifying model
downloader with an offline-bundle importer, a bearer-protected `POST /recognize/snip`
(plus `/hardware` and `/models`) FastAPI surface, a Rust snip hotkey + screen-capture path,
and a single typed TS engine client that reaches the engine only through authenticated Rust
proxy commands. The approach keeps all OCR/business logic in the engine, the UI free of any
specific model, and the port/bearer token entirely in Rust. The previously-RED Tauri build
(cargo exit 101) was root-caused to a missing PyInstaller sidecar and fixed.

Watch for: nothing blocking. The capture path grabs the whole primary monitor rather than a
selected region (deliberate, documented M2 scope — LOW), and confidence is honestly
`unavailable` on the pinned pix2tex rather than a fabricated number (correct per the honesty
rules). Host/interactive items (hotkey firing, live capture, on-screen popup, CPU latency)
are recorded as PENDING MANUAL and never claimed passed.

**Verdict**: APPROVED

## High-level view

Builds and suites are green on real recorded output. Rust: `cargo build`/`clippy -D
warnings`/`fmt --check`/`test` (14 passed) under a vcvars-loaded shell; the earlier exit-101
was the `externalBin` sidecar not existing because PyInstaller's in-place Windows PE
timestamp/checksum rewrite fails on the ~570 MB onefile (`OSError 22`). The fix in
`scripts/build_engine.py` finishes that fix-up via temp-file + atomic replace only when the
onefile already exists, and treats any other failure or a missing binary as a hard error —
no unverified binary ships. Engine: ruff/black (line-length 100)/mypy (32 files)/pytest (59)
all green. Frontend: lint/test (33)/build green.

The default model is permissive (pix2tex code MIT; weights MIT) with a `docs/LICENSES.md`
row, and no Surya/GPL/non-commercial default appears. `catalog.py` pins real SHA-256 values
that were computed on this host and cross-checked against the immutable upstream release
assets, with the honest "our hash of the upstream asset, not a vendor attestation" caveat in
both the catalog docstring and LICENSES.md. The bad-hash downloader test
(`test_bad_hash_is_rejected`) exists and asserts `ChecksumMismatch`, `.part` deletion, and
non-promotion.

No fabricated OCR anywhere in production paths: the recognizer returns typed `FormulaResult`,
maps every inference failure to `status=FAILED` with a `detail`, and reports
`confidence=0.0`/`confidence_kind=unavailable` because the pinned pix2tex exposes no usable
per-token scores. Real CPU inference on the committed fixture produces a KaTeX-valid `\frac`
string through the production adapter; the real-model test skips with a reason (never mocks)
when weights are absent.

Security posture holds: every non-health router carries a router-level `require_token`
dependency using constant-time comparison; the engine binds `127.0.0.1` by default; the TS
client is the sole production importer of `invoke`/`listen` and makes no `fetch`; and JS→engine
traffic flows only through Rust proxy commands that keep the port and bearer token in Rust.
i18n `id`/`en` key sets are identical (33 each).

<details>
<summary>Issues (1)</summary>

1. **Whole-monitor capture vs region select (LOW)** — `snip.rs::capture_primary_png_base64`
   grabs the entire primary monitor; on-screen region selection is deferred. This is a
   documented, deliberate M2 scope choice (comment in `snip.rs` + PENDING MANUAL in
   `docs/m2-verification.md`), not a defect. No action required for M2; track region-select
   UX as a host/interactive follow-up.

</details>

<details>
<summary>Details</summary>

### Build/suite evidence (read, not re-run)

Per the step contract I did not re-run the full suites; I read the diff plus the freshly
recorded output in `docs/m2-verification.md` (Convergence re-run section, dated 2026-10-18,
marked authoritative). Rust section B records `cargo build` Finished, `cargo fmt --check`
clean (after one `cargo fmt` applied to `snip.rs`, committed as `fa2670e`), `cargo clippy
--all-targets -- -D warnings` exit 0, and `cargo test` 14 passed/0 failed. Engine section C
records ruff "All checks passed!", black "50 files would be left unchanged" at line-length
100, mypy "no issues found in 32 source files", pytest "59 passed". Frontend section E
records lint clean, vitest 33 passed across 8 files, and a successful build. These are
concrete command transcripts, not "looks right" claims, so the evidence requirement is met.

### Sidecar freeze fix — the previously-RED cargo turned green honestly

The root cause is diagnosed, not guessed: PyInstaller rewrites the Windows PE build timestamp
and checksum in place, which fails with `OSError(22)` on the large `--onefile` because
`pefile` had just memory-mapped the same path. `scripts/build_engine.py` now runs PyInstaller
with `check=False` and, only when the expected onefile already exists on Windows, finishes the
cosmetic timestamp/checksum fix-up via temp-file + `os.replace`. Any other non-zero exit, or a
missing binary, remains a hard error — so the green cargo build rests on a fully assembled,
functional sidecar (the recorded `--help` invocation confirms it runs), not on a skipped step.
The binary is gitignored (`git check-ignore` confirmed), so no large weight/binary is committed.

### Recognizer Protocol + honest confidence

`recognizers/base.py` defines a `@runtime_checkable` `FormulaRecognizer` Protocol with a
stable `id`, declared `model_ids`, and a pure `recognize(...)` returning a Pydantic
`FormulaResult` (not a bare dict) that constrains `0 ≤ confidence ≤ 1` and carries an
explicit `RecognitionStatus` and `ConfidenceKind`. `Pix2TexFormulaRecognizer` implements it,
points pix2tex at registry-resolved local weights only (pix2tex's built-in downloader is
never triggered), and catches every inference error to return `status=FAILED` with a
`detail` rather than raising — satisfying the "never crash a job on one bad region" rule at
the adapter level.

The confidence decision is the honest one: the probe recorded in the verification doc found
that pinned pix2tex 0.1.4 discards sampling probabilities, so the adapter reports
`confidence=0.0` + `confidence_kind=unavailable` + a `detail`, and the UI renders a
"confidence unavailable" state (asserted in `SnipPopup.test.tsx`). No number is fabricated.
`recognize.py` further downgrades any result whose LaTeX fails KaTeX validation and never
emits un-validated LaTeX as confident; a timeout returns 200 `status=failed`, and decode/size
failures return typed 422s rather than 500s.

### Model pinning + corrupt-file rejection

`catalog.py` pins both pix2tex assets (`weights.pth`, `image_resizer.pth`) at release tag
`v0.0.1` with real SHA-256 values. The verification doc section D shows those digests were
computed on this host and the upstream per-tag URLs returned 200 with matching content
lengths, so these are genuine computed hashes, not placeholders. The pin-on-first-fetch
caveat ("our hash of the upstream asset, not vendor-signed") is recorded in the catalog
docstring, `docs/m2-verification.md`, and the `docs/LICENSES.md` ML-models row.

`downloader.py` streams to a `.incoming/<name>.part`, hashes while writing, enforces a 1 GiB
ceiling, and on a digest mismatch deletes the `.part` and raises `ChecksumMismatch` before any
atomic promote. `test_downloader.py::test_bad_hash_is_rejected` drives this against a local
HTTP server and asserts the mismatch raise, the absent final file, and the deleted `.part`.
The good-hash companion asserts promotion + a terminal `ready` event. This is download/verify
plumbing against a local server, not mocked OCR.

### Real inference, no mocks

`test_formula_pix2tex.py::test_real_model_recognizes_fixture` constructs the real adapter
against prefetched weights and runs it on the committed fixture
`engine/tests/fixtures/formula_frac_ab.png` (confirmed tracked by git) through the production
`recognize(...)` path, asserting a non-empty LaTeX string and the honest unavailable
confidence. When weights are absent it `pytest.skip`s with a reason — it never substitutes a
fabricated output. The construct-without-weights test monkeypatches `socket.connect` to fail,
proving no network egress on the not-ready path. `test_recognize_api.py` exercises the same
through the HTTP route (401 without token, 422 on bad/oversized input, real fixture → 200 with
the documented confidence branch).

### Security + transport invariants

`security.py` compares the bearer with `secrets.compare_digest` (constant time) and 401s on
any missing/mismatched/non-Bearer credential. Every non-health router
(`protected_router`, `recognize_router`, `hardware_router`, `models_router`) attaches
`Depends(require_token)` at the router level in `app.py`, while only `health_router` is open.
The CLI entrypoint defaults `--host` to `127.0.0.1`, so there is no non-loopback exposure.

On the shell side, `lib.rs` exposes only thin proxy commands
(`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`) that call
`supervisor::engine_request`, which reads the port and token from `SupervisorState` and adds
`Authorization: Bearer <token>` — the webview never receives either. A direct worktree grep
confirms `engineClient.ts` is the only production module importing `@tauri-apps/api` and that
no production module calls `fetch(`, matching the passing `bridgeInvariant.test.ts`. The Rust
`engine_request` unit tests prove not-ready-without-port, not-ready-without-token, and a
bearer-carrying request reaching a stub server.

### i18n parity

A direct flattened-key comparison of `locales/en.json` and `locales/id.json` yields 33 keys
each with an empty symmetric difference, matching the `locales.test.ts` assertion. `id` is the
default with `en` provided, per the product rules.

### Honest scope deferrals

The M2 tasks are marked done with inline comments recording the truthful deferrals: `asciimath`
is always null until M6 exporters; OMML copy is M6; and live hotkey firing, on-screen region
capture, the on-screen popup, and user-perceived CPU latency are PENDING MANUAL in
`docs/m2-verification.md`, structurally covered by Rust shortcut/capture-encode unit tests and
vitest popup/katex tests but never asserted as passed. The pix2tex-as-default deviation from
the spec's PP-FormulaNet name is flagged as a spec erratum against the approved design, and
pix2tex remains permissive-first.

### New dependency license rows

`docs/LICENSES.md` carries rows for every dependency M2 actually added or promoted: `httpx`
(dev→runtime), `pefile` (build-time PE fix-up), the pix2tex package and its full transitive
pin set (torch/torchvision+cpu, transformers, tokenizers, numpy, opencv-headless,
albumentations/albucore, timm, x-transformers, einops, entmax, munch, pandas, scipy, PyYAML),
the frontend `katex`/`@types/katex`/global-shortcut JS plugin, and the Rust
`base64`/`xcap`/`tauri-plugin-global-shortcut` plus transitive `image`/`global-hotkey`. The
pix2tex weights appear as a dedicated ML-models row (MIT, pinned tag, pin-on-first-fetch
caveat). Surya and PyMuPDF remain in the deferred/opt-in-only section, never a default.

</details>

<details>
<summary>File map</summary>

- `engine/texora_engine/recognizers/base.py` — `FormulaRecognizer` Protocol + typed result models.
- `engine/texora_engine/recognizers/formula_pix2tex.py` — real pix2tex adapter, local-weights-only, honest confidence.
- `engine/texora_engine/recognizers/factory.py` — pipeline-driven adapter selection + typed misconfig errors.
- `engine/texora_engine/models/catalog.py` — pinned pix2tex assets with real SHA-256 + pin-on-first-fetch caveat.
- `engine/texora_engine/models/downloader.py` — checksum-verifying streaming downloader (atomic promote, bad-hash reject).
- `engine/texora_engine/api/recognize.py` — bearer-protected `/recognize/snip`, typed Pydantic I/O, 422/timeout handling.
- `engine/texora_engine/api/hardware.py`, `api/models.py` — bearer-protected device + model routes.
- `engine/texora_engine/security.py` — constant-time bearer dependency.
- `engine/texora_engine/app.py` — router wiring (health open; rest protected).
- `engine/tests/test_downloader.py`, `test_formula_pix2tex.py`, `test_recognize_api.py`, ... — real-path tests, no mocked OCR.
- `apps/desktop/src/engineClient.ts` — sole typed bridge client; no fetch.
- `apps/desktop/src-tauri/src/supervisor.rs` — token/port kept in Rust; authenticated `engine_request`.
- `apps/desktop/src-tauri/src/lib.rs` — thin proxy commands.
- `apps/desktop/src-tauri/src/snip.rs` — hotkey + capture (whole-monitor; region select deferred).
- `scripts/build_engine.py` — PyInstaller onefile PE fix-up via temp+replace (unblocks the sidecar).
- `docs/LICENSES.md`, `docs/m2-verification.md` — license rows + recorded green evidence.

Full diff: `git -C c:\data\kucing\texora\.worktrees\m2-formula-ocr diff main`

</details>
