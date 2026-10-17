# Texora M2 — Single-image formula OCR: Requirements & Design

Status: v4 (converged after the third design review — see "Responses to review findings (v4)" at the
end; the v3 and v2 responses are retained below it). The four blocking findings (default-model
SHA-256 pin, confidence contract, katex allow-list generator input, model-download progress event)
are resolved with user-settled final decisions; cheap NITs applied; two spec errata kept flagged.
Scope:
Milestone **M2 — Single-image formula OCR (snip tool, one strong model)**. Target tree:
`c:\data\kucing\texora\.worktrees\m2-formula-ocr`.

Traces to `.kiro/specs/texora/requirements.md` (R-* IDs), `design.md`, `tasks.md` (M2 `done:`
criteria), and the steering set (`tech`, `structure`, `product`, `coding-standards`). This document
covers tasks **2.1–2.6**. It makes the two expensive-to-reverse decisions explicitly (model choice
+ adapter Protocol) and marks which `done:` criteria are structurally verifiable on this host vs.
host/interactive (documented pending).

---

## Part A — Requirements

### A.1 Summary

M2 proves Texora's recognition core on a single image before M3 wires the streaming document
pipeline. A user presses a global hotkey (Ctrl+Shift+M), selects a screen region containing a math
formula, and gets back compilable LaTeX plus MathML in a popup with one-click copy and a
live KaTeX preview (AsciiMath/OMML copy are deferred to M6 — §B.9). The engine gains: a model registry + checksum-verified downloader, a swappable
`FormulaRecognizer` adapter backed by **one strong permissive model running real inference on CPU**,
LaTeX normalization + validation, a token-protected `POST /recognize/snip` route, and a
`GET /hardware` device-report/override. No mocked OCR anywhere in the production path; an
unrecognizable region returns `needs_review`/`failed`, never a fabricated guess.

### A.2 Functional Requirements

**FR-1 Model registry + downloader (task 2.1, R-INST-2/3/4).**
- The engine maintains a `MODEL` registry with, per model: stable `id`, human name, pinned
  `version`, one-or-more source `files` each with a URL, expected `sha256`, and byte `size`; package
  license; on-disk target path; and a `status` (`absent | downloading | verifying | ready |
  corrupt`).
- Downloading a model streams each file to a temp path, computes SHA-256 while writing, and on
  completion compares to the pinned checksum. **A hash mismatch MUST reject the file** (delete the
  temp, do not promote to `ready`, mark `corrupt`, surface an error, allow retry).
- Download exposes progress (bytes received / total, per file and overall) via the `ModelProgress`
  contract and the `engine://model-progress` event (payload + supervisor polling contract in §B.2b).
- An **offline bundle import** path installs models from a local directory/archive with **no network
  access**, verifying the same pinned checksums before promoting to `ready`.
- Registry rows are persisted via the `db/` layer (SQLite), not via ad-hoc files.

**FR-2 FormulaRecognizer adapter + default engine (task 2.2, R-REC-2, R-REC-8, R-HW-2).**
- A stable `FormulaRecognizer` Protocol lives in `engine/texora_engine/recognizers/base.py`: a
  class attribute `id: str` and a pure method `recognize(image, ctx) -> FormulaResult`.
- One concrete adapter implements it against a **permissive, Windows-CPU-practical** formula model
  (decision in §B.3). CPU path is first-class.
- A real image→LaTeX **unit test on a committed fixture** exercises the production code path (no
  mock substituted for the model). If the model weights are absent, the test is skipped with a clear
  reason rather than faked (see §B.8).
- A region the model cannot recognize (empty/degenerate output, exception, or failed validation)
  yields a result whose `status` is `needs_review` or `failed` — never a fabricated LaTeX string.

**FR-3 LaTeX normalize + validate (task 2.3, R-REC-6/7).** *(Reworded for Finding 5 — the engine
does not embed a JS/KaTeX VM; the real KaTeX render is a UI/vitest check.)*
- The **engine** parses/validates each LaTeX string for: balanced braces, matched `\left`/`\right`,
  matched `\begin{env}`/`\end{env}`, and **all commands/environments within the KaTeX-supported set**
  (an allow-list generated from the pinned `katex`; §B.6). Output failing these is **flagged**
  (`validation = needs_review | failed`), never silently emitted as confident.
- The **authoritative KaTeX render** happens where KaTeX actually runs: the UI popup (human-visible)
  and a vitest test that renders the fixture/golden LaTeX with the real pinned `katex` and asserts no
  `ParseError` on valid cases (and a `ParseError` on invalid ones). The engine never claims a render
  it did not perform.
- Output is normalized for compilability and consistency (e.g. canonical `\frac`, spacing,
  `\operatorname`, `\mathrm`) while preserving mathematical meaning.
- (R-REC-6's literal "render check (KaTeX)" wording is flagged to the spec owner as an erratum; the
  intent — don't present un-renderable LaTeX as confident — is fully met by the split above.)

**FR-4 `POST /recognize/snip` (task 2.4, R-UI-2).**
- Accepts a single image and returns `{ latex, confidence, confidence_kind, mathml, asciimath,
  status, validation, detail? }` as a Pydantic model (`status`/`validation` are the shared
  `RecognitionStatus` enum). In M2, `asciimath` is always `null` — the LaTeX→AsciiMath conversion is
  deferred to M6 exporters (R-EXP-3), matching the OMML deferral; the field exists in the schema so
  the contract is stable but is not populated (§B.9, Finding 9).
- Requires the session bearer token (it is a non-health route).
- Returns a well-formed result for the fixture; returns a typed error for malformed input and a
  `needs_review`/`failed` result (HTTP 200 with an explicit status) for unrecognizable images — it
  never fabricates.

**FR-5 Snip Tool UI (task 2.5, R-UI-2, R-UI-10/11).**
- Global hotkey (default **Ctrl+Shift+M**) triggers a screen-region capture; the captured image is
  sent to the engine **through the single typed engine client only**. Because M1 exposes no JS→engine
  HTTP path, the client wraps new Rust proxy commands that carry the bearer token (§B.2a, Finding 1);
  the client itself never calls `fetch` and never holds the token/port.
- A result popup shows the LaTeX, a KaTeX preview, the confidence/validation state, and one-click
  copy for **LaTeX / MathML / Markdown**. (OMML copy is deferred to M6 6.2 — its license is
  unverified for default redistribution; §B.9, Finding 4.)
- All user-facing strings go through i18next (`id` default + `en`), with id/en key parity enforced by
  a test. Keyboard-first and accessible.

**FR-6 Hardware detect + device override (task 2.6, R-HW-1/3).**
- `GET /hardware` reports detected accelerators (CUDA / MPS / CPU) and the currently selected
  device.
- Settings displays this and lets the user override the execution device; the override persists and
  is applied by the recognizer.

### A.3 Non-Functional Requirements

- **Permissive-first (R-LIC-1/2):** the shipped default formula model and its package MUST be
  Apache/MIT/BSD. Surya and any GPL/non-commercial-weights model are opt-in only, never default.
  Every new dependency and every model gets a `docs/LICENSES.md` row in the same change.
- **Privacy/security (R-SEC-1/2/3):** engine stays loopback-only; every non-health route requires
  the bearer token (carried by the Rust proxy, kept out of JS — §B.2a); model downloads are the only
  default network egress and are explicit (the adapter never triggers pix2tex's own fetcher — §B.3);
  uploaded images are validated/size-bounded **and decoded-dimension-bounded** against decompression
  bombs; inference runs in a bounded worker pool with a per-call timeout that returns `failed`
  (§B.7).
- **Honesty (R-REC-8, product principle):** no mocked OCR in production paths; no fabricated output;
  CPU slowness is communicated, not hidden.
- **Testability/quality (R-QA-3/4):** pytest unit + integration + golden tests; vitest for UI;
  structured rotating logging; >80% coverage target on new core logic.
- **Performance (R-PERF-1/3):** the ≤1.5 s single-equation snip target is a **GPU** target; on this
  CPU host latency is measured and documented, not asserted as passing.

### A.4 Acceptance Criteria (testable, numbered)

1. Downloading a model whose bytes do not match the pinned SHA-256 is **rejected**: the temp file is
   deleted, the registry row is not `ready`, an error is surfaced, and retry is possible. (pytest,
   bad-hash fixture) — maps task 2.1 `done:`.
2. A valid offline bundle import promotes a model to `ready` with **zero** network calls, verifying
   the pinned checksum first. (pytest with a local fixture bundle)
3. `FormulaRecognizer` is a `typing.Protocol` with `id: str` and
   `recognize(image, ctx) -> FormulaResult`; the concrete adapter is an instance of it and is
   registered in the pipeline factory keyed by its `id`. (pytest, structural)
3a. The factory raises a typed `UnknownEngineError` (not a bare `KeyError`) when `pipeline.yaml`
   names a formula id absent from `_REGISTRY`, and a typed `FormulaStageNotConfigured` when the key
   is absent/None; both carry the offending/known ids, are logged, and the route maps them to a clear
   500 — no opaque 500 and no silent default. (pytest, Finding 4)
4. The concrete adapter converts a committed formula image fixture to a **non-empty, KaTeX-valid**
   LaTeX string via the real model, exercising the production path (skipped-with-reason if weights
   absent, never mocked). — maps task 2.2 `done:`.
5. The **engine** validator flags unbalanced braces / mismatched `\left\right` / bad environments /
   any command outside the KaTeX-supported allow-list as `needs_review`/`failed`; valid LaTeX passes;
   normalization output still passes the validator. (pytest golden + unit) **Separately**, a vitest
   test renders the fixture + golden LaTeX with the real pinned `katex` and asserts no `ParseError`
   on valid cases and a `ParseError` on invalid ones (the authoritative render — Finding 5).
   **Acceptance boundary (Finding 6):** an allow-list **false positive** (the generated list flags a
   macro that KaTeX actually supports) is **acceptable** and does **not** block `done` — it only
   downgrades that output to `needs_review`, never fabricates. The vitest real-`katex` render is the
   **sole correctness gate**; a divergence between the allow-list and real KaTeX fails this criterion
   **only** when the allow-list **rejects** a case the fixture golden marks **valid** (a too-strict
   list is tolerated; a list that would pass something KaTeX cannot render is not). — maps task 2.3
   `done:`.
6. `POST /recognize/snip` with no/invalid bearer token returns 401; with a valid token and the
   fixture image returns a valid `{latex, confidence, confidence_kind, status, validation, mathml}`
   with `asciimath == null` (deferred to M6 — Finding 9); an oversized decoded image is rejected 422
   (Finding 7). (pytest integration) — maps task 2.4 `done:`.
   **Confidence contract asserted BOTH ways (resolves Finding 2, R-REC-2):** if the pinned pix2tex
   exposes usable per-token scores, the response carries `confidence ∈ (0,1]` with
   `confidence_kind == "token_logprob"`; if it does **not**, the response carries `confidence == 0.0`
   with `confidence_kind == "unavailable"` **and the Snip popup renders a "confidence unavailable"
   state (asserted in vitest)** — never a fabricated number. Shipping `"unavailable"` is an accepted,
   documented R-REC-2 satisfaction for the *provisional* M2 default; M7's benchmark-chosen engine is
   expected to restore a numeric score. The integration test asserts whichever branch the pinned
   package yields (recorded in `docs/m2-verification.md`), and the vitest test asserts the UI
   "confidence unavailable" rendering for the `"unavailable"` branch.
7. `GET /hardware` returns the detected device set and current selection; a device override request
   changes the selection reported on the next call. (pytest integration) — maps task 2.6 `done:`.
8. `engineClient` gains `recognizeSnip`, `getHardware`, `setDevice`, `modelStatus`, `modelDownload`
   as wrappers over the new Rust proxy commands (§B.2a); it remains the **only** production module
   importing `invoke`/`listen` and makes **no `fetch`** (grep-confirmed, as in M1). The new Rust
   commands are permitted in `capabilities/default.json`. The Snip popup renders LaTeX + KaTeX
   preview and LaTeX/MathML/Markdown copy buttons from i18next strings; `id.json`/`en.json` key sets
   are identical (parity test, Finding 11). (vitest + grep + cargo test)
9. New dependencies (engine + npm) and the chosen model each have a `docs/LICENSES.md` row with a
   permissive verdict in the same change.
10. Engine `ruff`/`black --check`/`mypy`/`pytest` and frontend `lint`/`test`/`build` all pass.

### A.5 Out of Scope (deferred to later milestones)

- PDF ingestion, layout detection, reading order, text OCR (M3).
- Job queue, checkpoint/resume, batch, watch folder (M4).
- Ensemble / second-engine low-confidence re-run and the Needs-review panel (M5 — M2 only produces
  the single-engine `needs_review`/`failed` state and confidence; it does not vote across engines).
- Tables, DOCX export, **OMML copy** (its license is unverified for default redistribution — the M2
  snip popup copies LaTeX/MathML/Markdown only; OMML lands with DOCX in M6 6.2), searchable PDF, and
  the handwriting canvas (M6).
- Benchmark harness and benchmark-chosen defaults (M7) — M2 sets a **provisional** default justified
  by license + CPU-practicality, not by measured accuracy numbers.
- Model Manager UI (download/update/delete from the UI) is M7 (7.3). M2 ships the engine-side
  registry/downloader + a minimal first-run/on-demand fetch, not the full manager screen.

### A.6 Assumptions

- The engine Python 3.11 venv (`engine/.venv`) is available for real inference; MSVC toolchain is
  installed for Rust (per `m1-verification.md` §1.4).
- Per the original user approval, M2 performs a real network fetch and a multi-hundred-MB model
  download when inference is first exercised. CI does not download weights by default (gated).
- The global hotkey, actual screen-region capture, and the on-screen popup are
  host/interactive behaviors that can be structurally unit/integration tested but whose live
  behavior is confirmed manually in a running window (documented pending, §B.11).

---

## Part B — Design

### B.1 Overview

M2 extends the existing two-process architecture (Tauri shell ↔ loopback FastAPI engine) without
changing its security model. The engine gains four cohesive modules under `engine/texora_engine/`:
`models/` (registry + downloader), `recognizers/` (the `FormulaRecognizer` Protocol + one concrete
adapter + a pipeline factory), `ensemble/` (LaTeX normalize + validate + KaTeX check — the
single-engine subset of the full M5 ensemble), and `db/` (SQLite access for the `MODEL` and
`SETTING` tables). The API gains `POST /recognize/snip`, `GET /hardware`, and model
registry/download routes, all behind the existing `require_token` dependency. The shell gains a
global-shortcut + screen-capture path (Rust) that hands a captured PNG to the single typed
`engineClient`, and a Snip popup + Settings/hardware UI (React, i18next). `pipeline.yaml` gains a
concrete `recognize.formula` default pointing at the chosen adapter `id`, so the API/UI never name a
specific engine.

The design reuses M1 patterns verbatim: `create_app` wires routers; new routes live on
`protected_router` (token-enforced); Pydantic v2 models for all I/O; the shared rotating logger (no
bare `print`); `engineClient.ts` as the sole Tauri-bridge importer; strings via i18next.

### B.2 Technology stack (locked once approved)

Engine (new, pinned — exact patch verified against PyPI at implementation time, nearest patch in the
same minor if a pin is unavailable, and the `docs/LICENSES.md` row updated to match):

| Purpose | Library | Pin (target) | License | Why |
|---|---|---|---|---|
| Formula model (DEFAULT) | `pix2tex` (LaTeX-OCR) | `0.1.4` | MIT | Permissive **code and weights**, pip-installable, real CPU inference via PyTorch, weights on GitHub Releases with stable URLs → SHA-256 pinnable. (§B.3) |
| Tensor runtime (CPU) | `torch` (CPU wheel) | `2.3.1+cpu` | BSD-3-Clause | pix2tex backend; CPU index URL avoids CUDA download. Pin from the PyTorch CPU wheel index. |
| Image I/O | `pillow` | `10.4.0` | MIT-CMU (HPND) | Decode uploaded PNG; feed the model. Already needed project-wide (M3 adds pillow-heif). |
| HTTP client (model download) | `httpx` | `0.28.1` | BSD-3-Clause | **Promoted from dev to runtime** (see below). Streaming download with timeouts for the model downloader (FR-1); already pinned, only its LICENSES.md verdict/section changes. |
| LaTeX parse/validate | `pylatexenc` | `2.10` | MIT | AST/brace/macro validation + LaTeX→(text/unicode) helpers; named in tasks 2.3. |
| LaTeX → MathML | `latex2mathml` | `3.77.0` | MIT | Produce MathML for the snip result (`SnipResponse.mathml`). |
| Hardware probe | `torch` (already) + stdlib | — | — | `torch.cuda.is_available()` / `torch.backends.mps.is_available()`; no extra dep. |

**HTTP-client decision (Finding 2).** The M1 manifests ship no HTTP client at runtime —
`engine/requirements.txt` has only `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`;
`httpx==0.28.1` lives in `requirements-dev.txt` and is recorded in `docs/LICENSES.md` under "dev /
test". The model downloader (FR-1) is a **runtime** path (R-INST-2), so it needs a client that is
actually present in the frozen PyInstaller sidecar. Two options were considered: (a) use the stdlib
`urllib.request` (no new dep, but clunkier streaming + timeout handling and no connection reuse), or
(b) **promote `httpx` to a runtime dependency**. We choose (b): it is already pinned and
license-cleared (BSD-3-Clause), gives clean streaming (`client.stream("GET", …)`), per-request
timeouts, and matches the test client already in use. Concretely: move `httpx==0.28.1` from
`requirements-dev.txt` into `requirements.txt`; move its `docs/LICENSES.md` row from the "dev / test"
table into the "runtime" table (verdict stays Yes/Yes); and ensure the PyInstaller spec collects it
(`httpx` + its `httpcore`/`h11`/`anyio`/`certifi`/`idna`/`sniffio` deps — add a
`--collect-submodules httpx`/hiddenimports entry in `scripts/build_engine.py`). OMML conversion
(previously an `lxml` + Microsoft XSLT row) is removed from the M2 stack — see the OMML decision in
§B.9.

Frontend (new, pinned):

| Purpose | Library | Pin (target) | License |
|---|---|---|---|
| Math preview + render check | `katex` | `0.16.11` | MIT |
| Tauri global shortcut | `@tauri-apps/plugin-global-shortcut` | `2.x` (match CLI 2.12 line) | Apache-2.0 OR MIT |

`katex` is used in the UI for the human-visible preview **and** as the authoritative render check in
a vitest test (§B.6, Finding 5). The Python sidecar does **not** embed a JS VM or `katex.min.js`; it
validates against a KaTeX-supported-macro allow-list generated from the pinned `katex` (via its
public API / function registry, with a vendored-source-tarball fallback — §B.6).
This keeps the frozen sidecar a single Python binary with no Node/JS dependency while the real KaTeX
render lives on the UI side where it belongs.

Rust (new, pinned): `tauri-plugin-global-shortcut` (2.x) for the hotkey; `xcap` (Apache-2.0,
cross-platform monitor capture) for screen capture (§B.10); and `ureq` (2.12.1, **already a crate
dep** — used by the supervisor `/healthz` probe) reused as the blocking HTTP client for the new
engine-proxy commands (§B.2a). Device info for `GET /hardware` is computed in the engine
(Python/torch), not Rust.

### B.2a DECISION 0 — Frontend → engine transport (Finding 1)

The design repeatedly asserts the UI reaches the engine "through the single typed `engineClient`",
but M1 provides **no JS→engine HTTP path**. Reading the actual M1 source confirms this:
`engineClient.ts` is the sole importer of `@tauri-apps/api` and wraps only
`invoke('engine_status')` + the `engine://status` event — it makes no HTTP calls and holds no
port/token. `lib.rs` exposes exactly one command (`engine_status`). `supervisor.rs` mints the
256-bit token once, picks a fresh free loopback port per spawn, and **never hands the token or
port to JS**. The supervisor already uses the `ureq` crate for its blocking `/healthz` probe.

**Where the token actually lives today (Finding 1 — corrected).** The prior revision stated the
token is passed to the engine *only* via the `TEXORA_ENGINE_TOKEN` env var. That is **wrong** and is
corrected here. `supervisor.rs::spawn_engine` passes the token **both** on argv and via env:

```rust
let args = ["--host", "127.0.0.1", "--port", &port_str, "--token", token];   // argv
// ...
command.env("TEXORA_ENGINE_TOKEN", token).spawn()                            // env too
```

and `capabilities/default.json` explicitly whitelists `--token [0-9a-f]+` on the sidecar argv. So
the token is on the child-process command line **and** in the environment (design.md §1.1:
"token also via env … where possible"). **M2 does not change this transport.** Decision 0 below is
*not* about the Rust→engine seam (which is unchanged); it is strictly about the **JS→engine seam**:
whether the webview ever receives the loopback port or the bearer token. It must not.

*Argv hardening is explicitly out of M2 scope.* Tightening the current argv exposure (removing
`--token` from argv so the token is env-only) would require coordinated edits to `supervisor.rs`
(drop the arg), the `capabilities/default.json` validator (drop the whitelisted `--token` entry),
and the engine CLI arg parser, plus its own test. That is a separate, deliberate sub-task and is
**not** assumed to be already done and **not** smuggled into M2 — an implementer must not "restore"
an env-only transport or they will break the capability validator and engine arg parsing.

Two options exist, and they are incompatible:

- **(a) Rust proxy commands.** Add new `#[tauri::command]`s (`recognize_snip`, `get_hardware`,
  `set_device`, `model_status`, `model_download`) in `lib.rs`, backed by the supervisor, that make
  authenticated `ureq` calls to `127.0.0.1:<port>` with an `Authorization: Bearer <token>` header.
  The token and port stay in Rust (consistent with M1's security model); `engineClient` `invoke`s
  these commands. Image bytes travel JS → command → Rust → engine.
- **(b) Expose port+token to JS, `fetch` directly from `engineClient`.** This leaks the token into
  the JS heap, requires a new HTTP capability in `capabilities/default.json` (today only `core:default`
  + the sidecar shell scope are granted), and widens the token's exposure to the webview — the exact
  thing Decision 0 exists to prevent.

**Decision: (a).** Today the token already reaches the engine via argv+env (above); the point of
Decision 0 is that it must **not** additionally cross into the JS heap. Option (a) keeps the token
and port in Rust only, needs no HTTP capability, and preserves the single-typed-client invariant
because `engineClient` still wraps only `invoke`/`listen` (no `fetch`). The cost is that request
plumbing lives in Rust; steering says Rust stays "a secure client + process manager", and a thin
authenticating HTTP proxy that carries no OCR or business logic is exactly that — it just forwards
bytes and attaches the bearer header. This is stated explicitly so the seam is not a surprise.

Concrete shape:

- The supervisor stores the current `port` and `token` in `SupervisorState` (today it stores only
  the status snapshot). A small helper `engine_request(method, path, body) -> Result<Bytes, Error>`
  builds the `ureq` request against the live port with the bearer header. If the engine is not
  `Healthy` (no port yet), the proxy returns a typed "engine not ready" error that `engineClient`
  surfaces to the UI, rather than panicking.
- New commands in `lib.rs` (registered in `generate_handler!`), each a thin wrapper:
  - `recognize_snip(image_base64: String, is_display: bool) -> SnipResult`
  - `get_hardware() -> Hardware`
  - `set_device(device: String) -> Hardware`
  - `model_status(id: String) -> ModelStatus` and `model_download(id: String) -> ModelStatus`.
    **`model_download` is non-blocking (Finding 7):** it starts the download server-side and
    **returns immediately** with the initial status (`downloading`); it never blocks the `invoke`
    for the multi-hundred-MB transfer (which would be poor UX and risks hitting Tauri IPC timeouts).
    The **terminal** state (`ready` on checksum match, `corrupt` on mismatch) and interim byte
    progress are delivered via the `engine://model-progress` event the supervisor emits while polling
    `GET /models/{id}` — the client subscribes rather than long-polling (payload + polling contract
    pinned in §B.2b). **Cancel is out of M2 scope** (first-run cancel UI is M7 7.3 per §A.5); a
    partially downloaded `.part` left by an app kill is cleaned up on the next download attempt (the
    downloader always writes to a fresh temp).
- `capabilities/default.json` gains an `allow` entry for each new command (Tauri v2 requires the
  command be permitted for the `main` window). No network/HTTP capability is added — the HTTP call
  happens in Rust, not the webview.
- `engineClient.ts` gains `recognizeSnip`/`getHardware`/`setDevice`/`modelStatus`/`modelDownload`
  as `invoke` wrappers and `subscribeModelProgress`/`subscribeSnipCaptured` as `listen` wrappers —
  it remains the only module importing `invoke`/`listen` (grep-enforced, AC-8).

This makes AC-8 implementable: the capture PNG flows capture(Rust/xcap) → `engine://snip-captured`
event → `engineClient.recognizeSnip` → `recognize_snip` command → Rust `ureq` + bearer → engine
`POST /recognize/snip`.

### B.2b Model-download progress event contract (resolves Finding 4)

The first-run / on-demand fetch (§A.5) needs a concrete progress contract, so both the payload schema
**and** the supervisor's polling behavior are pinned here (they were previously only alluded to).

**`ModelProgress` payload — Pydantic model (engine) + mirrored TS type (client).** The engine exposes
a `ModelProgress` Pydantic v2 model that `GET /models/{id}` returns and that the supervisor forwards
verbatim on each `engine://model-progress` event; `engineClient.ts` mirrors it exactly as a shared TS
type (same literals, camelCase on the TS side), consistent with the `RecognitionStatus` mirroring:

```python
# engine/texora_engine/models/progress.py
from enum import StrEnum
from pydantic import BaseModel, Field

class ModelDownloadState(StrEnum):
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"     # bytes fully received; hashing/comparing to the pinned SHA-256
    READY = "ready"             # terminal: checksum matched, promoted
    CORRUPT = "corrupt"         # terminal: checksum mismatch, part deleted
    ERROR = "error"             # terminal: network/IO/other failure, retry offered

class ModelFileProgress(BaseModel):
    name: str                   # asset filename (e.g. "weights.pth")
    received: int = Field(ge=0) # bytes written to the .part so far
    total: int = Field(ge=0)    # expected size from the pinned ModelFile (0 if unknown)

class ModelProgress(BaseModel):
    id: str                                     # model id (e.g. "pix2tex")
    state: ModelDownloadState
    bytes_received: int = Field(ge=0)           # overall sum across files
    bytes_total: int = Field(ge=0)              # overall expected sum (0 if any file size unknown)
    files: list[ModelFileProgress]              # per-file received/total (FR-1: per file AND overall)
    detail: str | None = None                   # error/why context on error|corrupt
```

```ts
// mirrored in engineClient.ts (shared TS types block)
export type ModelDownloadState = 'downloading' | 'verifying' | 'ready' | 'corrupt' | 'error';
export interface ModelFileProgress { name: string; received: number; total: number; }
export interface ModelProgress {
  id: string;
  state: ModelDownloadState;
  bytesReceived: number;
  bytesTotal: number;
  files: ModelFileProgress[];
  detail?: string | null;
}
```

This directly satisfies FR-1's "bytes received / total, **per file and overall**": `files[].received/
total` are per file, `bytesReceived/bytesTotal` are the overall rollup.

**Supervisor polling contract (what starts polling, the interval, the stop condition).**
- **Start:** the `model_download(id)` command, after telling the engine to begin the server-side
  download (which returns the initial `downloading` status immediately), registers `id` with the
  supervisor's **model-download poller** (a small map of in-flight download ids kept on
  `SupervisorState`, keyed by model id so concurrent downloads of different ids are independent). The
  download work itself runs in the engine (a background task); the supervisor only *observes* it.
- **Poll:** for each registered id the supervisor polls `GET /models/{id}` (the engine returns the
  current `ModelProgress`) at a **fixed interval of 500 ms** — frequent enough for a live byte-count
  bar, cheap enough for a loopback call — and emits one `engine://model-progress` event carrying that
  `ModelProgress` per poll.
- **Stop:** polling for an id stops (the id is removed from the in-flight map) as soon as a poll
  returns a **terminal state — `ready`, `corrupt`, or `error`**; the supervisor emits that terminal
  `ModelProgress` once more and then stops. (A `verifying` state is non-terminal and keeps polling.)
  If the engine becomes unreachable mid-download (process died), the poll surfaces an `error`
  `ModelProgress` for that id and polling stops, so the UI never hangs on a dead download.
- The poller reuses the existing `ureq` agent and runs alongside (not blocking) the health loop.

`engineClient.subscribeModelProgress(cb)` is a `listen('engine://model-progress', …)` wrapper that
delivers each `ModelProgress` to the first-run progress UI; the UI renders the overall bar from
`bytesReceived/bytesTotal` and per-file rows from `files`, and closes on a terminal state.

### B.3 DECISION 1 — Default formula model (permissive + Windows-CPU-practical)

**Choice: `pix2tex` (LaTeX-OCR) as the M2 shipped default.** Exact pin, checksum, and license below.

Candidates considered:

- **PP-FormulaNet-S** (PaddleOCR/PaddleX). Package Apache-2.0. *But* it requires the **PaddlePaddle**
  runtime, whose Windows-CPU wheels are heavy and historically fragile, the model is distributed
  through the PaddleX model hub (indirect, harder to pin a single stable URL + SHA-256 for a first
  cut), and freezing Paddle under PyInstaller for the sidecar adds real packaging risk. Strong M7
  benchmark candidate, but a poor *first* CPU default here.
- **UniMERNet** (Apache-2.0 package). Accurate, transformer-based; larger weights and heavier
  dependency surface than needed to *prove the core* on CPU in M2. Keep as an M7 candidate.
- **Surya.** Code GPL-3.0 + non-commercial RAIL weights. **Excluded by policy** — opt-in only, never
  the shipped default (R-LIC-2; `docs/LICENSES.md` "Deferred / opt-in only").
- **pix2tex (LaTeX-OCR).** **MIT license for both code and weights.** Pip-installable
  (`pip install pix2tex`); pure PyTorch, runs on CPU out of the box; weights are published as
  versioned assets on the project's GitHub Releases, giving **stable URLs we can SHA-256 pin** and a
  clean offline-bundle story. It outputs LaTeX for a single cropped formula image — exactly the M2
  snip use case. This is the most permissive, most CPU-practical, most pinnable option for M2.

**Decision + justification:** ship **pix2tex** as the provisional M2 default. It satisfies
permissive-first (MIT code + MIT weights → redistributable), runs real inference on this Windows CPU
host, and its release-asset weights are checksum-pinnable for FR-1. This is a *provisional* default
chosen on license + CPU-practicality grounds (no fabricated accuracy claim); M7 (task 7.2) may
replace it with a benchmark-justified permissive model (PP-FormulaNet-S / UniMERNet) by changing one
`id` in `pipeline.yaml` — no API/UI change, because of Decision 2.

**Explicit deviation from tasks.md 2.2 (Finding 6).** tasks.md 2.2 and the user's sign-off name
**PP-FormulaNet-S** as the provisional default, with the explicit latitude "or a benchmark-chosen
permissive one". Choosing pix2tex uses that latitude, but because PP-FormulaNet-S was named
specifically, the swap is called out here rather than made silently: **pix2tex supersedes
PP-FormulaNet-S as the M2 default**, on the packaging/pinnability grounds above (PaddlePaddle
Windows-CPU/PyInstaller risk; PaddleX-hub weights are harder to pin to a single stable URL + SHA-256
for a first cut). PP-FormulaNet-S and UniMERNet remain M7 (7.2) benchmark candidates and can take
the default back by a one-line `pipeline.yaml` change. tasks.md 2.2 should be updated to read
"pix2tex (LaTeX-OCR) default for M2; PP-FormulaNet-S/UniMERNet are M7 candidates" so the spec and
design agree — this doc flags that edit to the spec owner (it is not applied here).

**SHA-256 pinning story — DECISION: pin-on-first-fetch of the upstream release asset (resolves HIGH Finding 1, user-settled).**
pix2tex distributes its weights (`weights.pth`, `image_resizer.pth`) as **GitHub release assets** on
`lukas-blecher/LaTeX-OCR` (a release tag such as `v0.0.1`), and upstream publishes **no
vendor-signed checksum** for them. So the pinned-SHA-256 story is explicitly **pin-on-first-fetch**,
not a vendor-pinned hash:

1. **Bypass pix2tex's built-in auto-downloader entirely.** The fetch is driven through **our own
   `models/` registry** (FR-1), never pix2tex's fetcher (§B.3 adapter-suppression below, §B.4).
2. **Fetch from the exact immutable per-tag release-asset URL.** `catalog.py` records, per file, the
   direct GitHub release-asset download URL pinned to the **specific release tag** (not `latest`, not
   a rolling/redirecting URL).
3. **On first fetch, download once, compute the SHA-256 OURSELVES, and record it in `catalog.py`** as
   the pinned checksum. This is a one-time adoption step performed by the implementer during tasks
   2.1/2.2 — **the coder ACTUALLY fetches the real assets, computes the real SHA-256, and bakes those
   real values into `catalog.py`. NEVER an invented hash.** If the asset URL / release tag / filenames
   differ from the assumption here (`weights.pth` / `image_resizer.pth` at tag `v0.0.1`), the coder
   uses the **real** ones discovered at fetch time and updates `catalog.py`, `ModelSpec`/`ModelFile`,
   and the factory `file_path(...)` lookups (§B.4) to match.
4. **Verify against the recorded hash forever after.** Every subsequent model load **and** every
   offline-bundle import re-verifies the downloaded/imported bytes against that recorded SHA-256
   (FR-1, AC-1/AC-2) — a mismatch rejects the file exactly as for any other model.

**Honesty caveat (documented, R-INST-2/3 satisfaction for the provisional M2 default).** The recorded
checksum is **OUR hash of the upstream release asset at the pinned tag, not a vendor-signed
checksum.** This is an accepted, documented satisfaction of R-INST-2/3 for the *provisional* M2
default: it guarantees integrity/immutability *relative to the bytes we first pinned* (tamper- and
corruption-detection on every later fetch, reproducible offline import), but it is not an independent
upstream attestation. This caveat is stated plainly in **`docs/LICENSES.md`** (the pix2tex model row)
**and `docs/m2-verification.md`**. A vendor-pinned checksum or a Hugging-Face-revision-addressed model
(content-addressed by commit) is an **M7 option** when the benchmark-chosen default is selected.

Pin values to record in the registry and `docs/LICENSES.md` (confirm exact values at adoption against
the pinned release; the hash is computed-at-fetch per the story above, never invented):

- Package: `pix2tex==0.1.4` (PyPI), MIT. Torch backend `torch==2.3.1+cpu`, BSD-3-Clause. (These are
  *target* pins; the exact existing patch is confirmed against PyPI at implementation time.)
- Weights: the checkpoint asset(s) that pix2tex uses (`weights.pth`, and `image_resizer.pth` only if
  the pinned version actually ships/uses a separate resizer checkpoint) from the **pinned pix2tex
  GitHub Release tag** (assumed `v0.0.1`; confirm at adoption). Each file gets a `version` (= release
  tag), its direct **immutable per-tag** release-asset URL, byte `size`, and a `sha256` **computed
  from the pinned asset on first fetch** and committed into `catalog.py`.

**Adoption checklist (tasks 2.1/2.2, done before `catalog.py` is final — confirm and record, never
invent):** (1) the exact `pix2tex` PyPI version that exists; (2) the exact GitHub release tag that
hosts the checkpoint; (3) each asset's exact filename and its **direct, non-redirecting, immutable**
per-tag download URL; (4) the real SHA-256 computed from each downloaded asset. If the real shape
differs from the assumption above — e.g. a single `weights.pth`, a different repo/tag, or a
redirecting URL — then `ModelSpec`/`ModelFile`, `models/catalog.py`, and the factory's
`file_path("weights.pth")`/`file_path("image_resizer.pth")` lookups (§B.4) are updated to the real
shape. The offline-bundle import path (§B.5 `bundle.py`) imports the **same** files and verifies them
against the **same** recorded SHA-256 — it is the no-network install path, not a feasibility fallback;
first-run auto-download through our registry is the primary path and is not "best-effort".
- `docs/LICENSES.md` rows to add/move (same change): `pix2tex` (MIT, personal+redistribute Yes),
  `torch` CPU (BSD-3-Clause, Yes/Yes), `pillow` (HPND, Yes/Yes), `pylatexenc` (MIT), `latex2mathml`
  (MIT), and **move `httpx` 0.28.1 from the "dev / test" table into the "runtime" table** (Finding 2;
  BSD-3-Clause, Yes/Yes). Plus a **model row** for the pix2tex weights (MIT weights → redistribute
  Yes) **carrying the pin-on-first-fetch honesty caveat** (the recorded SHA-256 is our hash of the
  upstream release asset at the pinned tag, not a vendor-signed checksum — §B.3) and the frontend
  `katex` (MIT) + `@tauri-apps/plugin-global-shortcut` (Apache-2.0 OR MIT) +
  the `xcap` crate (Apache-2.0) + `tauri-plugin-global-shortcut` crate (Apache-2.0 OR MIT). No `lxml`
  / Microsoft XSLT row — OMML is handled per §B.9 (deferred from the M2 popup).

Risk/mitigation: pix2tex pulls a large torch dependency. Mitigation: pin the **CPU** wheel
(`+cpu` from the PyTorch CPU index) so no CUDA payload is fetched; PyInstaller collects torch via a
`--collect-submodules torch` hook (extends the existing `scripts/build_engine.py`). If torch-on-CPU
freeze proves impractical under PyInstaller in a later step, the fallback is an ONNX-exported
pix2tex decoder run through `onnxruntime` (Apache-2.0) — recorded as a tracked risk, not silently
switched.

### B.4 DECISION 2 — Adapter Protocol + factory wiring

The Protocol is the stable seam that keeps the API/UI engine-agnostic. It is deliberately minimal
and pure.

```python
# engine/texora_engine/recognizers/base.py
from __future__ import annotations
from enum import StrEnum
from typing import Protocol, runtime_checkable
from PIL import Image
from pydantic import BaseModel, Field

class RecognitionStatus(StrEnum):
    """Single source of truth for recognition/validation state (Finding 8).

    Shared by FormulaResult, the validator, and SnipResponse; mirrored as a
    TS union `'ok' | 'needs_review' | 'failed'` in engineClient.ts so the same
    literals cross the language boundary with no drift (never "needs-review").
    """
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"

class RegionContext(BaseModel):
    """Inputs that influence recognition but are not the image itself."""
    is_display: bool = Field(
        default=True,
        description="Display vs inline math hint. In M2 this does NOT change recognition "
        "(pix2tex has no display/inline switch); it only controls downstream Markdown "
        "wrapping ($$...$$ vs $...$) assembled in the UI. See §B.4 / §B.9.",
    )
    device: str = Field(default="cpu", description="Execution device: cpu|cuda|mps.")
    source: str = Field(default="snip", description="snip|page — provenance for logging.")

class FormulaResult(BaseModel):
    """Explicit result type. Never contains a fabricated guess."""
    latex: str = Field(default="", description="Recognized LaTeX; empty when failed.")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_kind: str = Field(
        default="token_logprob",
        description="How `confidence` was derived (Finding 9): "
        "'token_logprob' = calibrated from decoder logprobs; "
        "'unavailable' = no meaningful score (confidence is a documented default, see detail).",
    )
    status: RecognitionStatus = Field(default=RecognitionStatus.OK)
    engine_id: str = Field(description="Adapter id that produced this result.")
    detail: str | None = Field(default=None, description="Failure/why context.")

@runtime_checkable
class FormulaRecognizer(Protocol):
    id: str
    # Model registry id(s) this adapter needs, declared by the adapter rather than
    # assuming adapter.id == model.id (NIT Finding 6). M2's pix2tex adapter sets
    # model_ids = ("pix2tex",), but a future adapter may share or swap weights.
    model_ids: tuple[str, ...]
    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult: ...
```

`FormulaResult` is a Pydantic model (not a bare dataclass) so it serializes directly into the API
response and is mypy-strict-clean across module boundaries (coding-standards: no untyped dicts
across boundaries). `status` is the shared `RecognitionStatus` `StrEnum`, not a free-form `str`
(Finding 8). `recognize` is **pure**: it takes an in-memory `PIL.Image` + context and returns a
result; it performs no I/O beyond the model forward pass, and it **catches its own inference errors**
and maps them to `status=FAILED` with `detail` rather than raising — so one bad image can never
crash a caller (coding-standards: fail gracefully).

**Confidence derivation (Finding 5/9, R-REC-2) — availability is NOT assumed.** pix2tex exposes no
native calibrated 0..1 score, so the field must be derived honestly, never invented. The prior
revision assumed per-token logprobs are reachable "through a stable API" — that is an **unverified
assumption** about pix2tex's public surface and is corrected here. pix2tex's high-level
`LatexOCR.__call__` returns only the decoded **string**; per-token scores generally require driving
the underlying model's `generate(..., output_scores=True, return_dict_in_generate=True)` (or the
equivalent decode loop that captures logits), which is a lower-level path that may or may not be
cleanly reachable on the pinned version.

Because this is load-bearing for M5's low-confidence trigger, the implementer **MUST verify on the
pinned pix2tex** (a one-line probe, recorded in `docs/m2-verification.md`) whether per-token scores
are obtainable via a stable call **before** relying on them. Two honest outcomes:

- **Scores reachable:** `confidence = exp(mean per-token logprob)` (the geometric-mean token
  probability, in 0..1), `confidence_kind="token_logprob"`.
- **Scores NOT reachable on the pin:** the adapter does **not** fabricate a number. Every result
  carries `confidence=0.0`, `confidence_kind="unavailable"`, and a `detail` noting the score is
  unavailable. In this case **M2 ships `"unavailable"` for pix2tex**, and this design states plainly
  that **M5's low-confidence re-run keys off `validation`/`status` state (not a numeric threshold)
  until a scoring-capable engine lands** — so an all-`unavailable` M2 does not quietly make M5's
  trigger meaningless. The UI shows "confidence unavailable" rather than a fake value.

Either outcome is acceptable for M2; what is not acceptable is implying a working logprob path that
may not exist. The chosen outcome is recorded in `docs/m2-verification.md` at adoption.

**`RegionContext.is_display` effect (Finding 5b) — pinned.** pix2tex has no display/inline switch,
so `is_display` **does not change recognition** in M2. It is a pure passthrough hint consumed only
**downstream**: the UI uses it to decide Markdown copy wrapping (`$$...$$` for display vs `$...$` for
inline — §B.9). The adapter ignores it for the forward pass; it is kept on `RegionContext` (rather
than dropped) because M3's page pipeline and M6's exporters need the same display/inline provenance,
and threading it now avoids a Protocol change later. An input that is accepted-but-ignored-by-the-model
is therefore documented, not ambiguous.

The concrete adapter:

```python
# engine/texora_engine/recognizers/formula_pix2tex.py
class Pix2TexFormulaRecognizer:
    id = "pix2tex"
    model_ids = ("pix2tex",)   # NIT Finding 6: declared, not inferred from `id`
    def __init__(self, checkpoint_path: Path, resizer_path: Path, device: str = "cpu") -> None:
        # Construct pix2tex pointed ONLY at registry-resolved local weights.
        # The pix2tex LatexOCR() default fetches weights.pth/image_resizer.pth from
        # its GitHub release on first use if absent — we suppress that entirely by
        # passing explicit checkpoint/resizer args so no uncontrolled network call
        # can happen here (Finding 3, R-SEC-1, FR-1). If either file is missing we
        # raise ModelNotReady; we never let pix2tex reach the network.
        ...
    def recognize(self, image: Image.Image, ctx: RegionContext) -> FormulaResult: ...
```

**pix2tex auto-download suppression (Finding 3).** The whole FR-1 guarantee (pinned SHA-256,
offline-bundle import, "network egress happens only in the downloader") requires the engine to be
the *only* thing that fetches weights. pix2tex's `LatexOCR()` has a built-in checkpoint fetcher that
downloads `weights.pth`/`image_resizer.pth` from its GitHub release on first construction when the
files are absent — an unpinned path that would bypass the registry/checksum and violate R-SEC-1. The
adapter therefore **always** constructs pix2tex with explicit local checkpoint/resizer paths resolved
from the model registry (`require_ready(ctor.model_ids[0])`, i.e. the adapter-declared model id —
NIT Finding 6), never invoking the default-arg path that
triggers the fetcher. A unit test asserts that **constructing the adapter with the weights absent
raises `ModelNotReady` and makes no network call** (the test runs with networking stubbed to fail, so
any accidental fetch attempt fails loudly rather than silently succeeding).

**`pipeline.yaml` typed schema (Finding 3 — reconciled with the committed template).** The committed
M1 `pipeline.yaml` documents `recognize` as a **single flat stage key** sibling to
`ingest`/`layout`/`ensemble`/`export`, with the comment `recognize: # text / formula / table /
handwriting`. The prior revision silently turned `recognize` into a nested map without reconciling
the two shapes, which would collide when M3 adds the other stages. This design now **pins the typed
Pydantic schema** and makes the committed file match it. `recognize` is a **map of sub-stages**
(`formula`/`text`/`table`/`handwriting`) — the natural fit for R-REC and the M3 pipeline — so each
recognizer type selects its engine id independently:

```python
# engine/texora_engine/pipeline_config.py  (typed config, structure.md: no magic constants)
from pydantic import BaseModel

class RecognizeStage(BaseModel):
    formula: str | None = None     # engine id; None = stage not configured yet
    text: str | None = None        # M3
    table: str | None = None       # M6
    handwriting: str | None = None # M6

class Stages(BaseModel):
    ingest: str | None = None      # M3
    layout: str | None = None      # M3
    recognize: RecognizeStage = RecognizeStage()
    ensemble: str | None = None    # M5
    export: str | None = None

class PipelineConfig(BaseModel):
    version: int = 1
    stages: Stages = Stages()

def load_pipeline_config() -> PipelineConfig:  # parses pipeline.yaml via Pydantic
    ...
```

The committed `pipeline.yaml` is edited by **replacing the ENTIRE commented placeholder body** (every
currently-commented line, including `# version: 1` and the flat `recognize: # text / formula / ...`
comment) with the minimal real config below — the implementer must not paste the new block while
leaving the old commented lines (that would produce a confusing double, NIT Finding 5). The
**permissive-first comment is kept** so the engine-id choices stay governed by the policy:

```yaml
# pipeline.yaml — default pipeline config (engine ids per stage).
# Permissive-first: only Apache/MIT/BSD engines may be the shipped default here;
# copyleft/non-commercial engines (e.g. Surya) are opt-in only, never set as a default id.
# `recognize` is a MAP of sub-stages (formula/text/table/handwriting); M3+ fill the other keys.
version: 1
stages:
  recognize:
    formula: pix2tex        # adapter id; swappable without touching API/UI
    # text / table / handwriting engine ids are set in later milestones (M3/M6)
  # ingest / layout / ensemble / export are configured in M3+ (keys above)
```

**Key-absent behavior (Finding 3/4).** `stages.recognize.formula` is `str | None`. If the key is
**absent/None** when the formula recognizer is requested, the factory raises a typed
`FormulaStageNotConfigured` (mapped by the route to a clear **500** — server misconfiguration, same
class as an unknown id below — logged via the shared logger) — it does **not** silently fall back to
a hardcoded default, because a hidden default is exactly the "magic constant" structure.md forbids. For M2 the committed file always sets `formula: pix2tex`, so this path is an
error guard, not the normal flow.

Factory + wiring:

```python
# engine/texora_engine/recognizers/factory.py
_REGISTRY: dict[str, Callable[..., FormulaRecognizer]] = {
    Pix2TexFormulaRecognizer.id: Pix2TexFormulaRecognizer,
}

class UnknownEngineError(Exception):
    """pipeline.yaml names a formula engine id that is not registered."""
    def __init__(self, stage_id: str, known: list[str]) -> None:
        self.stage_id, self.known = stage_id, known
        super().__init__(f"unknown formula engine id {stage_id!r}; known: {known}")

def build_formula_recognizer(settings, model_registry) -> FormulaRecognizer:
    stage_id = load_pipeline_config().stages.recognize.formula   # from pipeline.yaml
    if stage_id is None:
        raise FormulaStageNotConfigured()                        # typed; mapped to 500 (misconfig)
    if stage_id not in _REGISTRY:                                # Finding 4: no bare KeyError
        logger.error("unknown formula engine id %r; known=%s", stage_id, list(_REGISTRY))
        raise UnknownEngineError(stage_id, known=list(_REGISTRY))
    ctor = _REGISTRY[stage_id]
    # NIT Finding 6: resolve weights via the adapter's declared model_ids, NOT by
    # assuming adapter.id == model.id. For M2 the pix2tex adapter declares
    # model_ids = ("pix2tex",), so this resolves the same single model today while
    # staying correct for a future adapter that shares/swaps weights.
    model = model_registry.require_ready(ctor.model_ids[0])      # raises ModelNotReady if absent
    # Pass explicit local weight paths so the adapter never triggers pix2tex's
    # own downloader (Finding 3). File names come from the pinned ModelSpec.
    return ctor(
        checkpoint_path=model.file_path("weights.pth"),
        resizer_path=model.file_path("image_resizer.pth"),
        device=settings.device,
    )
```

**Unknown/unconfigured-id handling (Finding 4).** `build_formula_recognizer` never does a bare
`_REGISTRY[stage_id]` — that would raise a raw `KeyError` on a misspelled or swapped id (precisely
the "swap one line in `pipeline.yaml`" seam the design advertises for M7) and surface as an opaque
FastAPI 500. Instead the factory validates `stage_id` against `_REGISTRY` and raises a typed
`UnknownEngineError(stage_id, known=list(_REGISTRY))`, logged via the shared logger with the
offending id and the known ids. The recognize router maps `UnknownEngineError` and
`FormulaStageNotConfigured` to a clear **500** (server misconfiguration — a bad `pipeline.yaml`,
not user input) with an actionable message naming the bad id and the known ids. A unit test exercises
the unknown-id path (lives next to AC-3; see AC-3a).

The route handler depends on the Protocol type, never on `Pix2TexFormulaRecognizer`. A
`runtime_checkable` Protocol lets the structural test assert `isinstance(adapter, FormulaRecognizer)`
without inheritance. Adding a second engine later (M5/M7) is: drop a new file in `recognizers/`,
register it in `_REGISTRY`, change one line in `pipeline.yaml`.

### B.5 Model registry + downloader (task 2.1)

Module `engine/texora_engine/models/`:
- `registry.py` — Pydantic `ModelSpec` (`id`, `version`, `files: list[ModelFile]`, `license`,
  `target_dir`) and `ModelFile` (`name`, `url`, `sha256`, `size`). The pinned specs live in a
  committed `models/catalog.py` (or a checked-in `models.yaml` loaded via Pydantic) — the pix2tex
  spec is the only entry in M2. No magic constants scattered in code.
- `downloader.py` — streams each file to `<target_dir>/.incoming/<name>.part`, hashing with
  `hashlib.sha256` as it writes, emitting progress (callback / async generator). On completion:
  compare digest to `spec.sha256`; **mismatch → delete part, raise `ChecksumMismatch`, mark
  `corrupt`**; match → atomic `os.replace` into place, mark `ready`. Timeouts + max-size guard on
  the HTTP stream via **`httpx` (promoted to a runtime dep — Finding 2, see §B.2)** using
  `client.stream("GET", url)`. Network egress happens **only** here and only on explicit request.
- `store.py` — persists `MODEL` rows through `db/` (status, resolved path, sha256, size, license).
  `require_ready(id)` returns the ready spec or raises a typed `ModelNotReady` the API maps to a
  clear 409/503 so the UI can prompt a download.
- `bundle.py` — offline import: given a local dir/zip, verify each file's SHA-256 against the pinned
  spec (no network), then promote. Reuses the same verify routine as the downloader.

SQLite access is **only** through `db/` (coding-standards): `db/schema.py` creates the `MODEL` and
`SETTING` tables (a minimal subset of the full M4 schema — just what M2 needs), opened WAL mode,
with a tiny migration guard. Route handlers never run raw SQL.

Error handling (concrete):

| Operation | Failure | Recoverable? | Caller receives | Logged |
|---|---|---|---|---|
| download file | network/timeout | yes (retry) | `status=downloading→error`, retry offered | warning + context |
| download file | SHA-256 mismatch | yes (retry) | `ChecksumMismatch` → 422/409, part deleted, row `corrupt` | error + expected/actual prefix (not full bytes) |
| bundle import | file missing in bundle | no (for that file) | `BundleIncomplete` listing missing names | error |
| bundle import | SHA-256 mismatch | no | `ChecksumMismatch` | error |
| require_ready | model absent | yes (download) | `ModelNotReady` → 409 | info |

### B.6 LaTeX normalize + validate (task 2.3) — KaTeX check decision

Module `engine/texora_engine/ensemble/latex.py` (the single-engine subset of the M5 ensemble dir):

- **Validate:** `pylatexenc`'s `LatexWalker` parses the string; a structural pass checks balanced
  `{}`, matched `\left`/`\right`, and matched `\begin{env}`/`\end{env}`. A failed parse or unbalanced
  structure → `RecognitionStatus.FAILED`.
- **Macro-support check — decision (Finding 5):** the engine does **not** spawn a browser or embed a
  JS VM in the Python sidecar (keeps the PyInstaller binary a single clean Python artifact and avoids
  a Node dependency in the frozen sidecar). Instead the engine validates against KaTeX's **supported
  command/environment surface** — a vendored allow-list — plus the structural parse above; any
  command outside the supported set → `validation=NEEDS_REVIEW`. The engine therefore asserts
  "**structurally valid + all macros within the KaTeX-supported set**", not "KaTeX rendered it" — it
  never claims a render it did not perform.
- **Allow-list provenance (no magic constant) — input source pinned with a verified fallback
  (resolves Finding 3).** The allow-list is **generated**, not hand-typed, so it cannot silently
  drift from the pinned `katex`. The script `scripts/gen_katex_allowlist.py` derives the supported
  command/environment names from the pinned **`katex@0.16.11`**, and the generator's **input is
  specified precisely — the design does NOT assume the installed npm `katex` package contains
  `src/functions`/`src/macros`** (the published npm dist typically ships only compiled artifacts:
  `katex.min.js`, `katex.mjs`, CSS, fonts). The generator uses, in order:
  1. **Primary — the installed package's public API / function registry.** Parse the supported
     functions from the shipped `katex.mjs` function registry (the public API surface that lists the
     registered functions/environments). This is a dist-only input, no source tarball needed.
  2. **Verified fallback — vendored pinned source tarball.** If the npm dist does **not** expose the
     support tables in a parseable form, **vendor the pinned `katex` SOURCE tarball** (a
     devDependency-only input, not the shipped dist) and parse its `src/functions`/`src/macros`
     support tables; **record the tarball's SHA-256** (same pin-at-adoption discipline as the model).
  The exact input path is **confirmed against the installed `katex@0.16.11` at implementation time**
  (pin-at-implementation discipline, same as the pix2tex pin) and recorded in
  `docs/m2-verification.md`. Either way the generator writes
  `engine/texora_engine/ensemble/katex_allowlist.json` with a header recording the katex version it
  was generated from (and, in the fallback path, the source-tarball SHA). The engine loads that JSON;
  a test asserts the file's recorded version matches the `katex` pin in `apps/desktop/package.json`,
  so bumping katex without regenerating the list fails CI rather than drifting. AC-5's "generated,
  cannot drift" property stays real — **no hand-typed list masquerading as generated**. To bound
  false flags (a too-strict list marking valid LaTeX as `needs_review`), the list is **generated from
  katex's own tables**, not guessed, and the authoritative render below is the real correctness gate.
- **Authoritative KaTeX render moves to the UI/vitest (Finding 5).** The real `katex` render check
  lives in a vitest test: it renders the committed fixture LaTeX (and the validator's golden cases)
  with the actual pinned `katex` and asserts `renderToString` throws no `ParseError` for the valid
  cases and does throw for the invalid ones. This is the ground truth; the engine's macro-surface
  check is a cheap pre-filter. The human-visible render in the Snip popup uses the same real `katex`,
  so the user always sees ground truth.
- **Spec erratum flagged.** R-REC-6 and the original FR-3/AC-5 wording ("a render check (KaTeX)" /
  "KaTeX render failure") describe something the engine does not do. FR-3/AC-5 are reworded below to
  match what the engine actually asserts; the authoritative katex render is relocated to vitest. This
  wording divergence from R-REC-6 is flagged to the spec owner as an erratum rather than quietly
  diverging — the *intent* (don't emit LaTeX that KaTeX can't render as confident) is fully met.
- **Normalize:** canonicalize `\dfrac`→`\frac` policy, collapse redundant spacing, prefer
  `\operatorname`/`\mathrm` forms — rule-based, each rule covered by a golden test asserting the
  normalized output still validates. Normalization never changes a valid expression into an invalid
  one (tested).

`validate_and_normalize(latex) -> tuple[str, RecognitionStatus]` returns the normalized string plus
the shared `RecognitionStatus` enum (`ok | needs_review | failed`, defined in `recognizers/base.py`
— Finding 8, not a local `Validation` enum). The snip route folds this into the `FormulaResult` so a
model output that fails validation downgrades `status` to `needs_review`/`failed` — never emitted as
confident (R-REC-6/8).

### B.7 `POST /recognize/snip` + `GET /hardware` (tasks 2.4, 2.6)

New router module `engine/texora_engine/api/recognize.py` and `hardware.py`, both mounted on
`protected_router` in `create_app` (so the bearer token is enforced identically to M1's
`/engine/info`). Pydantic I/O:

```python
class SnipRequest(BaseModel):
    image_base64: str = Field(description="PNG/JPEG bytes, base64; <= MAX_SNIP_BYTES decoded.")
    is_display: bool = True

class SnipResponse(BaseModel):
    latex: str
    confidence: float
    confidence_kind: str                 # token_logprob | unavailable (Finding 9)
    status: RecognitionStatus            # shared StrEnum (Finding 8)
    validation: RecognitionStatus        # shared StrEnum (Finding 8)
    mathml: str | None
    asciimath: str | None = None         # always null in M2; populated by M6 exporters (Finding 9)
    detail: str | None = None
```

Flow: validate/decode image (size + decoded-dimension guarded, see below) → `build_formula_recognizer()`
(cached singleton; model loaded once) → `recognize` → `validate_and_normalize` → compute MathML
(`latex2mathml`); `asciimath` is left `null` in M2 (deferred to M6 — Finding 9) → assemble
`SnipResponse`. On any recognizer/validation failure the
response is still 200 with `status=needs_review|failed` and empty `latex` (honesty rule); on bad
input it is a typed 4xx.

**Timeout + resource guard (Finding 7, R-SEC-3).** A bare `asyncio.wait_for` over a thread offload
*returns* on timeout but cannot cancel a running CPU-bound torch forward pass, so a hostile/large
image could pin a worker. The concrete guard is three-layered:
1. **Bound decoded dimensions before inference.** Byte size alone does not stop a decompression bomb
   (a tiny PNG can decode to a huge bitmap). After `Image.open`, reject when
   `width*height > MAX_SNIP_PIXELS` (config, e.g. 8 MP) or either side exceeds `MAX_SNIP_EDGE`
   (e.g. 5000 px) → 422, before any tensor work. Pillow's `Image.MAX_IMAGE_PIXELS` is also set as a
   decompression-bomb backstop. **Every Pillow decode/load call is wrapped so that
   `UnidentifiedImageError`, `DecompressionBombError`, or any other decoding exception is caught and
   returned as a typed 422 with a field detail — never surfaced as an unhandled 500 (NIT Finding 7),
   keeping failure isolation explicit at the route boundary.**
2. **Single-worker pool — inference is serialized (Finding 8).** Inference runs in a
   `ThreadPoolExecutor` with **`max_workers=1`** (`snip_concurrency=1` for M2). The cached singleton
   `Pix2TexFormulaRecognizer` wraps one shared torch module, and torch CPU `forward` on a shared
   module is **not** guaranteed concurrency-safe (the GIL does not protect native code), so two
   concurrent snips must never call the same model from two threads. With one worker the model is
   never entered re-entrantly; additional snips queue (**backpressure**) rather than racing. The
   executor still exists (rather than running inline) so the event loop stays responsive and the
   per-call timeout in step 3 can be applied to the future. (A size-1 pool is the deliberate M2
   choice over a lock around `forward`, because serializing is simpler and snip is inherently a
   one-at-a-time user action; a future page pipeline that wants parallel formula recognition will
   instantiate multiple model copies or a process pool, decided in M3/M4, not here.)
3. **Timeout returns a `failed` response.** `asyncio.wait_for` on the executor future enforces
   `SNIP_TIMEOUT_S` (config); on timeout the route returns a 200 `SnipResponse` with
   `status=failed`, `detail="recognition timed out"`, and the straggler thread is accounted for by
   the bounded pool (it finishes and frees its slot; the result is discarded). This is honest — a
   timed-out snip is reported as `failed`, never as a guess.

Input validation (each external input):

| Field | Rule | On failure |
|---|---|---|
| `image_base64` | required, valid base64, decodes to a PNG/JPEG Pillow can open, ≤ `MAX_SNIP_BYTES` (config, e.g. 8 MB) | 422 with field detail |
| decoded image | `width*height ≤ MAX_SNIP_PIXELS` and `max(width,height) ≤ MAX_SNIP_EDGE` (Finding 7) | 422 (decompression-bomb guard) |
| Pillow decode | any `Image.open`/`.load()` failure — `UnidentifiedImageError`, `DecompressionBombError`, or any other Pillow/decoding exception | **caught and returned as 422** with a field detail — **never a 500** (NIT Finding 7) |
| `is_display` | optional bool, default true | coerced/ignored |
| `device` (override route) | must be one of the detected device ids | 422 |
| bearer token | required (non-health route) | 401 (reuses `require_token`) |

**Hardware routes (Finding 10 — pinned in one place).**
- `GET /hardware` → `HardwareResponse { devices: list[Device], selected: str }`, where devices are
  computed from `torch.cuda.is_available()`, `torch.backends.mps.is_available()`, else CPU.
- `POST /hardware/device` with body `{ "device": str }` → `HardwareResponse`. It validates the
  device is in the detected set (**422 on an unknown device**), persists it to the `SETTING` table
  via `db/`, and the recognizer factory reads it on the next build. This is the single canonical
  spelling; FR-6 (`setDevice`) and design.md §5 (`GET /hardware`) both refer here. The client method
  `setDevice(device)` wraps the `set_device` Rust command, which proxies `POST /hardware/device`.

### B.8 No-mock / honesty in the production path (R-REC-8)

- The production code path calls the **real** `Pix2TexFormulaRecognizer`. The fixture unit test (AC-4)
  loads the real model and asserts a real LaTeX result; if the weights are not present on the host it
  **skips with an explicit reason** (`pytest.skip("pix2tex weights absent; run model prefetch")`) —
  it never substitutes a mock output to make the suite green. CI exercises this test only in a job
  that first prefetches the pinned weights (gated), so "no mock" holds end to end.
- Unit tests for the registry/validator/factory/route *plumbing* may use small local fixtures and a
  fake HTTP server for the downloader (testing the download/verify logic, not OCR) — that is allowed
  because it is not mocking OCR output. The line we never cross: no fabricated LaTeX stands in for
  model inference in any production or "passing OCR" path.

### B.9 Copy formats in the popup (LaTeX / MathML / Markdown) — OMML + AsciiMath decisions

- LaTeX: the normalized string.
- MathML: from `latex2mathml` (engine-provided in `SnipResponse.mathml`).
- Markdown: `$$ ... $$` wrapping of the LaTeX (display, `is_display=true`) / `$ ... $` (inline) —
  assembled in the UI from the LaTeX + the `is_display` hint (§B.4).

**AsciiMath is deferred from M2 (Finding 9).** The prior revision promised a populated
`SnipResponse.asciimath` and an "AsciiMath golden" test and added `export/asciimath.py`, but named
**no** LaTeX→AsciiMath library or conversion approach — only `latex2mathml` (LaTeX→MathML) is in the
stack table, and coding-standards forbids inventing an API. No permissive, maintained, pinnable
LaTeX→AsciiMath Python converter was identified for M2. Rather than invent one or hand-roll a lossy
converter under time pressure, `asciimath` is scoped to **`null` in M2** and its population is
**deferred to M6's exporters (R-EXP-3)** — exactly how OMML was deferred. This keeps the response
schema stable (the field exists) without shipping an unspecified/invented conversion. Consequently
there is **no AsciiMath golden test and no `export/asciimath.py` in M2**; M6 will choose the
converter (naming the dependency + adding its `docs/LICENSES.md` row) when the exporter suite lands.

**OMML copy is deferred from the M2 popup (Finding 4).** The v1 design planned to vendor and ship
Microsoft's `MML2OMML.XSL` stylesheet by default, asserting it is "Microsoft-redistributable" — but
with **no cited source**. That stylesheet historically ships inside Microsoft Office / the Windows
SDK, and its redistribution terms are **not clearly a permissive grant**; shipping it as a default
installer asset conflicts with permissive-first (R-LIC-1/2) and the verify-before-use rule. Three
options: (a) cite a concrete license that permits redistribution and record it in LICENSES.md; (b)
use a permissively-licensed MathML→OMML converter; or (c) drop OMML from the M2 snip popup. We choose
**(c)**: DOCX OMML is already scoped to **M6 (task 6.2)**, and §A.5 already defers "DOCX export beyond
the snip-popup OMML copy", so removing OMML-copy from the M2 popup is low-cost and avoids shipping an
unverified-license asset. M6 6.2 will make the OMML license decision deliberately (with a cited
source or a permissive converter) when DOCX export is designed. The M2 popup therefore offers
**LaTeX / MathML / Markdown** copy buttons; the OMML button and its i18n key land in M6.

Clipboard copy is done in the UI via the Tauri clipboard API routed through `engineClient` (the
client stays the only bridge importer). No `lxml` / Microsoft XSLT dependency is added in M2.

### B.10 Shell: global hotkey + screen capture (task 2.5, Rust side)

- `tauri-plugin-global-shortcut` registers **Ctrl+Shift+M** in `lib.rs` `setup`; the default is
  configurable (persisted in `SETTING`). On trigger it opens a lightweight transparent overlay
  window for region selection, then captures the selected monitor rectangle.
- **Screen capture decision:** use the **`xcap`** crate (Apache-2.0, cross-platform: Windows/macOS/
  Linux) to grab the monitor pixels, crop to the selected rect, encode PNG. Chosen over
  `screenshots`/platform-specific APIs because it is permissive, maintained, and cross-platform,
  matching the Windows-primary/macOS-Linux-secondary target. The PNG is base64'd and passed to the
  frontend via an `engine://snip-captured` event (Rust→JS), and the frontend sends it to
  `recognizeSnip` **through `engineClient`** — the capture itself is a shell/OS concern (correctly in
  Rust), while recognition stays in the engine.
- Capabilities: add a `global-shortcut:allow-register`/`unregister` scope limited to the app, the
  overlay window scope, **and `allow` entries for the new engine-proxy commands (`recognize_snip`,
  `get_hardware`, `set_device`, `model_status`, `model_download`) per §B.2a** to
  `capabilities/default.json`. No new network/HTTP capability — the authenticated HTTP call happens
  in Rust (`ureq`), not the webview.
- **Transport note (Finding 1, §B.2a):** the capture PNG does not go straight to the engine. It
  flows capture (Rust/`xcap`) → `engine://snip-captured` event → `engineClient.recognizeSnip` →
  `recognize_snip` Rust command → `ureq` + `Authorization: Bearer` → engine `POST /recognize/snip`.
  The supervisor holds the port+token; JS never sees them.

### B.11 Frontend: Snip popup, Settings/hardware, typed client (task 2.5, 2.6)

- `engineClient.ts` gains, **as `invoke`/`listen` wrappers over the §B.2a Rust commands** (not
  `fetch`), staying the **only** bridge importer:
  `recognizeSnip(pngBase64, isDisplay) -> SnipResult`, `getHardware() -> Hardware`,
  `setDevice(device) -> Hardware`, `modelStatus(id) -> ModelStatus`, `modelDownload(id) -> ModelStatus`,
  `subscribeSnipCaptured(cb)`, `subscribeModelProgress(cb)`. Types mirror the engine Pydantic models
  exactly (a shared TS types block), including the `RecognitionStatus` union
  `'ok' | 'needs_review' | 'failed'` (Finding 8), `confidenceKind` (Finding 9), and the
  `ModelProgress`/`ModelFileProgress`/`ModelDownloadState` mirror (§B.2b) carried by
  `subscribeModelProgress`.
- `SnipPopup.tsx`: shows LaTeX (Monaco or a read-only code box), a **KaTeX** live preview (the
  authoritative render — Finding 5), the confidence + validation badge (color by
  `ok|needs_review|failed`; shows "confidence unavailable" when `confidenceKind === 'unavailable'`),
  and copy buttons for **LaTeX / MathML / Markdown** (OMML deferred to M6 — Finding 4). All strings
  via i18next (`locales/id.json` default + `en.json`). Keyboard-first: Esc closes, Enter copies
  LaTeX, focus trap, ARIA live region for the result.
- `Settings` (hardware section): renders `getHardware()` and a device `<select>` calling
  `setDevice`; shows the "CPU mode is slower" note (R-HW-2) as an i18next string.
- A `needs_review`/`failed` result renders a clear "could not recognize — review" state, never a
  fabricated LaTeX (honesty surfaced in the UI).

**i18n keys enumerated + parity test (Finding 11).** M1's locales have `app`, `theme`, `engine`
namespaces. M2 adds exactly these keys to **both** `locales/id.json` (default) and `locales/en.json`:

```
snip.title            snip.copyLatex        snip.copyMathml       snip.copyMarkdown
snip.preview          snip.confidence       snip.confidenceUnavailable
snip.status.ok        snip.status.needsReview   snip.status.failed
snip.error.capture    snip.error.engineNotReady snip.error.timeout
snip.close            snip.hotkeyHint
hardware.title        hardware.device       hardware.selected     hardware.cpuSlowNote
hardware.override     hardware.deviceCpu    hardware.deviceCuda   hardware.deviceMps
```

(No `snip.copyOmml` in M2 — OMML is M6, Finding 4.) A new vitest `locales.test.ts` asserts
`Object.keys` of the recursively-flattened `id.json` and `en.json` are **identical sets**, so a
missing or extra translation fails CI (R-UI-10). This is the parity check M1 lacked.

### B.12 Testability

- **Unit (pytest):** Protocol/structural (AC-3); downloader checksum accept+reject with a fake HTTP
  server and a bad-hash fixture (AC-1); bundle import (AC-2); **adapter-constructed-with-weights-absent
  raises `ModelNotReady` and makes no network call** (Finding 3, networking stubbed to fail); LaTeX
  validate/normalize golden tests (AC-5); the katex-allowlist version-matches-pin test (Finding 5);
  hardware device-set logic with torch availability monkeypatched (AC-7); MathML golden. **No AsciiMath
  golden and no OMML golden in M2** (both deferred to M6 — Findings 9 and 4). Decoded-dimension/
  decompression-bomb rejection test (Finding 7); the factory **unknown-id** typed-error test (AC-3a,
  Finding 4).
- **Integration (pytest + TestClient):** `/recognize/snip` auth + fixture result (AC-6);
  `/hardware` get/override (AC-7). The real-model fixture test (AC-4) is the single test that loads
  weights (skip-with-reason if absent; gated-prefetch in CI).
- **Frontend (vitest):** `engineClient` wraps the right `invoke`/`listen` commands/events and stays
  the sole bridge importer (grep, as M1 — Finding 1); `SnipPopup` renders LaTeX + copy from i18next
  and the `needs_review` state renders the review message; the **real-`katex` render assertion**
  (Finding 5) over the fixture + golden LaTeX; the **id/en key-parity test** (Finding 11).
- **Rust (cargo test):** the §B.2a `engine_request` helper builds the correct URL + bearer header
  against a stub port (no real engine); shortcut registration; capture-encodes a known fixture buffer
  to PNG. The proxy commands' not-ready error path is unit-tested.
- **Hard-to-test / documented pending (host + interactive):** the **global hotkey firing**, the
  **live screen-region capture**, and the **on-screen popup** require a running `tauri dev` window +
  OS screen-capture permission. These are structurally covered (shortcut registration unit-tested in
  Rust; capture encodes a known fixture buffer to PNG in a unit test; the popup rendered in vitest
  with a stub capture), but their end-to-end live behavior is **confirmed manually** and recorded as
  pending in `docs/m2-verification.md`, consistent with M1's honest host-caveat handling. The
  ≤1.5 s R-UI-2 latency is a GPU target; CPU latency here is measured and documented, not claimed.

### B.13 Verification plan (maps to AC-10)

Engine (venv python): `ruff check .`, `black --check . --line-length 100`, `mypy texora_engine`,
`pytest -q` (the weight-dependent test skips cleanly if weights absent). Frontend:
`pnpm --filter desktop lint`, `pnpm --filter desktop test -- --run`, `pnpm --filter desktop build`.
Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (shortcut +
capture-encode unit tests) under a vcvars64 shell. OCR-affecting completion additionally runs the
benchmark smoke per steering once the real model is fetched. New temp files cleaned up. Every new
dependency + the model get a `docs/LICENSES.md` row in the same change (AC-9).

### B.14 Structurally verifiable vs. documented-pending (summary)

- **Structurally verifiable now:** registry/downloader checksum accept+reject, offline bundle import,
  adapter-no-network-when-weights-absent, Protocol shape + factory wiring, LaTeX validate/normalize +
  katex-allowlist-version check, MathML conversion (AsciiMath + OMML deferred to M6), `/recognize/snip`
  auth + Pydantic contract + decoded-dimension guard, `/hardware` get/override, the Rust proxy
  command/header plumbing, engineClient single-bridge invariant, real-katex render test, i18n id/en
  parity, lint/type/build.
- **Real-inference gated:** the real pix2tex image→LaTeX fixture test (runs where weights are
  prefetched; skip-with-reason otherwise — never mocked).
- **Documented pending (host/interactive):** global hotkey trigger, live screen-region capture,
  on-screen popup behavior, and CPU snip latency numbers — confirmed manually in a running window and
  recorded honestly in `docs/m2-verification.md`.

---

## Part C — File-level change map

Engine (new unless noted):
- `engine/texora_engine/recognizers/base.py` — Protocol + `RegionContext` + `FormulaResult`.
- `engine/texora_engine/recognizers/formula_pix2tex.py` — concrete adapter (real inference).
- `engine/texora_engine/recognizers/factory.py` — id→ctor registry + `build_formula_recognizer`.
- `engine/texora_engine/models/{registry,downloader,store,bundle,catalog}.py` — registry + verified
  download + offline import.
- `engine/texora_engine/models/progress.py` — `ModelProgress`/`ModelFileProgress`/
  `ModelDownloadState` (returned by `GET /models/{id}`, emitted on `engine://model-progress` — §B.2b).
- `engine/texora_engine/recognizers/base.py` — also defines the shared `RecognitionStatus` StrEnum.
- `engine/texora_engine/ensemble/latex.py` — validate + normalize + KaTeX-supported-macro check.
- `engine/texora_engine/ensemble/katex_allowlist.json` — generated allow-list (Finding 5).
- `engine/texora_engine/export/mathml.py` — MathML conversion. **No `asciimath.py` and no OMML/XSLT
  in M2** — AsciiMath (Finding 9) and OMML (Finding 4) are both deferred to M6 exporters.
- `engine/texora_engine/db/{schema,models_dao,settings_dao}.py` — SQLite (WAL) `MODEL`+`SETTING`.
- `engine/texora_engine/api/{recognize,hardware,models}.py` — new routers on `protected_router`.
- `engine/texora_engine/app.py` — include new routers (edit).
- `engine/texora_engine/settings.py` — add `device`, `models_dir`, `db_path`, `max_snip_bytes`,
  `max_snip_pixels`, `max_snip_edge`, `snip_timeout_s`, `snip_concurrency` (edit).
- `engine/requirements.txt` — **move `httpx==0.28.1` here from requirements-dev.txt** (Finding 2) +
  add pinned deps (edit); `pyproject.toml` (edit); extend `scripts/build_engine.py` to collect torch
  **and httpx** (edit).
- `scripts/gen_katex_allowlist.py` — regenerate the allow-list from the pinned katex (new, Finding 5).
- `engine/tests/` — unit + integration + golden + committed formula image fixture.
- `pipeline.yaml` — add `stages.recognize.formula: pix2tex` (edit).

Shell / frontend (new unless noted):
- `apps/desktop/src-tauri/Cargo.toml` — add `tauri-plugin-global-shortcut`, `xcap` (edit; `ureq`
  already present).
- `apps/desktop/src-tauri/src/supervisor.rs` — store `port`+`token` in `SupervisorState`, add the
  `engine_request` authenticated-proxy helper (edit, Finding 1), and the **model-download poller**
  (in-flight id map + 500 ms `GET /models/{id}` poll emitting `engine://model-progress`, stop on
  terminal state — §B.2b).
- `apps/desktop/src-tauri/src/{lib.rs,snip.rs}` — register shortcut, overlay, capture→event, and the
  new `recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download` commands
  (edit/new, Finding 1).
- `apps/desktop/src-tauri/capabilities/default.json` — global-shortcut + overlay window scope + the
  new command `allow` entries (edit, Finding 1).
- `apps/desktop/src/engineClient.ts` — add `recognizeSnip`/`getHardware`/`setDevice`/`modelStatus`/
  `modelDownload` + capture/progress subscriptions, all as `invoke`/`listen` wrappers (edit).
- `apps/desktop/src/{SnipPopup,SettingsHardware}.tsx` + tests — popup + hardware UI.
- `apps/desktop/src/locales/{id,en}.json` — `snip.*`, `hardware.*` keys (edit); `locales.test.ts`
  parity test (new, Finding 11); real-katex render test (new, Finding 5).
- `apps/desktop/package.json` — add `katex`, `@tauri-apps/plugin-global-shortcut` (edit).

Docs:
- `docs/LICENSES.md` — rows for every new dep + the pix2tex model, and **move the `httpx` row from
  the dev/test table to the runtime table** (edit, same change — Finding 2).
- `docs/m2-verification.md` — real command output + documented-pending items (new, appended as tasks
  complete, mirroring `m1-verification.md`).

---

## Part D — Traceability

| Task | Requirements | Acceptance criteria |
|---|---|---|
| 2.1 registry+downloader | R-INST-2/3/4, R-LIC-1 | AC-1, AC-2, AC-9 |
| 2.2 adapter+default | R-REC-2/8, R-HW-2, R-LIC-2 | AC-3, AC-4 |
| 2.3 normalize+validate | R-REC-6/7 | AC-5 |
| 2.4 /recognize/snip | R-UI-2, R-SEC-2/3 | AC-6 |
| 2.5 snip UI | R-UI-2/10/11 | AC-8, (pending: hotkey/capture/popup) |
| 2.6 hardware+override | R-HW-1/3 | AC-7 |
| all | R-QA-3/4, R-SEC-1 | AC-10 |

---

## Responses to review findings (v4 — third review, user-settled resolutions)

Third-review verdict was CHANGES_REQUESTED (1 HIGH, 3 MEDIUM, plus NITs — see
`m2-design-review-v3.md`). The four blocking findings are resolved here with **user-settled, final
decisions** (not re-debated), plus the cheap NITs. The design was already faithful to the M1
codebase and strong on the passing invariants (Protocol+factory, no-mock/honesty, token-on-every-
route, SQLite-through-db/, single-typed-client, i18n parity, host-pending, no invented benchmarks);
those are **not** re-opened.

1. **HIGH Finding 1 — default model SHA-256 / URL / tag unpinned (RESOLVED, pin-on-first-fetch).**
   pix2tex (MIT code + MIT weights, CPU-runnable) **stays** the default. §B.3 now pins the SHA-256
   story explicitly as **pin-on-first-fetch**: pix2tex ships `weights.pth`/`image_resizer.pth` as
   GitHub release assets at `lukas-blecher/LaTeX-OCR` (tag like `v0.0.1`) with **no vendor-published
   checksum**, so we **bypass pix2tex's built-in auto-downloader**, drive the fetch through our own
   `models/` registry from the exact immutable per-tag release-asset URL, and on first fetch
   **download once, compute the SHA-256 ourselves, record it in `catalog.py`**, then verify every
   subsequent load **and** every offline-bundle import against that recorded hash. The honesty caveat
   (our hash of the upstream asset, not a vendor-signed checksum — an accepted, documented R-INST-2/3
   satisfaction for the provisional default; vendor-pinned / HF-revision is an M7 option) is stated
   in `docs/LICENSES.md` and `docs/m2-verification.md`. §B.3 states the coder **actually fetches the
   real assets, computes the real SHA-256, and bakes those real values into `catalog.py` — never an
   invented hash**, and uses the real URL/tag/filenames if they differ from the assumption. The
   offline-bundle path is the no-network install path (verifying the same recorded hash), **not** a
   best-effort fallback.

2. **MEDIUM Finding 2 — confidence contract left open (RESOLVED).** **AC-6** now asserts the contract
   **both ways**: usable scores → `confidence ∈ (0,1]`, `confidence_kind="token_logprob"`; otherwise
   `confidence==0.0`, `confidence_kind="unavailable"` **and the UI renders a "confidence unavailable"
   state asserted in vitest**. One sentence added: shipping `"unavailable"` is an accepted, documented
   R-REC-2 satisfaction for the provisional M2 default, and M7's benchmark-chosen engine is expected
   to restore a numeric score. No fabricated confidence values ever (§B.4 already enforces this).

3. **MEDIUM Finding 3 — katex allow-list generator input unverified (RESOLVED).** §B.6 no longer
   assumes the installed npm `katex` package contains `src/functions`/`src/macros`. The generator's
   input is pinned with a **verified fallback**: primary = parse supported functions from the
   installed package's public API / shipped `katex.mjs` function registry; fallback = if the npm dist
   does not expose the support tables, **vendor the pinned `katex` SOURCE tarball** (devDependency-only
   input) and **record its SHA**. The exact input path is confirmed against the installed
   `katex@0.16.11` at implementation time (same pin-at-implementation discipline as the model). AC-5's
   "generated, cannot drift" property stays real — no hand-typed list masquerading as generated.

4. **MEDIUM Finding 4 — model-download progress contract unspecified (RESOLVED).** New **§B.2b**
   defines the `ModelProgress` Pydantic model **and** its mirrored TS type
   (`{ id, state: 'downloading'|'verifying'|'ready'|'corrupt'|'error', bytesReceived, bytesTotal,
   files: [{name, received, total}], detail? }`), and specifies the supervisor's polling contract:
   `model_download(id)` registers the id with the supervisor poller, which polls `GET /models/{id}`
   at a **fixed 500 ms interval**, emits `engine://model-progress` carrying `ModelProgress` per poll,
   and **stops on a terminal state (`ready`/`corrupt`/`error`)**. FR-1's "bytes received/total per
   file and overall" is carried by `files[]` + `bytesReceived/bytesTotal`. File map + FR-1 +
   engineClient mirror updated.

**NITs applied (cheap):** (a) §B.4 `pipeline.yaml` — the implementer **replaces the ENTIRE commented
placeholder body** with the real config and **keeps the permissive-first comment**. (b) §B.4 factory
+ Protocol — the adapter **declares `model_ids`** and the factory resolves via `ctor.model_ids[0]`
rather than assuming `adapter.id == model.id`. (c) §B.7 route boundary — any Pillow
decode/`DecompressionBombError`/`UnidentifiedImageError` is **caught and returned as 422, never a
500** (added to the narrative and the input-validation table).

**Kept flagged, NOT silently applied (spec errata, as instructed):** tasks.md 2.2 still names
**PP-FormulaNet-S** as the provisional default (pix2tex supersedes it for M2 — flagged to the spec
owner, §B.3), and **R-REC-6's "render check (KaTeX)"** wording (the engine does a macro-surface
allow-list check + the authoritative real-`katex` render lives in vitest/UI — flagged, §B.6). These
are flagged to the spec owner, not edited into the spec here.

Any attempt to re-litigate the settled/passing items above is out of scope for this convergence pass.

## Responses to review findings (v3 — second review)

Second-review verdict was CHANGES_REQUESTED (1 HIGH, 4 MEDIUM, 4 NIT). Every finding is **addressed**
in this v3 revision (none backlogged, none ignored); all fixes stay inside M2 scope and align with
the original requirements. I re-read the M1 source to confirm the HIGH finding:
`supervisor.rs::spawn_engine` passes `--token` on argv **and** `TEXORA_ENGINE_TOKEN` via env, and
`capabilities/default.json` whitelists `--token [0-9a-f]+` on argv — the review is correct.

1. **HIGH — §B.2a env-only rationale misread the M1 source (addressed).** §B.2a now states the token
   is on argv **and** env today (with the actual `spawn_engine` snippet and the capability-validator
   whitelist) and that **M2 does not change this transport**. Decision 0 is reframed as strictly the
   **JS→engine seam** (webview never gets the port/token), and the decision's rationale no longer
   leans on a false env-only claim. Argv-hardening is called out as an explicit, separate,
   **out-of-M2-scope** sub-task (supervisor + capability validator + engine CLI + its own test) so no
   implementer assumes it is done or breaks the validator "restoring" env-only.

2. **MEDIUM — pix2tex weight-pin feasibility unverified (addressed).** §B.3 adds a **mandatory
   pre-registry feasibility check**: before any `models/` code, the implementer must confirm and
   record the exact PyPI version, the exact release tag, each asset's exact filename + direct
   immutable URL, and that the URL does not redirect/roll — updating `ModelSpec`/`ModelFile`/
   `catalog.py`/`file_path(...)` to the real shape if it differs, with offline-bundle import as the
   fallback distribution path. The "hash computed at adoption, never invented" rule is retained.

3. **MEDIUM — pipeline.yaml shape conflicts with the committed template (addressed).** §B.4 now
   pins an explicit `PipelineConfig`/`Stages`/`RecognizeStage` Pydantic schema, makes `recognize` a
   **map of sub-stages** (`formula`/`text`/`table`/`handwriting`), edits the committed `pipeline.yaml`
   (and its comment block) to that shape so M3 reuses it, and states the **key-absent** behavior
   (typed `FormulaStageNotConfigured`, never a silent default). The factory reads
   `load_pipeline_config().stages.recognize.formula`.

4. **MEDIUM — unknown factory id → opaque 500 (addressed).** §B.4's `build_formula_recognizer` no
   longer does `_REGISTRY[stage_id]`; it validates against `_REGISTRY` and raises a typed
   `UnknownEngineError(stage_id, known=...)` (logged via the shared logger), mapped by the route to a
   clear 500 naming the bad id + known ids. New **AC-3a** adds the unit test; B.12 lists it.

5. **MEDIUM — confidence assumes per-token logprobs; `is_display` effect unspecified (addressed).**
   §B.4 now **does not assume** pix2tex exposes per-token scores: the implementer must verify on the
   pin (probe recorded in `docs/m2-verification.md`); if unreachable, M2 ships
   `confidence_kind="unavailable"` and **M5's trigger keys off validation/status state** until a
   scoring engine lands — stated plainly, no implied working logprob path. `RegionContext.is_display`
   is pinned as a **passthrough that does not change recognition** (pix2tex has no inline/display
   switch); it only drives Markdown `$`/`$$` wrapping downstream, documented on the field and in §B.4.

6. **NIT — AC-5 allow-list false-positive boundary (addressed).** AC-5 now states allow-list false
   positives are acceptable (downgrade to `needs_review`, never fabricate), the vitest real-`katex`
   render is the sole correctness gate, and divergence fails **only** when the allow-list rejects a
   case the fixture golden marks valid.

7. **NIT — `model_download` sync/async contract (addressed).** §B.2a now states `model_download`
   **starts** the download and **returns immediately** with the initial `downloading` status;
   terminal state (`ready`/`corrupt`) + progress arrive via `engine://model-progress`. Cancel is
   explicitly out of M2 scope (M7 7.3); a killed `.part` is cleaned up on the next attempt.

8. **NIT — ThreadPoolExecutor torch thread-safety (addressed).** §B.7 sets **`snip_concurrency=1`**
   (`max_workers=1`): inference over the shared pix2tex module is serialized; extra snips queue
   (backpressure). The executor is retained only to keep the loop responsive and apply the per-call
   timeout. The choice (serialize vs. lock) and the rationale are documented.

9. **NIT — AsciiMath source unspecified (addressed).** `asciimath` is scoped to **`null` in M2** and
   deferred to **M6 exporters (R-EXP-3)** — matching the OMML deferral — because no permissive,
   pinnable LaTeX→AsciiMath converter was identified and coding-standards forbids inventing one. The
   field stays in the schema (stable contract); `export/asciimath.py` and the AsciiMath golden are
   **removed from M2**. §B.9, FR-4, `SnipResponse`, AC-6, B.12, B.14, and the file map updated.

Spec errata still flagged to the owner (unchanged from v2, not applied here): tasks.md 2.2
default-model wording (pix2tex supersedes PP-FormulaNet-S for M2) and R-REC-6's "render check (KaTeX)"
wording.

---

## Responses to review findings (v2 — first review)

Review verdict was CHANGES_REQUESTED (2 HIGH, 5 MEDIUM, 4 NIT). Every finding is **addressed** in
this revision (none backlogged, none ignored) — all fixes stay inside M2 scope and align with the
original requirements (permissive-first, honesty, loopback+token security, single-typed-client,
SQLite-through-db/, i18n). I re-read the M1 source (`supervisor.rs`, `lib.rs`, `engineClient.ts`,
`capabilities/default.json`, `requirements*.txt`, `docs/LICENSES.md`) and confirmed every assumption
the review relied on holds.

1. **HIGH — transport unspecified (addressed).** New §B.2a "DECISION 0" picks option (a): new Rust
   `#[tauri::command]`s (`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`)
   backed by the supervisor using the existing `ureq` crate with the bearer header; token+port stay
   in Rust; `engineClient` wraps those commands (no `fetch`); capture bytes flow JS→command→Rust→
   engine; new command `allow` entries added to `capabilities/default.json`. FR-5, AC-8, B.10, B.11,
   B.12 and the file map updated to match.

2. **HIGH — httpx dev-only (addressed).** Decided to promote `httpx==0.28.1` to a runtime dependency
   (over stdlib `urllib`): move it to `requirements.txt`, move its `docs/LICENSES.md` row into the
   runtime table, add it to the stack table (§B.2), and collect it in the PyInstaller spec. B.5 and
   the file map updated.

3. **MEDIUM — pix2tex auto-download (addressed).** §B.3/§B.4 now require the adapter to construct
   pix2tex with explicit registry-resolved local checkpoint/resizer paths, never the default-arg
   fetcher; a unit test asserts construction with weights absent raises `ModelNotReady` and makes no
   network call (networking stubbed to fail). B.12 lists the test.

4. **MEDIUM — MML2OMML.XSL unverified license (addressed).** Chose option (c): **drop OMML copy from
   the M2 popup** (DOCX OMML is already M6 6.2); no `lxml`/Microsoft-XSLT dependency or asset is
   shipped in M2. M6 will make the OMML license call with a cited source or a permissive converter.
   §B.9, the stack table, FR-5, B.11, B.14, and the file map updated; the `snip.copyOmml` i18n key is
   explicitly not in M2.

5. **MEDIUM — "KaTeX render check" surrogate mislabeled (addressed).** FR-3/AC-5 reworded to what the
   engine actually asserts (structurally valid + macros within the KaTeX-supported set); the
   authoritative real-`katex` render moved to a vitest test. §B.6 specifies the allow-list is
   **generated** by `scripts/gen_katex_allowlist.py` from the pinned katex, stored with its version,
   and a test fails CI if it drifts from the `katex` pin. R-REC-6's literal wording is flagged to the
   spec owner as an erratum.

6. **MEDIUM — silent default-model swap (addressed).** §B.3 now states explicitly that pix2tex
   supersedes tasks.md 2.2's provisional PP-FormulaNet-S for M2 (PP-FormulaNet-S/UniMERNet remain M7
   candidates) and flags the matching tasks.md 2.2 edit to the spec owner.

7. **MEDIUM — timeout cannot cancel CPU work; no decompression-bomb guard (addressed).** §B.7 now
   specifies a three-layer guard: bound decoded dimensions/area before inference (new input-validation
   rule + `MAX_SNIP_PIXELS`/`MAX_SNIP_EDGE`), a bounded `ThreadPoolExecutor` so a stuck call degrades
   to backpressure, and a timeout that returns a `failed` `SnipResponse` with the straggler accounted
   for by the pool. New settings added to the file map.

8. **NIT — stringly-typed status (addressed).** A shared `RecognitionStatus` StrEnum is defined in
   `recognizers/base.py` and reused by `FormulaResult`, the validator (`validate_and_normalize`
   returns it), and `SnipResponse.status`/`.validation`; mirrored as a TS union in `engineClient`.

9. **NIT — pix2tex confidence undefined (addressed).** §B.4 specifies `confidence` =
   `exp(mean token logprob)` with `confidence_kind="token_logprob"`; when no score is available the
   adapter reports `confidence=0.0`, `confidence_kind="unavailable"`, and a `detail`, never a fake
   number. `confidence_kind` added to `SnipResponse`.

10. **NIT — device route name inconsistent (addressed).** Pinned once in §B.7: `POST /hardware/device`
    with body `{device: str}` → `HardwareResponse`, 422 on an unknown device; FR-6, the client
    `setDevice`, and design.md §5 all reference this spelling.

11. **NIT — i18n keys not enumerated / no parity check (addressed).** §B.11 enumerates the new
    `snip.*`/`hardware.*` keys and adds a vitest `locales.test.ts` asserting identical flattened key
    sets for `id.json` and `en.json`.

Spec errata flagged to the owner (not applied in this design): tasks.md 2.2 default-model wording
(Finding 6) and R-REC-6's "render check (KaTeX)" wording (Finding 5).
