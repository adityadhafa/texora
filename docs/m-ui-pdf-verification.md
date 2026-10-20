# Verification — PDF → Markdown convert screen (feat/m4-jobs)

Evidence for the headline **Convert PDF → Markdown** UI wired end-to-end to the existing engine
job API. All commands were run on Windows (bash) with this PATH prefix exported first:

```
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

Rust commands additionally loaded `vcvars64.bat` (MSVC env) first.

## What was built

**Rust (thin client only — no business logic added):**

- `apps/desktop/src-tauri/src/lib.rs` — four new `#[tauri::command]` proxies mirroring the existing
  `recognize_snip`/`model_download` pattern (reuse `engine_request` + `ProxyError`):
  - `job_create(path, options_json, priority)` → `POST /jobs` with body
    `{ path, options: <parsed options_json>, priority }`; parses the new job `id` out of the returned
    `JobView` and kicks off the progress poll.
  - `job_get(id)` → `GET /jobs/{id}`.
  - `job_cancel(id)` → `POST /jobs/{id}:cancel`.
  - `job_export(id, format)` → `GET /jobs/{id}/export?format={format}` (raw body).
  - `save_text(path, contents)` — local UTF-8 file write so the Save-.md dialog persists the export
    without adding a second Tauri plugin. Query components are percent-encoded via a small helper.
- `apps/desktop/src-tauri/src/supervisor.rs` — `JOB_PROGRESS_EVENT = "engine://job-progress"` and
  `start_job_poll(app, job_id)`, mirroring `start_model_poll`: polls `GET /jobs/{id}` every 500 ms,
  emits the raw `JobView` JSON on `engine://job-progress`, and stops on a terminal status
  (`done`/`failed`/`canceled`, matching `jobs_dao.TERMINAL_JOB_STATUSES`) or on an engine-unreachable
  error (synthetic `{"id","status":"failed","error"}` payload so the UI never hangs). Added a
  `ProxyError::from_message` constructor for local validation/IO failures and a unit test
  `terminal_job_status_detection`.
- `apps/desktop/src-tauri/Cargo.toml` — pinned `tauri-plugin-dialog = "2.8.3"`; registered
  `tauri_plugin_dialog::init()` in the builder.
- `apps/desktop/src-tauri/capabilities/default.json` — granted `dialog:allow-open` +
  `dialog:allow-save`.

**TypeScript (single typed client stays the sole bridge importer):**

- `apps/desktop/src/engineClient.ts` — new `JobStatus`/`JobOptions`/`JobProgress`/`JobView` types
  (snake_case → camelCase), `parseJobView`, and wrappers `createJob`/`getJob`/`cancelJob`/
  `getJobMarkdown`/`subscribeJobEvents`, plus dialog helpers `pickPdf`/`saveMarkdown` (the only
  `@tauri-apps/plugin-dialog` importer; `bridgeInvariant` only forbids `@tauri-apps/api` + `fetch(`,
  and both remain confined to this module).
- `apps/desktop/src/ConvertPdf.tsx` — one clean screen: pick a PDF, Start → `createJob`, live
  progress bar + "page X of N" + status label + pages/min + ETA + honest needs-review/failed counts
  driven by `subscribeJobEvents`, a Cancel button, and on completion a scrollable monospace raw
  Markdown panel with Copy + Save (.md). Keyboard-operable, `role="progressbar"`, focus moved to the
  result panel on completion, dark/light theme tokens, all strings via i18next.
- `apps/desktop/src/App.tsx` — a `'home' | 'convert'` view switch; Home gets a "Convert PDF" button,
  the Convert view a "Back". Existing screens untouched.
- `apps/desktop/src/locales/{id,en}.json` — a `convert` namespace + `home.convert` at full key
  parity (id default, en provided).

**Progress transport note (honest):** progress is delivered by the Rust supervisor **polling**
`GET /jobs/{id}` every 500 ms and emitting a Tauri event — the exact proven shape of the existing
model-download bridge — rather than proxying the engine `WS /jobs/{id}/events`. This keeps Rust a
thin blocking client (ureq, no async WS crate) and is sufficient for a clean progress bar because
`JobProgress` already carries counts + rate + ETA. The engine WS endpoint remains available for a
future upgrade.

**Tests added:** `engineClient.test.ts` extended (job methods assert the serialized snake_case
options body + correct commands; `parseJobView` field mapping incl. the minimal failed poll payload;
`subscribeJobEvents`; `pickPdf`/`saveMarkdown`). New `ConvertPdf.test.tsx` covers idle→selected,
Start→running + progressbar, a progress event driving "page X of N", Cancel→`cancelJob`, terminal
done → markdown shown + Copy/Save wired, a failed event, and the `engineNotReady` error state.
`bridgeInvariant` + `locales` parity stay green.

## Commands + real output

### Frontend

`pnpm install`

```
Scope: all 2 workspace projects
...
Packages: +2
++
Done in 5.6s using pnpm v9.15.9
```

`pnpm --filter desktop lint`

```
> desktop@0.1.0 lint C:\data\kucing\texora\.worktrees\m4-jobs\apps\desktop
> eslint .
(exit 0, no findings)
```

`pnpm --filter desktop test -- --run`

```
 ✓ src/ConvertPdf.test.tsx (8 tests) 804ms
 ✓ src/App.test.tsx (2 tests) 302ms
 ✓ src/SnipPopup.test.tsx (6 tests) 428ms
 Test Files  9 passed (9)
      Tests  53 passed (53)
   Duration  5.31s
(exit 0)
```

(The `act(...)` stderr warnings come from the pre-existing App/SettingsHardware/EngineStatusBadge
tests, not the new suites.)

`pnpm --filter desktop build`

```
dist/assets/index-2-KfvR82.css   39.68 kB │ gzip:  10.88 kB
dist/assets/index-BBjVSjKf.js   481.77 kB │ gzip: 147.57 kB │ map: 1,603.32 kB
✓ built in 5.04s
(exit 0 — runs tsc -p tsconfig.json, tsc -p tsconfig.node.json, then vite build)
```

### Rust (`apps/desktop/src-tauri`, MSVC env via vcvars64)

`cargo fmt --check`

```
(exit 0 — clean after cargo fmt; re-ran `cargo fmt --check` → FMT_CLEAN)
```

`cargo clippy --all-targets -- -D warnings`

```
   Compiling tauri-plugin-dialog v2.8.3
    Checking ureq v2.12.1
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 21.92s
(exit 0 — no warnings)
```

`cargo build`

```
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1m 09s
(exit 0)
```

`cargo test`

```
running 15 tests
test supervisor::tests::terminal_job_status_detection ... ok
...
test result: ok. 15 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
(exit 0)
```

## Running-window E2E: PENDING MANUAL

The interactive flow in a live window is host-limited and MUST be verified by the user with
`pnpm tauri dev` (automation did not run any dev server / `tauri build` / PyInstaller sidecar).
Steps to verify manually, with the engine healthy (status badge "Ready"):

1. Home → click **Convert PDF to Markdown**.
2. **Choose PDF** → native dialog → pick a multi-page math PDF; the filename appears.
3. **Start conversion** → progress bar fills, "page X of N" + status update live; optional
   pages/min + ETA show once the engine reports them.
4. (optional) **Cancel** mid-run → status becomes "Canceled".
5. On completion the exported Markdown renders in the raw monospace panel; any failed /
   needs-review page counts are shown honestly.
6. **Copy Markdown** copies to the clipboard; **Save .md** opens the native save dialog and writes
   the file.
7. With the engine not yet ready, Start surfaces the "engine is not ready" message instead of
   hanging.

This checklist is **not** claimed as passed — it is pending manual confirmation by the user.

---

## Iteration 2 — review fixes (commit on feat/m4-jobs)

Addressed the three findings from `.agents/tasks/ui-pdf-review.json`:

- **[MEDIUM] Cancel no longer renders as an error.** `ConvertPdf.tsx` gained a distinct `canceled`
  terminal phase. `handleTerminal` now routes `job.status === 'canceled'` to a `canceled` dispatch
  instead of the `failed` branch, so the red `role="alert"` panel never shows for a deliberate
  cancellation. A neutral `role="status"` note (`convert.canceledNote`) is shown instead, while the
  status label keeps reading "Canceled". Added `convert.canceledNote` to both `id.json` and
  `en.json` at parity. New test `a canceled poll event shows a neutral note, not the error alert`
  drives a `canceled` poll event after Cancel and asserts the neutral note appears and
  `queryByRole('alert')` is null.
- **[LOW] bridgeInvariant now guards the dialog plugin.** The invariant regex was widened from
  `@tauri-apps\/api` to `@tauri-apps\/(api|plugin-dialog)`, so a future component importing the
  dialog plugin directly (bypassing `engineClient`) trips the test. Current code already compliant.
- **[LOW] Synthetic failed payload uses `serde_json::json!`.** In `supervisor.rs::start_job_poll`,
  the engine-unreachable fallback payload is now built with `serde_json::json!({...}).to_string()`
  instead of hand-formatting with quote-replacement, so any backslash/control char in the error
  message is always escaped into valid JSON.

### Commands + real output (iteration 2)

**Frontend — all green:**

`pnpm install`

```
Scope: all 2 workspace projects
Lockfile is up to date, resolution step is skipped
Already up to date
Done in 3s using pnpm v9.15.9
```

`pnpm --filter desktop lint`

```
> desktop@0.1.0 lint C:\data\kucing\texora\.worktrees\m4-jobs\apps\desktop
> eslint .
(exit 0, no findings)
```

`pnpm --filter desktop test -- --run`

```
 ✓ src/App.test.tsx (2 tests) 225ms
 ✓ src/ConvertPdf.test.tsx (9 tests) 684ms
 ✓ src/SnipPopup.test.tsx (6 tests) 343ms
 Test Files  9 passed (9)
      Tests  54 passed (54)
   Duration  4.74s
(exit 0)
```

(ConvertPdf is now 9 tests, up from 8 — the new canceled-state test. Total 54, up from 53.)

`pnpm --filter desktop build`

```
dist/assets/index-eZNcLXBN.css   39.74 kB │ gzip:  10.89 kB
dist/assets/index-BbAH0txC.js   482.21 kB │ gzip: 147.66 kB │ map: 1,604.28 kB
✓ built in 3.75s
(exit 0 — tsc + vite build)
```

**Rust:**

`cargo fmt --check`

```
(exit 0 — clean)
```

`cargo clippy --all-targets -- -D warnings` / `cargo build` / `cargo test` — **NOT RE-RUN THIS
ITERATION (host time limit).** A cold Tauri compile exceeded this host's maximum per-command time
ceiling (~29 min) on every attempt without producing output, so the clippy/build/test suites could
not be re-run for the iteration-2 edit. What was verified:

- `cargo fmt --check` passed clean (exit 0).
- The only Rust change is an isolated edit inside the existing `start_job_poll` function: replacing
  a hand-built JSON string with `serde_json::json!({ "id": job_id, "status": "failed", "error":
  err.message }).to_string()`. `serde_json` is already a direct dependency of the crate (used in the
  `supervisor.rs` tests, e.g. `serde_json::to_string(&status)`), and both `job_id` and `err.message`
  are `String` values valid as serde JSON values. No new dependency, no signature change, no new
  public item.

The iteration-1 Rust evidence above (clippy clean, build OK, 15 tests passing incl.
`terminal_job_status_detection`) remains the last recorded green Rust run; this iteration's Rust
change is a strict subset of that surface. **The reviewer / user should re-run the Rust suite
(`cargo clippy --all-targets -- -D warnings && cargo test` under vcvars64) to confirm on a host
without the time ceiling.**

The running-window E2E remains **PENDING MANUAL** (unchanged from iteration 1); add a mid-run
**Cancel** check to the checklist and confirm the screen shows a neutral "Conversion canceled" note
with no red error alert.
