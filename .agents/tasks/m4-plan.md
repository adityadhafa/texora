# Implementation Plan — Texora M4 (Job queue, checkpoint/resume, batch + watch folder, 5,000-page proof)

Source of truth: the approved design `.agents/tasks/m4-design.md` (HOW) + the authoritative
`done:` criteria in `.kiro/specs/texora/tasks.md` §M4. This plan sequences that design faithfully;
it re-decides nothing. Requirements traced: `R-JOB-1..7`, `R-UI-1/6`, `R-SEC-2/3`, `DoD-1/2`.

## Execution constraints (read first — anti-race)

- **Exactly ONE coder writes the worktree `c:\data\kucing\texora\.worktrees\m4-jobs` at any
  instant.** This plan is a single ordered chain for ONE sequential implementer. Never run two
  tasks concurrently; never spawn an overlapping writer. The order is the design's §14 chain:
  **4.1 → 4.2 → 4.3 → 4.5 → 4.4 → 4.6 → 4.7 → 4.8** (4.5 is pulled before 4.4 per design §14; both
  depend only on 4.2/4.3 and the chain stays linear). One writer → verify → commit → next.
- Each task leaves the engine build **green on its own**: `ruff` clean, `black --check` clean,
  `mypy texora_engine` clean, `pytest -q` passing (model-/binary-gated tests skip-with-reason, never
  mocked). A task is complete only when its verification passes.
- **Verification commands** (run from `engine/` with the worktree venv, mirroring
  `docs/m3-verification.md` / `docs/PROGRESS.md`; the venv is created fresh in the worktree and is
  gitignored). On Windows/bash the interpreter is `.venv/Scripts/python.exe`:
  - `.venv/Scripts/python.exe -m ruff check .`
  - `.venv/Scripts/python.exe -m black --check . --line-length 100`
  - `.venv/Scripts/python.exe -m mypy texora_engine`
  - `.venv/Scripts/python.exe -m pytest -q`
  Frontend (task 4.8 only), from `apps/desktop/` or repo root:
  `pnpm --filter desktop lint`, `pnpm --filter desktop test`, `pnpm --filter desktop build`. Do NOT
  run `pnpm tauri dev`/watchers via automation — the user runs those manually.
- **Dependency + licensing rule (steering):** any new dependency gets a `docs/LICENSES.md` row in
  the SAME change that introduces it, pinned to an exact version. M4 shipped deps: `watchdog`
  4.0.2 (Apache-2.0), Rust `tungstenite` 0.23 (MIT/Apache-2.0). Test/CI-only deps (NOT frozen into
  the PyInstaller sidecar): `reportlab` 4.2.2 (BSD-3-Clause), `psutil` 6.0.0 (BSD-3-Clause). Declare
  test-only deps under a `[project.optional-dependencies] test` extra in `engine/pyproject.toml`.
  `anyio` needs NO row (stays a transitive Starlette dep; the runner imports only stdlib
  `concurrent.futures`). Verify each exact version against official PyPI/crates metadata before
  pinning.
- **mypy note:** `watchdog`, `psutil`, `reportlab` have no bundled stubs — add them to the
  `[[tool.mypy.overrides]] ignore_missing_imports` module list in `engine/pyproject.toml` in the
  same task that first imports each.
- **All SQLite access goes through `db/` DAOs** — no raw SQL in routes or the runner. All DB calls
  run on the engine's single asyncio loop; worker threads never touch `conn`; the watchdog thread
  only marshals via `loop.call_soon_threadsafe` (design §1 M4-ADR-1).
- **Honesty invariants:** no fabricated output; a page that cannot be processed is `failed`; the
  5,000-page claim is proven locally at a SCALED count + full count on CI nightly — documented
  honestly in `docs/m4-verification.md`, never faked.

---

## Tasks

- [ ] 1. **(4.1) SQLite schema + additive v1→v2 migration + new typed DAOs + FTS5.**
      Convert `schema.py`'s single `_SCHEMA_SQL` blob into an ordered `_MIGRATIONS: dict[int, str]`
      keyed by target version (`1: _V1_SQL` = the current `_SCHEMA_SQL` VERBATIM; `2: _V2_SQL`); bump
      `SCHEMA_VERSION = 2`; rewrite `migrate` to loop `range(current+1, SCHEMA_VERSION+1)` applying
      each step in its own `with conn:` transaction + `PRAGMA user_version`, with the gap-guard
      `assert version in _MIGRATIONS` and NO `if current >= SCHEMA_VERSION: return` fast-path (the
      empty range is already a no-op). `_V2_SQL` creates `job`, `page`, `region`,
      `formula_candidate`, `correction`, the `region_fts` FTS5 virtual table, and the
      `region_ai`/`region_ad`/`region_au` triggers exactly as design §4.2 specifies (PAGE has the
      two orthogonal columns `status` = lease lifecycle `pending|leased|done|failed` and
      `rollup_status` = content quality `ok|needs_review|failed`; `result_json` stores the full
      `PageResult.model_dump_json()`). Add the new DAOs as separate files beside
      `models_dao.py`/`settings_dao.py`, each returning typed dataclasses/Pydantic rows (no untyped
      dict crosses a boundary): `jobs_dao.py` (`JobRow`; `create_job`, `get_job`, `list_jobs`,
      `set_status`, `set_priority`, `update_timestamps`, `delete_job`), `pages_dao.py` (`PageRow`;
      `bulk_insert_pending`, `lease_next` [atomic `UPDATE ... WHERE status='pending' ... RETURNING`],
      `mark_done`, `mark_failed` [both `WHERE id AND lease_token=:tok`], `revert_expired_leases(now)`
      [TTL-gated sweeper], `revert_all_leased_for_active_jobs()` [unconditional boot-revert — DISTINCT
      from the TTL method, design §4.3], `reset_failed_to_pending(job_id)`, `counts(job_id)`,
      `get_page`), `regions_dao.py` (`insert_regions`), `fts_dao.py` (`search(query, limit, offset)
      -> list[FtsHit]` using FTS5 `MATCH` + `bm25()` + `snippet()`, query bound as a parameter; `FtsHit`
      Pydantic model = `{region_id, job_id, snippet, score}`, never exposing the implicit FTS rowid).
      Re-export the new public names from `db/__init__.py`. Also add the one-line spec erratum (design
      §4.2 / M4-ADR-9) to `.kiro/specs/texora/design.md §4` and near 4.1 in `.kiro/specs/texora/tasks.md`
      stating the PAGE `status`/`rollup_status` split and that the review surface queries `rollup_status`.
      Files: `engine/texora_engine/db/schema.py`, `engine/texora_engine/db/jobs_dao.py` (new),
      `engine/texora_engine/db/pages_dao.py` (new), `engine/texora_engine/db/regions_dao.py` (new),
      `engine/texora_engine/db/fts_dao.py` (new), `engine/texora_engine/db/__init__.py`,
      `engine/tests/test_db_migrations.py` (new), `engine/tests/test_jobs_dao.py` (new),
      `engine/tests/test_pages_dao.py` (new), `engine/tests/test_fts_dao.py` (new),
      `.kiro/specs/texora/design.md`, `.kiro/specs/texora/tasks.md`.
      `done:` migration test passes + FTS query returns (tasks.md 4.1). Tests MUST cover (design §4.4,
      §13): fresh-DB migration (`user_version==2`; both v1 tables `model`/`setting` AND all v2 tables
      exist); v1-seeded preservation (a DB pre-seeded at `user_version=1` with a `MODEL` row → `migrate`
      → row survives verbatim + v2 tables appear); `lease_next` atomicity (two concurrent lease attempts
      → distinct pages); `revert_expired_leases` reverts only expired; `revert_all_leased_for_active_jobs`
      reverts EVERY leased row of a non-terminal job even with a future `lease_expires_at` and leaves
      terminal-job leases untouched; `reset_failed_to_pending` touches only failed rows;
      `fts_dao.search("integral")` returns the expected `region_id`/`job_id` ranked. Real fixture: an
      in-memory/tmp SQLite DB seeded with known `job`/`page`/`region` rows (unit-level, no models needed).
      Verify: `.venv/Scripts/python.exe -m pytest tests/test_db_migrations.py tests/test_jobs_dao.py
      tests/test_pages_dao.py tests/test_fts_dao.py -q` all pass, then the full engine gate
      (`ruff`/`black --check`/`mypy texora_engine`/`pytest -q`) is clean.

- [ ] 2. **(4.2) Streaming job runner + manager + per-page lease loop (reuses `assemble_page`).**
      Create the `jobs/` package. Add the bounded job settings to `Settings` (design §3.4):
      `job_max_concurrent_pages` (default 2, `ge=1,le=64`), `job_page_workers` (default **1**,
      `ge=1,le=64` — serializes the shared torch model, HIGH-2), `job_lease_ttl_s` (default 300.0,
      `gt=0`), `job_page_timeout_s` (default 120.0, `gt=0`), `job_lease_sweep_s` (default 30.0, `gt=0`),
      `job_output_dir` (default `output`), `watch_dir` (default `None`), `watch_settle_s` (default 2.0,
      `gt=0`), `ws_token_timeout_s` (default 5.0, `gt=0`); add the Pydantic v2
      `@model_validator(mode="after")` enforcing `job_page_timeout_s < job_lease_ttl_s` (HIGH-3). Add
      the `Request`-free shared deps provider `pipeline/deps.py::get_or_build_deps(app_state) ->
      PipelineDeps` (reads `app_state.{settings, model_store}` via `getattr(..., "pipeline_deps",
      None)`, builds layout/text/formula engines + `load_pipeline_config`, caches via `setattr`; raises
      the SAME typed errors `ModelNotReady`/`TesseractUnavailable`/factory-misconfig the route maps —
      design §11, NIT-4) and refactor `api/pages._get_deps(request)` to a thin wrapper
      `return get_or_build_deps(request.app.state)` keeping its 409/500 mapping. Add the lazy image
      frame iterator `ingest/images.py::iter_image_pages(path, settings) -> Iterator[tuple[RenderedPage,
      Image.Image]]` (mirrors `iter_pdf_pages`; loads+converts ONE frame at a time via
      `ImageSequence.Iterator`; same `ImageBounds` guards; caller owns/closes each image — design §2.1,
      MEDIUM-1), leaving the eager `load_image_pages` untouched. Implement `jobs/manager.py`
      (`JobManager` on `app.state.job_manager`: one `asyncio.Semaphore(job_max_concurrent_pages)`, one
      `ThreadPoolExecutor(max_workers=job_page_workers)`, a `dict[str, JobHandle]` with per-job
      `asyncio.Task` + pause `asyncio.Event` + cancel flag + `JobProgress`) and `jobs/runner.py`
      (`_run_job` coroutine: the §3.1 loop — per owned page, `await pause_gate`, check cancel, `async
      with semaphore`, `pages_dao.lease_next`, render the page via the source-kind seam [PDF: `open_pdf`
      once + `render_pdf_page(pdf, index, cfg)` for ONLY owned/`pending` indices, never
      `iter_pdf_pages`, MEDIUM-F1; image: `iter_image_pages`, pre-resume frames decoded-and-skipped],
      `await loop.run_in_executor(pool, assemble_page, rendered, image, deps)`, `mark_done` on success,
      free the bitmap in `finally`, `emit_progress`). `JobProgress` from `pages_dao.counts` + an EWMA
      of per-page durations for pages/min + ETA (design §3.3). Build the deps inside `_run_job`'s
      top-level guard so a deps-build failure fails the JOB gracefully (`status=failed`,
      `error="models not ready: …"`/`"pipeline misconfiguration: …"`, no page leased, never crashes the
      task — design §11, MEDIUM-F4). This task adds NO API surface yet. No new dependency.
      Files: `engine/texora_engine/settings.py`, `engine/texora_engine/pipeline/deps.py` (new),
      `engine/texora_engine/api/pages.py`, `engine/texora_engine/ingest/images.py`,
      `engine/texora_engine/jobs/__init__.py` (new), `engine/texora_engine/jobs/manager.py` (new),
      `engine/texora_engine/jobs/runner.py` (new), `engine/tests/test_settings.py`,
      `engine/tests/test_jobs_runner.py` (new), `engine/tests/test_iter_image_pages.py` (new),
      `engine/tests/test_get_or_build_deps.py` (new).
      `done:` memory stays flat on a large synthetic PDF (tasks.md 4.2 — proven at scale in task 7;
      here, prove the mechanism). Tests MUST cover (design §13): a small end-to-end job over a synthetic
      multi-page PDF driven with a FAST stub `FormulaRecognizer`/`TextRecognizer` in the harness (the
      production path stays real — honesty intact) reaches all pages `done`; the semaphore caps in-flight
      pages (at most `job_max_concurrent_pages` bitmaps live at once); `iter_image_pages` yields one
      frame at a time over a multi-frame TIFF without materializing all frames; `get_or_build_deps`
      builds+caches once and raises the typed errors with no `Request` (seed `settings`/`model_store` on
      a stub `app_state`); the `job_page_timeout_s < job_lease_ttl_s` validator rejects an invalid
      config. Real fixture: a small synthetic PDF (generated inline or a committed tiny fixture) + the
      two-frame `multipage.tiff` already under `engine/tests/fixtures/`. Verify: the full engine gate is
      clean and `.venv/Scripts/python.exe -m pytest tests/test_jobs_runner.py
      tests/test_iter_image_pages.py tests/test_get_or_build_deps.py tests/test_settings.py -q` passes.

- [ ] 3. **(4.3) Checkpoint/resume (boot-revert + sweeper) + idempotent per-page export writer +
      per-page body emitters + reference JSON exporter.**
      Add `pipeline/deps`-independent resume wiring on the manager: `recover_on_boot()` calls
      `pages_dao.revert_all_leased_for_active_jobs()` (UNCONDITIONAL boot-revert, design §6.2 step 1,
      single-process precondition) then re-enqueues every job with `status in (running, paused, queued)`
      (paused stays paused); it NEVER re-enrolls (design §6.1, NIT-F6). Add the periodic sweeper as an
      `asyncio` task on the loop (interval `job_lease_sweep_s`) calling `pages_dao.revert_expired_leases
      (now)` (design §6.2). Add enrollment at job create: `bulk_insert_pending(job_id, indices)` in ONE
      transaction, computing the owned index set from job options (full doc / `page_start..page_end`
      range / explicit `pages: [..]` list); `total_pages`/the index universe come from `len(pdf)` (PDF)
      or the frame count (image). Add `JobManager.shutdown()` (graceful checkpoint: signal cancel, await
      in-flight pages to `done`/`failed` bounded by `job_page_timeout_s`, stop the executor — design
      §6.3). Add the two thin PUBLIC per-page body emitters wrapping the existing private `_render_page`
      (body only, NO document wrapper / trailing-newline rule): `export/markdown.py::render_page_markdown
      (page, opts) -> str` and `export/latex.py::render_page_latex_body(page, opts) -> str`, each
      `"\n\n".join(b for b in _render_page(page, options) if b != "")`. Add the reference JSON exporter
      `export/json_export.py::document_to_json(doc, opts) -> str` = `doc.model_dump_json(indent=...)` (the
      FULL `DocumentResult`/`PageResult`, lossless — design §7.1 json rule, MEDIUM-3). Implement the
      idempotent per-page writer `jobs/output.py::write_page_outputs_idempotent(...)`: write each page's
      `md`/`tex` body fragment + JSON page dump + figure assets to `output/<job_id>/pages/<index>.<ext>.tmp`
      then `os.replace()` to the final name (atomic on Windows+POSIX); the final write is the commit point
      and happens BEFORE `mark_done`; also maintain a `output/<job_id>/manifest.json` (temp+rename)
      recording completed page fragments (design §7.2). Wire the writer into `runner._run_job` before
      `mark_done`. Add the on-demand concat builder (used by the export route in task 5) that joins
      committed fragments in `page_index` order and applies the single document wrap exactly once per
      format with the empty-fragment filter (md: `"\n\n".join(f for f in fragments if f != "")` + `body +
      "\n" if body else "\n"`; tex: `preamble_for(...).rstrip("\n")` + `\begin{document}` + body joined by
      `"\n\n"` + `\end{document}`, joined by `"\n"`, trailing `"\n"` — matching `document_to_latex`'s
      `parts` assembly byte-for-byte; json: reconstruct `DocumentResult` from committed `result_json` and
      call `document_to_json`, or the mid-job placeholder array — design §7.1/§7.3).
      Files: `engine/texora_engine/jobs/manager.py`, `engine/texora_engine/jobs/runner.py`,
      `engine/texora_engine/jobs/output.py` (new), `engine/texora_engine/export/markdown.py`,
      `engine/texora_engine/export/latex.py`, `engine/texora_engine/export/json_export.py` (new),
      `engine/texora_engine/export/__init__.py`, `engine/tests/test_jobs_resume.py` (new),
      `engine/tests/test_jobs_output.py` (new), `engine/tests/test_export_fragment_concat.py` (new).
      `done:` kill mid-job → resume with no lost/dup pages (tasks.md 4.3, DoD-2). Tests MUST cover (design
      §13): fragment-concat golden-equivalence over a FULL page set, a committed-SUBSET (mid-job) set,
      AND a set containing a committed page that renders an EMPTY body — `md`/`tex`/`json` concat is
      byte-identical to `document_to_markdown`/`document_to_latex`/`document_to_json` over that exact set
      (HIGH-1 + MEDIUM-F3 + the empty-fragment filter MEDIUM-1 + json anchor MEDIUM-3); json round-trips
      (`DocumentResult.model_validate_json(out) == doc`); the idempotent writer writes twice → one file,
      same bytes; manifest concat order is `page_index`; immediate-resume determinism — simulate a crash
      (leave rows `leased` with a FUTURE `lease_expires_at`), reopen the DB, run `recover_on_boot`, assert
      those pages are `pending` AT ONCE (not TTL-delayed) and a resumed job reaches `done` over the full
      index set with no duplicates (per-page processing counter in the stub); resume renders only owned
      PDF indices (a stub `render_pdf_page` counter asserts a resumed job never re-renders a `done`
      index — MEDIUM-F1). Real fixture: a fixed hand-constructed `DocumentResult` (extend
      `engine/tests/_doc_sample.py`) incl. an empty-body page, plus the small synthetic PDF + stub
      recognizers from task 2. Verify: the full engine gate is clean and
      `.venv/Scripts/python.exe -m pytest tests/test_jobs_resume.py tests/test_jobs_output.py
      tests/test_export_fragment_concat.py -q` passes.

- [ ] 4. **(4.5) Failure isolation — per-page wall-clock timeout + resource guard + retry-failed-only.**
      In `runner._run_job`, wrap the whole `assemble_page` offload in
      `asyncio.wait_for(loop.run_in_executor(pool, assemble_page, ...), timeout=job_page_timeout_s)`; on
      `asyncio.TimeoutError` mark the page `failed` with `error="page timeout"` (document the abandoned-
      thread trade-off per design §5). Add the resource guard: before rendering, reject a page whose
      rendered pixel area would exceed `max_snip_pixels` (reuse the existing bound;
      `Image.MAX_IMAGE_PIXELS` is already set in `app.py`), logging + failing that page. Ensure ANY
      per-page exception is caught, logged with page context via `get_logger("jobs.runner")`, the page
      row set `failed`, and the loop continues — a failed page never kills the job (R-JOB-6). Finalize a
      job `done` when every page is attempted (non-zero `failed` count surfaced in progress), `failed`
      only if aborted. Add the retry path on the manager:
      `pages_dao.reset_failed_to_pending(job_id)` (flips `failed → pending`, clears `error`, keeps
      `attempts`; `done` rows untouched) + re-enqueue (design §5). No new dependency; no API surface yet
      (the route lands in task 5).
      Files: `engine/texora_engine/jobs/runner.py`, `engine/texora_engine/jobs/manager.py`,
      `engine/texora_engine/jobs/guard.py` (new, the page-timeout + resource-guard helpers),
      `engine/tests/test_jobs_failure_isolation.py` (new).
      `done:` hostile-page fixture fails the page, the job completes, retry works (tasks.md 4.5). Tests
      MUST cover (design §13): a hostile-page fixture (one pathological/oversize page) → that page
      `failed`, the other pages complete, job finishes `done` with `failed==1`; a subsequent retry
      re-attempts ONLY the poisoned page (counter proves `done` pages are not re-run); a page that runs
      right up to `job_page_timeout_s` is marked `failed` (never reverted/re-leased while in flight —
      HIGH-3 timeout/TTL ordering). Real fixture: the "hostile variant" synthetic page (produced by the
      generator from task 7, or a small committed pathological fixture here) + stub recognizers (one stub
      configured to hang/raise for a target index). Verify: the full engine gate is clean and
      `.venv/Scripts/python.exe -m pytest tests/test_jobs_failure_isolation.py -q` passes.

- [ ] 5. **(4.4) Job control REST API + bearer-protected progress WebSocket.**
      Create `api/jobs.py` with a `jobs_router = APIRouter(dependencies=[Depends(require_token)])` and
      mount it in `app.py` exactly like `pages_router`; on startup also construct
      `JobManager(...)` once on `app.state.job_manager`, call `recover_on_boot()`, and start the sweeper
      task; on FastAPI shutdown `await job_manager.shutdown()` (design §11). Routes (all Pydantic v2
      request/response models — `JobCreateRequest`, `JobView`, `JobProgress`, `BatchCreateRequest`,
      `FtsHit`, `ProgressEvent`; design §9.1): `POST /jobs` (path+options+range/list+priority →
      `JobView`), `GET /jobs` (`?status=&limit=&offset=`), `GET /jobs/{id}`, `POST /jobs/{id}:pause`,
      `:resume`, `:cancel`, `:reprioritize` (`{priority}`), `POST /jobs/{id}/pages:retry-failed` (wraps
      task 4's `reset_failed_to_pending`), `GET /jobs/{id}/export?format=md|tex|json` (returns a
      Starlette `StreamingResponse` fed by a generator reading one committed fragment at a time, partial
      over the committed set mid-job, non-`done` pages emit honest in-order placeholders per design §7.3
      — md `<!-- texora: page N status (no output) -->` / tex `% texora: ...` / json `{index,status,
      error}`; `Content-Type` per format + a `Content-Disposition` filename from `job.source_name`),
      `GET /search?q=&limit=&offset=` (→ `fts_dao.search`), and `WS /jobs/{id}/events`. Error mapping
      mirrors `api/pages.py`: bad path/range/format → 422, unknown job id → 404, action invalid for
      current state (e.g. resume a `done` job) → 409. WS auth (design §9.2, MEDIUM-4) validates against
      `app.state.engine_token` with `secrets.compare_digest`: header path — if an `Authorization: Bearer`
      header is present, validate BEFORE `accept()` (match → `accept()` + stream; mismatch →
      `close(code=4401)` without accept); fallback path — no header → `accept()`, then
      `asyncio.wait_for(ws.receive_text(), timeout=ws_token_timeout_s)` reading one `{"token":"..."}`
      frame, validate, on mismatch/timeout `close(4401)`. Input validation per design §10 (factor the
      shared path validator into `jobs/paths.py` from `api/pages._validate_path`; FTS `q` non-empty +
      `≤256` chars bound as a parameter; `priority` clamped `[-100,100]`; OOB page indices dropped with a
      logged note). `ProgressEvent` is emitted by the runner's `emit_progress` to connected WS
      subscribers on each page completion + state change.
      Files: `engine/texora_engine/api/jobs.py` (new), `engine/texora_engine/api/__init__.py`,
      `engine/texora_engine/app.py`, `engine/texora_engine/jobs/paths.py` (new),
      `engine/texora_engine/jobs/manager.py` (subscriber registry), `engine/tests/test_jobs_api.py`
      (new), `engine/tests/test_jobs_ws.py` (new).
      `done:` control actions verified; WS emits (tasks.md 4.4). Tests MUST cover (design §13): full
      small job end-to-end over a 5-page synthetic PDF via `POST /jobs` → all pages `done`, fragments on
      disk, export concat matches expected; pause/resume/cancel/reprioritize transitions + their 409s;
      retry-failed re-runs only the failed page; mid-job export returns the committed subset with an
      in-order placeholder for a not-yet-done page; deps-build-at-job-start failure
      (`get_or_build_deps` raises `ModelNotReady`) → job `failed` with `error="models not ready: …"`, no
      page leased, terminal WS event, task does not crash (MEDIUM-F4); WS auth both paths (header-mismatch
      closes 4401 pre-accept; fallback timeout closes 4401; a valid token on either path receives a
      `ProgressEvent`) and the WS emits a `ProgressEvent` per page (tested with a bare Starlette WS test
      client using the message-token fallback); 401 without a token on REST routes. Real fixture: the
      5-page synthetic PDF + stub recognizers (via `FastAPI` TestClient + `app.state` overrides, mirroring
      `conftest.py`). Verify: the full engine gate is clean and `.venv/Scripts/python.exe -m pytest
      tests/test_jobs_api.py tests/test_jobs_ws.py -q` passes.

- [ ] 6. **(4.6) Batch intake + watch folder (watchdog settle/debounce).**
      Add `POST /jobs/batch` accepting `{paths:[file-or-dir,...], options}` (dirs expanded non-recursively
      by default, `recursive:true` opt-in, to `_PDF_EXTS ∪ _IMAGE_EXTS` reused from `api/pages.py`; each
      resolved file → its own `JOB` enqueued; path validation via the shared `jobs/paths.py`). Implement
      `jobs/watch.py`: when `settings.watch_dir` is set, `app.py` starts a `watchdog` `Observer` on it at
      startup (and stops it on shutdown). A new/renamed file event triggers a settle check (wait
      `watch_settle_s`, confirm stable file size, validate extension+path) then enqueues a job; an
      in-memory already-enqueued set keyed by resolved path + mtime de-dupes the OS's multiple events; the
      `Observer` thread only submits enqueue work via `loop.call_soon_threadsafe` so all job creation
      goes through the single `JobManager` (no second writer — design §8, §1 M4-ADR-1). Pin `watchdog==
      4.0.2`, add it to `engine/requirements.txt` + `engine/pyproject.toml` dependencies + a `docs/
      LICENSES.md` row (Apache-2.0, shipped) + the mypy override list, all in this task.
      Files: `engine/texora_engine/api/jobs.py`, `engine/texora_engine/jobs/watch.py` (new),
      `engine/texora_engine/jobs/manager.py`, `engine/texora_engine/app.py`,
      `engine/requirements.txt`, `engine/pyproject.toml`, `docs/LICENSES.md`,
      `engine/tests/test_jobs_batch.py` (new), `engine/tests/test_jobs_watch.py` (new).
      `done:` dropping files / a new file in a watched dir enqueues jobs (tasks.md 4.6). Tests MUST cover
      (design §8): dropping a fixture PDF into a temp watch dir → a `JOB` row appears `queued` (settle
      wrapper is deterministic given a fully-written fixture, no live FS race needed); a folder of two
      PDFs via `POST /jobs/batch` → two jobs. Real fixture: the committed `born_digital_math.pdf` (and/or
      a tmp copy) under `engine/tests/fixtures/`. Verify: the full engine gate is clean and
      `.venv/Scripts/python.exe -m pytest tests/test_jobs_batch.py tests/test_jobs_watch.py -q` passes.

- [ ] 7. **(4.7) 5,000-page proof — synthetic generator + memory/resume assertions (local scaled + CI
      nightly at full count).**
      Add `scripts/make_synthetic_pdf.py` (`reportlab`): emits an N-page PDF with mixed text + simple
      math-like content, deterministic given a seed (CLI `python -m scripts.make_synthetic_pdf --pages N
      --out path.pdf`); also emits a "hostile" variant (one pathological oversize-image/degenerate page)
      for the task 4 isolation test. Add `benchmarks/job_proof/`: `test_memory_flat.py` (`psutil`) runs a
      job over a SCALED synthetic PDF, samples RSS every K pages, asserts the RSS-vs-pages slope is below
      a threshold (flat within noise) and peak RSS stays under a bound — using the FAST stub recognizers
      in-harness so runner/streaming memory is measured without model-load noise (a second
      `@pytest.mark.model` variant uses the real engines); `test_interrupt_resume.py` starts a job, kills
      the runner task mid-way (cancel + drop the manager without graceful shutdown so some pages stay
      `leased`), reopens the DB, runs `recover_on_boot`, resumes, and asserts the final `done` set == the
      full index set with no duplicates (per-page counter). Pin `reportlab==4.2.2` + `psutil==6.0.0`
      under a NEW `[project.optional-dependencies] test` extra in `engine/pyproject.toml` (so the
      PyInstaller sidecar — which freezes only runtime deps — never bundles them), add both to the mypy
      override list, and add `docs/LICENSES.md` rows marked *test/CI only, not shipped*, all in this task.
      Wire the full 5,000-page run as a CI nightly job (`.github/workflows/*` nightly matrix) that
      generates the 5,000-page PDF and runs the same assertions at full count. Document the split verbatim
      in `docs/m4-verification.md`: invariants proven locally at a scaled count; the full 5,000-page run
      is the nightly CI gate; never faked (design §12).
      Files: `scripts/make_synthetic_pdf.py` (new), `benchmarks/job_proof/__init__.py` (new),
      `benchmarks/job_proof/test_memory_flat.py` (new), `benchmarks/job_proof/test_interrupt_resume.py`
      (new), `engine/pyproject.toml`, `engine/requirements-dev.txt`, `docs/LICENSES.md`,
      `.github/workflows/` (nightly job — new or extended), `docs/m4-verification.md` (new, mirroring the
      `docs/m3-verification.md` structure: per-task sections with REAL captured command output + honest
      PENDING notes).
      `done:` CI nightly green; memory bounded; resume correct (tasks.md 4.7). The local proof asserts
      the mechanism at a scaled count (e.g. 200–500 pages — enough to see the RSS slope + a mid-job kill);
      the full 5,000-page count is the nightly CI gate, recorded honestly, never claimed as a local pass.
      Real fixture: the deterministic synthetic PDF produced by `make_synthetic_pdf.py` (a REAL document,
      not mocked). Verify: `.venv/Scripts/python.exe -m pytest benchmarks/job_proof -q` passes at the
      scaled count (install the `test` extra first: `.venv/Scripts/python.exe -m pip install -e
      ".[test]"`), then the full engine gate (`ruff`/`black --check`/`mypy texora_engine`/`pytest -q`) is
      clean. Record the exact command output in `docs/m4-verification.md`.

- [ ] 8. **(4.8) Queue UI + incremental output (single typed engineClient + Rust event bridge +
      i18next id/en).**
      Engine side is complete; this task wires the UI through the single typed client and the Rust
      bridge (components NEVER call `invoke`/`listen`/`fetch` directly — design §9.3). Rust: add
      `tungstenite==0.23` to `apps/desktop/src-tauri/Cargo.toml` + a `docs/LICENSES.md` row
      (MIT/Apache-2.0, shipped) in this task; add `start_job_events(app, id)` in `supervisor.rs` (a NEW
      blocking read thread that opens an authenticated WS — bearer token on the handshake — to the engine
      `WS /jobs/{id}/events`, loops reading frames and re-emits each as a Tauri `engine://job-progress`
      event; the thread stops on a terminal job state `done|failed|canceled` or socket close — mirrors the
      proven `start_model_poll` Tauri-event re-emit pattern but over a WS, not the `ureq` poller); add the
      `#[tauri::command] job_subscribe(id)` + thin `engine_request` proxy commands `job_create`,
      `job_list`, `job_get`, `job_pause`, `job_resume`, `job_cancel`, `job_reprioritize`,
      `job_retry_failed`, `job_search` in `lib.rs` (exactly like `recognize_snip`/`model_download`). TS:
      extend `engineClient.ts` with typed `createJob/listJobs/getJob/pauseJob/resumeJob/cancelJob/
      reprioritizeJob/retryFailed/searchContent` (invoke proxies, snake→camel mapping like `parseSnip`/
      `parseModelProgress`) + `subscribeJobProgress(cb)` listening to `engine://job-progress` (mirroring
      `subscribeModelProgress`). Add the Batch/Queue screen component rendering per-page + overall
      progress, throughput (pages/min + ETA), per-page errors, and a retry-failed button, wired to the
      client; all user-facing strings via i18next with `id` default + `en` provided (add keys to
      `src/locales/id.json` + `src/locales/en.json`). Route/register the screen in `App.tsx`.
      Files: `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/src/supervisor.rs`,
      `apps/desktop/src-tauri/src/lib.rs`, `apps/desktop/src/engineClient.ts`,
      `apps/desktop/src/engineClient.test.ts`, `apps/desktop/src/BatchQueue.tsx` (new),
      `apps/desktop/src/BatchQueue.test.tsx` (new), `apps/desktop/src/App.tsx`,
      `apps/desktop/src/locales/id.json`, `apps/desktop/src/locales/en.json`,
      `apps/desktop/src/locales.test.ts`, `docs/LICENSES.md`.
      `done:` E2E shows live per-page progress (tasks.md 4.8). Tests MUST cover (design §13 Frontend +
      Rust): `engineClient` job functions map snake→camel correctly and call the right invoke command
      (mocked `invoke`); `subscribeJobProgress` parses `engine://job-progress` payloads; the Batch/Queue
      component renders progress from a mocked client (per-page/overall status, throughput, errors, retry
      button) and all strings resolve via i18next `id`/`en` (locale completeness test); Rust
      `start_job_events` terminal-state detection + event re-emit (one-shot stub WS server, mirroring
      `engine_request_reaches_stub_with_bearer`) and the job proxy commands build the right body/path. The
      interactive live window (real WS → live DOM updates) is host-limited → record it PENDING MANUAL in
      `docs/m4-verification.md` (same honest pattern as M2's hotkey/popup and M3's latex-compile), proven
      structurally by vitest + cargo tests. Real fixture: a mocked `engineClient`/`invoke` + a stub WS
      server (no live engine needed for the unit layer). Verify (engine gate still clean), then frontend:
      `pnpm --filter desktop lint`, `pnpm --filter desktop test`, `pnpm --filter desktop build` all pass,
      and `cargo test` (run via `pnpm tauri`-adjacent tooling or `cargo test` in
      `apps/desktop/src-tauri/`) passes. Record output in `docs/m4-verification.md`.

---

## Final-gate checklist (after task 8)

- Engine: `ruff check .` clean · `black --check . --line-length 100` clean · `mypy texora_engine`
  clean · `pytest -q` passing (model-/binary-gated tests skip-with-reason, never mocked).
- Benchmarks: `pytest benchmarks/job_proof -q` passes at the scaled count; the 5,000-page full run is
  wired as the CI nightly gate (not a local claim).
- Frontend: `pnpm --filter desktop lint` · `pnpm --filter desktop test` · `pnpm --filter desktop
  build` all pass; Rust `cargo test` passes.
- `docs/m4-verification.md` records REAL captured output per task with honest PENDING MANUAL notes;
  `docs/LICENSES.md` has rows for `watchdog`, `tungstenite` (shipped) and `reportlab`, `psutil`
  (test/CI only, not shipped); `docs/PROGRESS.md` updated to M4 status.
- DoD-1/2: a kill mid-job resumes with no lost/duplicate pages (task 3 + task 7 interrupt-resume);
  the unlimited-pages claim rests on the honest scaled-local + nightly-CI proof.
- Clean up any temp files created during verification.
```
