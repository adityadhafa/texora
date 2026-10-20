# Implementation Plan — PDF → Markdown convert screen (feat/m4-jobs)

Goal: one clean, simple "Convert PDF" screen for the Texora desktop app, wired end-to-end to the
EXISTING engine job API (`POST /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}:cancel`,
`GET /jobs/{id}/export?format=md`, and the `WS /jobs/{id}/events` progress stream). No batch/queue
manager, no redesign of existing screens. The port + bearer token stay in Rust; the UI only ever
calls `invoke` + `listen` through the single typed client `src/engineClient.ts`.

## Design decisions (made here, grounded in the code I read)

- **File picking + saving: use the official Tauri dialog plugin** (`@tauri-apps/plugin-dialog` +
  the `tauri-plugin-dialog` Rust crate), not drag-drop. Rationale: the feature needs a native
  **Save .md** dialog anyway (drag-drop cannot choose a save path), so one plugin covers both
  open-PDF and save-markdown with the standard native UX. The plugin JS API is called from
  `engineClient.ts` only (it is `@tauri-apps/plugin-dialog`, a Tauri-bridge module), so the bridge
  invariant test — which only forbids `@tauri-apps/api` imports and `fetch(` outside
  `engineClient.ts` — stays green; still, to keep the "UI never touches the bridge" spirit, the
  open/save calls are wrapped behind thin `engineClient` helpers.
- **Version alignment:** `@tauri-apps/plugin-dialog@2.8.3` depends on `@tauri-apps/api ^2.12.0`, but
  the repo pins `@tauri-apps/api@2.9.0`. Bump `@tauri-apps/api` to `2.12.0` (compatible with the
  pinned `tauri@2.12.4` crate) so the peer resolves cleanly. Pin `@tauri-apps/plugin-dialog@2.8.3`
  and the Rust `tauri-plugin-dialog@2.8.3` (both MIT OR Apache-2.0, matching `max_stable_version`
  verified on npm + crates.io). All pins; no ranges.
- **Progress transport: WS events bridge in Rust, mirroring the `engine://model-progress` pattern,
  with a polling fallback.** The existing model-progress bridge already polls `GET /models/{id}`
  every 500 ms and emits a Tauri event; I reuse that exact, proven shape by polling
  `GET /jobs/{id}` every 500 ms and emitting `engine://job-progress` with the raw `JobView` JSON,
  stopping on a terminal status. This avoids adding a WS client crate to Rust (ureq is blocking,
  no async WS), keeps Rust thin, and is honest about being a poll. The engine's `JobProgress`
  already carries everything the UI needs (counts, pages_per_min, eta_seconds), so per-page WS
  frames are not required for a clean progress bar. Terminal job statuses to stop on:
  `done`, `failed`, `canceled` (plus treat `paused` as non-terminal). Confirm the exact terminal
  vocabulary from `jobs_dao.TERMINAL_JOB_STATUSES` while implementing step 1.
- **Completion render: raw Markdown in a clean monospace panel, NOT KaTeX.** The export body is a
  full Markdown document (many `$$…$$` blocks), not a single formula; rendering a whole MD doc with
  KaTeX is scope creep for a tight budget. Show the raw `.md` in a readable, scrollable monospace
  `<pre>` with Copy + Save. (KaTeX stays where it already is: the snip popup.)
- **Navigation: a tiny in-`App` view switch (`'home' | 'convert'`) via `useState`.** No router
  dependency for two screens. Home gets a "Convert PDF" button; the Convert view gets a "Back".
- **State store: local `useState`/`useReducer` in the Convert view.** The screen is self-contained;
  pulling in Zustand/TanStack Query for one screen is over-engineering for this budget. (The
  coding-standard mentions them as options, not mandates; the existing screens also use plain
  hooks.)

All verification commands assume this PATH prefix is exported first (Windows bash):

```
export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

Rust steps additionally require loading `vcvars64.bat` first (MSVC env). Do NOT run `tauri dev`,
`vite dev`, `tauri build`, or build the PyInstaller sidecar. The interactive running-window E2E is
host-limited → mark PENDING MANUAL, never claim it passed.

---

- [ ] 1. Add the dialog plugin + four job proxy commands + a job-progress poll bridge in Rust (thin client only).
      In `apps/desktop/src-tauri/Cargo.toml` add `tauri-plugin-dialog = "2.8.3"`. In `src/lib.rs`:
      register `.plugin(tauri_plugin_dialog::init())`; add `#[tauri::command]` functions
      `job_create(path, options_json, priority)` → `engine_request POST /jobs` with body
      `{ "path", "options": <options>, "priority" }`, `job_get(id)` → `GET /jobs/{id}`,
      `job_cancel(id)` → `POST /jobs/{id}:cancel`, `job_export(id, format)` →
      `GET /jobs/{id}/export?format={format}` (all returning the raw body `String`, reusing
      `engine_request` and `ProxyError` exactly like `recognize_snip`); add all four to
      `invoke_handler!`. In `src/supervisor.rs` add `pub const JOB_PROGRESS_EVENT:
      &str = "engine://job-progress";` and `start_job_poll<R>(app, job_id)` that mirrors
      `start_model_poll` — poll `GET /jobs/{id}` every 500 ms, `app.emit(JOB_PROGRESS_EVENT, body)`,
      stop when the JSON `status` is terminal (`done`/`failed`/`canceled`; verify against
      `jobs_dao.TERMINAL_JOB_STATUSES`), and on `engine_request` error emit a synthetic
      `{"id":…,"status":"failed",…}` payload then stop (same self-healing shape as the model poll).
      Have `job_create` call `supervisor::start_job_poll(app, <new id>)` after a successful create
      (parse the id out of the returned JSON in Rust with `serde_json`, which is already a dep).
      Keep ALL business logic out of Rust. Add a `#[cfg(test)] mod tests` unit for a
      `is_terminal_job_status`/terminal-detection helper, following the existing
      `terminal_model_state_detection` test.
      Files: `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/src/lib.rs`,
      `apps/desktop/src-tauri/src/supervisor.rs`
      Verify: load vcvars64, then from `apps/desktop/src-tauri`:
      `cargo fmt --check` && `cargo clippy --all-targets -- -D warnings` && `cargo build` &&
      `cargo test` — all pass, new terminal-detection test green.

- [ ] 2. Grant the dialog capability.
      In `apps/desktop/src-tauri/capabilities/default.json` add the permissions
      `"dialog:allow-open"` and `"dialog:allow-save"` to the `permissions` array (keep the existing
      shell/global-shortcut scope untouched). This is required or the open/save dialog calls are
      rejected at runtime.
      Files: `apps/desktop/src-tauri/capabilities/default.json`
      Verify: part of step 1's `cargo build` (Tauri regenerates the permission manifest at build);
      confirm the build still succeeds after the edit. (Runtime dialog behavior = PENDING MANUAL.)

- [ ] 3. Add job types + typed-client wrappers in `engineClient.ts` (the SOLE invoke/listen/dialog importer).
      Add TS interfaces mirroring the engine exactly (snake_case → camelCase):
      `JobOptions { formats: string[]; dpi?: number; pageStart?: number; pageEnd?: number;
      pages?: number[] }`, `JobProgress { total; pending; leased; done; failed; needsReview;
      pagesPerMin: number | null; etaSeconds: number | null }`,
      `JobView { id; sourceName; sourcePath; status; totalPages; priority; error: string | null;
      createdAt; updatedAt; progress: JobProgress }`, and a `JobStatus` string union
      (`'pending' | 'running' | 'paused' | 'done' | 'failed' | 'canceled'` — confirm against the
      engine while implementing). Add `parseJobView(json)` (maps `source_name`→`sourceName`,
      `needs_review`→`needsReview`, `pages_per_min`→`pagesPerMin`, `eta_seconds`→`etaSeconds`,
      etc.). Add wrappers: `createJob(path, options?, priority?)` → `invoke('job_create', { path,
      optionsJson: JSON.stringify(engineOptions), priority })` (serialize camel→snake for the body:
      `page_start`/`page_end`), `getJob(id)` → `invoke('job_get', { id })`, `cancelJob(id)` →
      `invoke('job_cancel', { id })`, `getJobMarkdown(id)` → `invoke<string>('job_export', { id,
      format: 'md' })` (returns the raw markdown string), and
      `subscribeJobEvents(callback: (job: JobView) => void)` →
      `listen('engine://job-progress', e => callback(parseJobView(e.payload)))`. Also add dialog
      wrappers `pickPdf(): Promise<string | null>` (open dialog, single file, filter
      `{ name:'PDF', extensions:['pdf'] }`) and `saveMarkdown(defaultName, contents): Promise<boolean>`
      (save dialog `.md` filter, then write via the plugin's `writeTextFile`? — NO: the dialog
      plugin only returns a path; write the file through a thin Rust `save_text` command OR use
      `@tauri-apps/plugin-fs`. To avoid a second new plugin, add a Rust `#[tauri::command]
      save_text(path, contents)` in step 1 scope IF simpler; otherwise return the chosen path and
      write via the engine is NOT allowed. DECISION: add `save_text` Rust command — fold into step 1
      and expose `saveMarkdown` here calling `invoke('save_text', { path, contents })`). Bump
      `@tauri-apps/api` to `2.12.0` and add `@tauri-apps/plugin-dialog@2.8.3` in
      `apps/desktop/package.json`.
      Files: `apps/desktop/src/engineClient.ts`, `apps/desktop/package.json`
      (and the `save_text` command noted back into step 1's `lib.rs`)
      Verify: `pnpm install` then `pnpm --filter desktop test -- --run` (after step 5 adds the
      client tests) — for now `pnpm --filter desktop lint` && `pnpm --filter desktop build` pass
      (typecheck clean).

- [ ] 4. Build the `ConvertPdf` view component and wire it into `App.tsx` from Home.
      Create `apps/desktop/src/ConvertPdf.tsx`: a single clean screen matching the existing Tailwind
      tokens (`bg-bg`/`bg-surface`/`text-fg`/`text-muted`/`border-muted/40`/`focus-visible:ring-accent`,
      same button classes as `App.tsx`/`SnipPopup.tsx`). States (use a small `useReducer` or typed
      `useState` union): `idle` (big "Choose PDF" button → `pickPdf()`), `selected` (show filename +
      "Start" + "Choose different"), `running` (progress bar from `progress.done/progress.total`,
      "page X of N" using `done`/`total`, status label, optional pages/min + ETA when non-null, a
      "Cancel" button → `cancelJob(id)`), `done` (fetch markdown via `getJobMarkdown(id)`, show it in
      a scrollable monospace `<pre>`, "Copy Markdown" → `navigator.clipboard.writeText`, "Save .md" →
      `saveMarkdown(sourceName.replace(/\.pdf$/i,'.md'), markdown)`, plus honest `needs_review`/
      `failed` page counts surfaced from the final `JobProgress`), and `failed`/`error` (clear message
      from `JobView.error` or a translated "engine not ready" when `createJob` throws `engineNotReady`).
      Subscribe to `subscribeJobEvents` on start, unsubscribe on unmount/back; keep the latest
      `JobView` in state; when it becomes terminal, transition to `done`/`failed`. Accessibility:
      labelled controls, keyboard-operable buttons, `role="progressbar"` with
      `aria-valuenow/valuemin/valuemax`, focus moved to the result panel on completion, works in
      dark/light. All strings via `t(...)` (step 6). In `App.tsx` add a `view` state
      (`'home' | 'convert'`), a "Convert PDF" button on Home that sets `'convert'`, and render
      `<ConvertPdf onBack={() => setView('home')} />` when active (Back button inside the view).
      Components NEVER import `invoke`/`listen`/dialog directly — only through `engineClient`.
      Files: `apps/desktop/src/ConvertPdf.tsx`, `apps/desktop/src/App.tsx`
      Verify: `pnpm --filter desktop lint` && `pnpm --filter desktop build` pass; full test pass in
      step 5.

- [ ] 5. Add vitest tests for the client job methods, the dialog wrappers, and the ConvertPdf view states.
      In `apps/desktop/src/engineClient.test.ts` (extend) mock `@tauri-apps/api/core` + `/event` and
      `@tauri-apps/plugin-dialog`; assert `createJob` invokes `job_create` with the serialized
      snake_case options body, `getJob`/`cancelJob`/`getJobMarkdown` invoke the right commands,
      `parseJobView` maps every snake_case field, and `subscribeJobEvents` listens on
      `engine://job-progress` and forwards a parsed `JobView`. Create
      `apps/desktop/src/ConvertPdf.test.tsx` (mock `./engineClient` module) covering: idle→selected
      after `pickPdf`, Start calls `createJob` and shows running, a `subscribeJobEvents` callback
      drives the progress bar + "page X of N", Cancel calls `cancelJob`, terminal `done` fetches +
      shows markdown and Copy/Save are wired (assert `getJobMarkdown`/`saveMarkdown` called), and a
      `failed` event / `engineNotReady` throw shows the error state. The existing
      `bridgeInvariant.test.ts` must stay green (ConvertPdf must not import the bridge/dialog
      directly — only `engineClient`).
      Files: `apps/desktop/src/engineClient.test.ts`, `apps/desktop/src/ConvertPdf.test.tsx`
      Verify: `pnpm --filter desktop test -- --run` — all tests pass including `bridgeInvariant`.

- [ ] 6. Add i18next strings for BOTH `id` (default) and `en` with full key parity.
      Add a `convert` namespace to `apps/desktop/src/locales/id.json` and `en.json` with identical
      key sets, e.g. `convert.title`, `convert.open`, `convert.chooseDifferent`, `convert.start`,
      `convert.cancel`, `convert.back`, `convert.pageProgress` (with `{{done}}`/`{{total}}`
      interpolation), `convert.status.pending|running|paused|done|failed|canceled`,
      `convert.pagesPerMin`, `convert.eta`, `convert.result.title`, `convert.copyMarkdown`,
      `convert.saveMd`, `convert.saved`, `convert.needsReview` (with `{{count}}`),
      `convert.failedPages` (with `{{count}}`), `convert.error.engineNotReady`,
      `convert.error.generic`, and a Home `home.convert` button label. `id` values in Indonesian,
      `en` in English. Keep every key present in BOTH files.
      Files: `apps/desktop/src/locales/id.json`, `apps/desktop/src/locales/en.json`
      Verify: `pnpm --filter desktop test -- --run` — `locales.test.ts` parity test stays green.

- [ ] 7. Add the LICENSES.md rows and docs (evidence + progress).
      In `docs/LICENSES.md`: add a frontend-npm row for `@tauri-apps/plugin-dialog | 2.8.3 | npm |
      Apache-2.0 OR MIT | Yes | Yes` and update the `@tauri-apps/api` row to `2.12.0`; add a Rust
      crate row `tauri-plugin-dialog | 2.8.3 | crates.io | MIT OR Apache-2.0 | Yes | Yes` (native
      open/save dialogs for the Convert PDF screen). Create
      `docs/m-ui-pdf-verification.md` documenting what was built (the four Rust proxy commands + the
      `engine://job-progress` poll bridge + `save_text`, the `engineClient` job/dialog wrappers, the
      `ConvertPdf` screen, i18n keys, tests), with the EXACT commands run and their real output
      (pnpm lint/test/build + cargo fmt/clippy/build/test), and a clearly-marked
      "Running-window E2E: PENDING MANUAL" section (pick a PDF → Start → progress → export →
      Copy/Save must be verified by the user in `pnpm tauri dev`, which automation must not run).
      In `docs/PROGRESS.md` add a note that the PDF→Markdown UI was added on `feat/m4-jobs`.
      Files: `docs/LICENSES.md`, `docs/m-ui-pdf-verification.md`, `docs/PROGRESS.md`
      Verify: re-run the full frontend suite (`pnpm --filter desktop lint`,
      `pnpm --filter desktop test -- --run`, `pnpm --filter desktop build`) and the Rust suite
      (`cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo build`, `cargo test`)
      from a clean state; paste the real output into `docs/m-ui-pdf-verification.md`. Clean up any
      temp files.

## Notes / open assumptions
- Terminal job-status vocabulary and the exact `JobStatus` union: confirm against
  `engine/texora_engine/db/jobs_dao.py` (`TERMINAL_JOB_STATUSES`, `ACTIVE_JOB_STATUSES`) while
  implementing steps 1 and 3 rather than hard-coding guesses.
- The default `JobOptions` already defaults `formats:['md']`, so `createJob` can send a minimal body;
  only set `dpi`/page-range fields if the UI exposes them (it does not in this lean screen).
- If, during step 3, `@tauri-apps/plugin-fs` turns out simpler than a `save_text` Rust command for
  writing the chosen path, that is an acceptable swap — but it then needs its own LICENSES row and a
  `fs:allow-write-text-file` capability; the `save_text` Rust command is preferred as it adds no new
  plugin and keeps the write path in the thin Rust client.
```

