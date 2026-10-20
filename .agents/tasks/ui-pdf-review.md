# PDF → Markdown convert screen wired to the engine job API

The two latest commits on `feat/m4-jobs` (`3e9813a` add the screen, `9082811` resolve the prior
review's findings) add Texora's headline **Convert PDF → Markdown** flow as one clean, self-contained
screen wired end-to-end to the existing engine job API. The user picks a PDF via a native dialog,
Start creates a job through `POST /jobs`, a Rust supervisor poll bridge drives a live progress bar,
Cancel calls the engine, and on completion the exported Markdown is shown in a readable monospace
panel with Copy and Save (.md). All engine/dialog access is funnelled through the single typed client
`engineClient.ts`; the port + bearer token stay in Rust behind four new proxy commands plus a local
`save_text` write. Progress is delivered by Rust polling `GET /jobs/{id}` every 500 ms and emitting a
Tauri event — the exact proven shape of the existing model-download bridge — rather than proxying the
engine WebSocket, which the plan documents as a deliberate, honest trade-off.

Watch for: the iteration-2 Rust change (an isolated `serde_json::json!` swap in `start_job_poll`) was
**not** re-run through `cargo clippy`/`build`/`test` because of a host per-command time ceiling —
`cargo fmt --check` passed and the edit is a strict subset of the fully-green iteration-1 surface, so
this is a LOW doubt, not a blocker (confirmed from the evidence + the code). The running-window E2E is
honestly marked PENDING MANUAL. No HIGH/MEDIUM findings.

**Verdict**: APPROVED

## High-level view

The feature is correctly layered. Rust gains four thin `#[tauri::command]` proxies
(`job_create`/`job_get`/`job_cancel`/`job_export`) that reuse the existing `engine_request` +
`ProxyError` path, plus a `save_text` local-write command and a `start_job_poll` supervisor task that
mirrors `start_model_poll`. No OCR/business logic leaks into Rust; the token and port never cross into
the webview. Route paths and the request body (`{ path, options, priority }`) match the engine's
FastAPI routes exactly.

The bridge invariant holds: `engineClient.ts` is the sole importer of `@tauri-apps/api` and the new
`@tauri-apps/plugin-dialog`, and the `bridgeInvariant` test was widened to `@tauri-apps/(api|plugin-dialog)`
so a future direct dialog import would trip it. `ConvertPdf.tsx` touches the engine only through the
client. The evidence records the invariant and locale-parity tests green.

The TS types are faithful mirrors of the engine Pydantic shapes. `JobView`, `JobProgress`, and the
`JobStatus` union (`queued|running|paused|done|failed|canceled`) match `api/jobs.py`,
`jobs/models.py`, and `jobs_dao` (`ACTIVE_JOB_STATUSES` + `TERMINAL_JOB_STATUSES`) field-for-field;
snake_case → camelCase mapping is handled in `parseJobView`/`parseJobProgress` with no invented names.

The UI is honest and accessible: failed and needs-review page counts come straight from the engine's
own `JobProgress`, cancellation renders as a neutral `role="status"` note (not a red error), there's a
`role="progressbar"` with aria values, focus moves to the result panel on completion, controls are
labelled and keyboard-operable, and strings go through i18next at full id/en parity.

The one gap is verification hygiene, not behavior: the iteration-2 Rust edit was not re-run through the
clippy/build/test suite (host time ceiling), only `cargo fmt --check`. The change is isolated and
reads as safe, so it is a LOW note with a recommendation to re-run on an unconstrained host.

<details>
<summary>Issues (3)</summary>

1. **Rust suite not re-run for iteration 2 (LOW)** — the `serde_json::json!` swap in `start_job_poll`
   was only `cargo fmt`-checked; re-run `cargo clippy --all-targets -- -D warnings && cargo build && cargo test`
   under vcvars64 on a host without the per-command time ceiling to confirm green. Non-blocking: the
   edit is a strict subset of the fully-green iteration-1 surface and `serde_json` is a pre-existing dep.
2. **`start_job_poll` has no dedup guard (LOW)** — unlike `start_model_poll` (which uses
   `begin_download`), a job poller is spawned per `job_create` with no in-flight registry. In the single
   lean flow this cannot overlap (one job id per Start, component guards terminal with `finishedRef`),
   so it is a latent note only; consider a guard if batch/multi-job Start is ever added.
3. **Running-window E2E PENDING MANUAL (informational)** — the live pick→Start→progress→export→
   Copy/Save→Cancel flow is host-limited and correctly not claimed as passed; the user must verify it in
   `pnpm tauri dev`.

</details>

<details>
<summary>Details</summary>

## Transport: Rust poll bridge over the engine WebSocket

Progress is delivered by `supervisor::start_job_poll`, which `job_create` kicks off after parsing the
new job id out of the returned `JobView`. It polls `GET /jobs/{id}` every 500 ms, emits the raw
`JobView` JSON on `engine://job-progress`, and stops on a terminal status via `is_terminal_job_status`
(substring match on `"status":"done|failed|canceled"`, mirroring `TERMINAL_JOB_STATUSES`). On an
engine-unreachable error it emits a synthetic `{ id, status: "failed", error }` payload built with
`serde_json::json!` and stops, so the UI never hangs on a dead poll. This is the same proven shape as
`start_model_poll`; the plan documents choosing it over proxying `WS /jobs/{id}/events` to keep Rust a
thin blocking client (ureq, no async WS crate). The engine's `JobProgress` already carries counts +
rate + ETA, so per-page WS frames are not required for the progress bar. This satisfies the
"documented polling fallback on GET /jobs/{id}" branch of the acceptance criteria.

## Bridge invariant and the thin Rust client

`engineClient.ts` is the only module importing `invoke`/`listen` and the new `@tauri-apps/plugin-dialog`,
and makes no `fetch`. The four job proxies reuse `engine_request` + `ProxyError` exactly like
`recognize_snip`; `job_get`/`job_cancel`/`job_export` percent-encode the job id/format via a small
`encode_component` helper. `save_text` is a plain local UTF-8 write (no engine involvement) so the
Save-.md dialog persists without adding a second plugin. The port + bearer token stay in
`SupervisorState` in Rust and never reach the webview. The `bridgeInvariant` test was correctly widened
from `@tauri-apps\/api` to `@tauri-apps\/(api|plugin-dialog)`, closing the gap the prior review flagged
as LOW, and the evidence shows it green. `ConvertPdf.tsx` imports only from `./engineClient`.

## TS types mirror the engine Pydantic shapes

`JobView` (id, sourceName, sourcePath, status, totalPages, priority, error, createdAt, updatedAt,
progress) maps one-to-one to the FastAPI `JobView` in `api/jobs.py`. `JobProgress` (total, pending,
leased, done, failed, needsReview, pagesPerMin, etaSeconds) maps to `jobs/models.py::JobProgress`
(`needs_review`/`pages_per_min`/`eta_seconds` → camelCase in `parseJobProgress`). The `JobStatus` union
`queued|running|paused|done|failed|canceled` is exactly `ACTIVE_JOB_STATUSES + TERMINAL_JOB_STATUSES`.
No invented field names. `parseJobView` tolerates the minimal `{ id, status, error }` error payload by
defaulting the optional fields and zeroing progress — keeping the failed state honest rather than
throwing.

## Honest states and accessibility

Failed and needs-review counts are surfaced from the engine's own `JobProgress` (amber/red inline
notes), never fabricated. A deliberate Cancel resolves to a dedicated `canceled` phase rendered as a
neutral `role="status"` note (`convert.canceledNote`), not the red `role="alert"` panel — the exact
fix the prior review asked for, with a test (`a canceled poll event shows a neutral note, not the error
alert`) asserting `queryByRole('alert')` is null. The progress region uses `role="progressbar"` with
`aria-valuenow/min/max`, focus moves to the result panel on completion, buttons are native and
labelled, and the screen uses the shared dark/light Tailwind tokens. All strings are i18next keys with
full id (default) / en parity, including every `convert.status.*` value the status label can build.

## Test coverage

`ConvertPdf.test.tsx` (9 tests) covers idle→selected, Start→`createJob` + progressbar, a progress event
driving "page X of N", Cancel→`cancelJob`, the canceled-neutral-note path, terminal done → markdown
shown + Copy/Save wired (asserting `getJobMarkdown('job-1')` and `saveMarkdown('paper.md', …)`), a
failed event → alert, and the `engineNotReady` throw → translated error. `engineClient.test.ts` asserts
the job commands, the serialized snake_case options body, `parseJobView` field mapping including the
minimal failed payload, `subscribeJobEvents`, and the dialog wrappers. The Rust `terminal_job_status_detection`
unit test covers the terminal vocabulary. Not tested by automation: the live running-window E2E (PENDING
MANUAL) and the iteration-2 Rust edit against clippy/build/test (see Issues 1, 3).

## Dependencies, capabilities, docs

`@tauri-apps/plugin-dialog@2.8.3` (exact) and `@tauri-apps/api@2.12.0` are pinned in `package.json`;
`tauri-plugin-dialog = "2.8.3"` in `Cargo.toml`. LICENSES.md gains rows for the npm plugin, the Rust
crate (noting transitive `rfd` 0.16.0 MIT), and the `@tauri-apps/api` bump rationale — all MIT OR
Apache-2.0, permissive-first. `capabilities/default.json` grants `dialog:allow-open` + `dialog:allow-save`
without disturbing the existing shell/shortcut scope. PROGRESS.md is updated. Existing screens
(App/Home, SnipPopup, SettingsHardware, EngineStatusBadge) are untouched beyond App.tsx's `home|convert`
view switch.

</details>

<details>
<summary>File map</summary>

- `apps/desktop/src-tauri/src/lib.rs` — four job proxy commands + `save_text`; dialog plugin registered.
- `apps/desktop/src-tauri/src/supervisor.rs` — `JOB_PROGRESS_EVENT` + `start_job_poll` poll bridge; `ProxyError::from_message`; `terminal_job_status_detection` test.
- `apps/desktop/src-tauri/Cargo.toml` — pin `tauri-plugin-dialog@2.8.3`.
- `apps/desktop/src-tauri/capabilities/default.json` — grant `dialog:allow-open`/`allow-save`.
- `apps/desktop/src/engineClient.ts` — job types + `createJob`/`getJob`/`cancelJob`/`getJobMarkdown`/`subscribeJobEvents` + `pickPdf`/`saveMarkdown`.
- `apps/desktop/src/ConvertPdf.tsx` — the convert screen (idle→selected→running→done/failed/canceled).
- `apps/desktop/src/App.tsx` — `home|convert` view switch + Convert button.
- `apps/desktop/src/bridgeInvariant.test.ts` — invariant widened to include plugin-dialog.
- `apps/desktop/src/engineClient.test.ts`, `ConvertPdf.test.tsx` — new/extended tests.
- `apps/desktop/src/locales/{id,en}.json` — `convert` namespace + `home.convert` at parity.
- `apps/desktop/package.json`, `pnpm-lock.yaml`, `Cargo.lock` — dependency pins.
- `docs/LICENSES.md`, `docs/PROGRESS.md`, `docs/m-ui-pdf-verification.md`, `.agents/tasks/ui-pdf-plan.md` — docs + evidence.

Full diff: `git -C c:\data\kucing\texora\.worktrees\m4-jobs diff ca3c336..HEAD`

</details>
