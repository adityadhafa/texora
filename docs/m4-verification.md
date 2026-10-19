# M4 — Verification Log

Real command output captured while implementing M4 (job queue + checkpoint/resume + batch +
watch-folder + the 5,000-page proof). Each section is appended as its task completes; earlier
sections are not overwritten. Host: Windows + bash. Engine venv: Python **3.11.9** at
`.worktrees/m4-jobs/engine/.venv` (created fresh for M4; gitignored). The venv was seeded by
installing `engine/requirements.txt` (M1–M3 runtime pins) + the pinned dev tools (`pytest` 8.3.3,
`pytest-asyncio` 0.24.0, `ruff` 0.6.9, `black` 24.10.0, `mypy` 1.11.2). Interactive / host-only
items are recorded as PENDING MANUAL and are never claimed as passed. Memory-flatness numbers and
kill-and-resume results are REAL measurements (task 4.7), never fabricated.

Required engine commands run with the PATH export + the worktree venv
(`engine/.venv/Scripts/python.exe`), from `engine/`:
`export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:...:$PATH"`.

---

## Baseline (before M4) — M3 gate re-run green on this worktree

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> 90 files would be left unchanged.
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 55 source files
$ .venv/Scripts/python.exe -m pytest                  -> 151 passed, 12 skipped, 1 xfailed
```

---

## Task 4.1 — SQLite schema + additive v1→v2 migration + typed DAOs + FTS5

**What landed.** `db/schema.py` converted to an ordered `_MIGRATIONS` map (`1: _V1_SQL` verbatim,
`2: _V2_SQL`), `SCHEMA_VERSION=2`, gap-guarded loop with no fast-path early return. `_V2_SQL`
creates `job`/`page`/`region`/`formula_candidate`/`correction`, the `region_fts` FTS5 virtual table,
and the `region_ai`/`region_ad`/`region_au` triggers. PAGE carries the two orthogonal columns
`status` (lease lifecycle) + `rollup_status` (content quality) per M4-ADR-9; `result_json` stores the
full `PageResult.model_dump_json()`. New typed DAOs beside `models_dao.py`:

- `jobs_dao.py` — `JobRow`; `create_job`/`get_job`/`list_jobs`/`set_status`/`set_priority`/
  `update_timestamps`/`delete_job`; `ACTIVE_JOB_STATUSES`/`TERMINAL_JOB_STATUSES`.
- `pages_dao.py` — `PageRow`/`PageCounts`/`LeasedPage`; `bulk_insert_pending`, atomic `lease_next`
  (`UPDATE ... RETURNING`), token-guarded `mark_done`/`mark_failed`, the two DISTINCT reverts
  (`revert_expired_leases(now)` TTL sweeper vs `revert_all_leased_for_active_jobs()` unconditional
  boot-revert), `reset_failed_to_pending`, `counts`, `get_page`, `list_pages`.
- `regions_dao.py` — `RegionInsert`/`insert_regions` (FTS filled by the trigger).
- `fts_dao.py` — `FtsHit` Pydantic model `{region_id, job_id, snippet, score}`; `search(query,...)`
  binds the query to FTS5 `MATCH`, ranks by `bm25()`, never exposes the implicit rowid.

Spec erratum (M4-ADR-9) added to `.kiro/specs/texora/design.md §4` (ER diagram comment) and
`tasks.md` near 4.1 stating the PAGE `status`/`rollup_status` split.

**New dependencies:** none (stdlib `sqlite3` + FTS5 compiled into the bundled SQLite; `pydantic`
already pinned). No `docs/LICENSES.md` row required.

**Tests** (`tests/test_db_migrations.py`, `tests/test_jobs_dao.py`, `tests/test_pages_dao.py`,
`tests/test_fts_dao.py`): fresh-DB migration (`user_version==2`, v1+v2 tables present); v1-seeded
preservation (a `MODEL` row at `user_version=1` survives verbatim, v2 tables appear); migrate is a
no-op at current version; `lease_next` index order + atomicity (two attempts → distinct pages);
token-guarded `mark_done`/`mark_failed`; `revert_expired_leases` reverts only expired;
`revert_all_leased_for_active_jobs` reverts every leased row of an active job despite a FUTURE TTL
and leaves terminal-job leases untouched; `reset_failed_to_pending` touches only failed rows (keeps
`attempts`); `counts` rolls up `needs_review`; FTS `search("integral")` returns the expected
`region_id`/`job_id`, NULL content is not indexed, ranking + limit + `region` UPDATE refresh.

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> 98 files would be left unchanged.
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 59 source files
$ .venv/Scripts/python.exe -m pytest tests/test_db_migrations.py tests/test_jobs_dao.py \
      tests/test_pages_dao.py tests/test_fts_dao.py   -> 20 passed
$ .venv/Scripts/python.exe -m pytest                  -> 171 passed, 12 skipped, 1 xfailed
```

---

## Task 4.2 — Streaming job runner + manager + per-page lease loop

**What landed.** New `jobs/` package: `jobs/models.py` (`JobOptions`/`JobProgress`/`ProgressEvent`
Pydantic v2 models), `jobs/manager.py` (`JobManager` on `app.state.job_manager`: one global
`asyncio.Semaphore(job_max_concurrent_pages)`, one `ThreadPoolExecutor(job_page_workers)`, a
`dict[str, JobHandle]` with per-job `asyncio.Task` + pause `asyncio.Event` + cancel flag + an EWMA
rate tracker + a WS-subscriber list; `create_job` enrolls the owned index set in ONE transaction
and starts the runner task), `jobs/runner.py` (`run_job`/`_run_job`: the §3.1 lease loop — build
deps once in a top-level guard, per owned page `lease_next` → render → offload `assemble_page` to
the pool under the semaphore → `mark_done`/`mark_failed` → `emit_progress`, freeing the bitmap in
`finally`). PDFs render via the indexed `render_pdf_page` on a single `open_pdf` handle (resume
renders only owned indices); images via the new lazy `iter_image_pages` with pre-resume frames
decoded-and-skipped. Added `pipeline/deps.py::get_or_build_deps(app_state)` (Request-free shared
provider) and refactored `api/pages._get_deps` to a thin wrapper. Added the bounded job settings +
the `job_page_timeout_s < job_lease_ttl_s` cross-field validator. Added
`ingest.images.iter_image_pages` + `image_frame_count` (eager `load_image_pages` untouched).

**New dependencies:** none (stdlib `asyncio` + `concurrent.futures`). No LICENSES row.

**Tests** (`tests/test_jobs_runner.py`, `tests/test_iter_image_pages.py`,
`tests/test_get_or_build_deps.py`, `tests/test_settings.py`, harness `tests/_job_harness.py` with
fast stub recognizers + a REAL minimal multi-page PDF writer — no mock OCR): a 5-page synthetic PDF
job reaches all pages `done`; range + explicit-list enrollment (out-of-range indices dropped); the
semaphore caps in-flight pages (peak ≤ cap); a 2-frame TIFF streams to `done`; `iter_image_pages`
yields one frame at a time and `image_frame_count` matches; `get_or_build_deps` tolerates a missing
`pipeline_deps` attr (raises `ModelNotReady`, not `AttributeError`) and returns a cached instance;
the timeout/lease-TTL validator rejects an invalid config.

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> all files unchanged
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 64 source files
$ .venv/Scripts/python.exe -m pytest tests/test_jobs_runner.py tests/test_iter_image_pages.py \
      tests/test_get_or_build_deps.py tests/test_settings.py  -> 16 passed
$ .venv/Scripts/python.exe -m pytest                  -> 183 passed, 12 skipped, 1 xfailed
```

---

## Task 4.3 — Checkpoint/resume + idempotent per-page export writer + reference JSON exporter

**What landed.** `JobManager.recover_on_boot()` (calls `revert_all_leased_for_active_jobs()`
unconditionally, then re-enqueues each `running|paused|queued` job — paused stays paused; NEVER
re-enrolls), the periodic sweeper `start_sweeper()` (an asyncio task calling
`revert_expired_leases(now)` every `job_lease_sweep_s`), and graceful `shutdown()` (cancel tasks,
await in-flight, stop the pool). New `export/json_export.py::document_to_json` (lossless
`DocumentResult` dump) + thin public per-page body emitters `render_page_markdown` /
`render_page_latex_body` (wrap the private `_render_page`, empties filtered). New `jobs/output.py`:
`write_page_outputs_idempotent` (temp + `os.replace` per fragment + a `manifest.json`, wired into
`runner._commit_done` BEFORE `mark_done`), `read_manifest`, and the on-demand concat builders
`build_markdown`/`build_latex`/`build_json` that apply the single document wrap exactly once with
the empty-fragment filter + honest in-order placeholders for non-committed pages. The runner now
also persists each page's regions (feeding FTS via the trigger).

**New dependencies:** none. No LICENSES row.

**Tests** (`tests/test_export_fragment_concat.py`, `tests/test_jobs_output.py`,
`tests/test_jobs_resume.py`; `_doc_sample.py` extended with an EMPTY-body page +
`build_multipage_document_with_empty`): fragment-concat byte-identity for `md`/`tex`/`json` over a
FULL set that includes a committed empty-body page (empty-fragment filter, MEDIUM-1); json
round-trips (`DocumentResult.model_validate_json(out) == doc`, MEDIUM-3); committed-SUBSET mid-job
concat matches the whole-doc exporter over that subset after stripping the in-order placeholder;
mid-job json/md placeholder emission for a failed page; idempotent writer (write twice → one final
file, no stray `.tmp`, same bytes); the full JSON fragment is always written; manifest records
completed indices in `page_index` order; immediate boot-revert (a TTL-FUTURE lease is `pending` at
once after `revert_all_leased_for_active_jobs`); kill-mid-job → `recover_on_boot` → resume reaches
`done` over the full index set with NO lost and NO duplicate-completed pages (at most the one
in-flight page re-rendered); resume renders ONLY owned indices (a pre-done prefix is never
re-rendered — MEDIUM-F1, proven with a `render_pdf_page` counter).

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> all files unchanged
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 66 source files
$ .venv/Scripts/python.exe -m pytest tests/test_export_fragment_concat.py tests/test_jobs_output.py \
      tests/test_jobs_resume.py  -> 12 passed
$ .venv/Scripts/python.exe -m pytest                  -> 195 passed, 12 skipped, 1 xfailed
```

---

## Task 4.5 — Failure isolation: per-page timeout + resource guard + retry-failed-only

**What landed.** New `jobs/guard.py` (`PageResourceError` + `check_page_resources(rendered,
max_pixels)` reusing the M2 `max_snip_pixels` bound). The runner now wraps the whole
`assemble_page` offload in `asyncio.wait_for(..., timeout=job_page_timeout_s)` (on timeout the page
is `failed` with `error="page timeout"`; the abandoned-thread trade-off is documented inline per
§5), applies the resource guard before recognition, and catches ANY per-page exception → logs with
page context → `mark_failed` → continues (a failed page never kills the job). A job finishes `done`
when every page is attempted (non-zero `failed` surfaced in progress). `JobManager.retry_failed`
calls `reset_failed_to_pending` (flips `failed → pending`, keeps `attempts`, `done` untouched) +
re-enqueues.

**New dependencies:** none. No LICENSES row.

**Tests** (`tests/test_jobs_failure_isolation.py`): the resource guard rejects an oversize page and
passes one within bound; a hostile page (stub raising for one index) is isolated as `failed` while
the other 3 pages complete and the job finishes `done` with `failed==1`, then retry re-runs ONLY
the failed index (a per-index processed-counter proves `done` pages are not re-run); a page that
runs past `job_page_timeout_s` is marked `failed` with `error="page timeout"` (never reverted/
re-leased while in flight) and the job still completes the other page.

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> all files unchanged
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 67 source files
$ .venv/Scripts/python.exe -m pytest tests/test_jobs_failure_isolation.py  -> 3 passed
$ .venv/Scripts/python.exe -m pytest                  -> 198 passed, 12 skipped, 1 xfailed
```

---

## Task 4.4 — Job control REST API + bearer-protected progress WebSocket

**What landed.** New `jobs/paths.py` (`validate_source_path` / `PathValidationError` /
`is_supported_file`, factored from `api/pages._validate_path`, which now wraps it). New
`api/jobs.py`: a `jobs_router` (`Depends(require_token)`) with `POST /jobs`, `POST /jobs/batch`,
`GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}:pause|:resume|:cancel|:reprioritize`,
`POST /jobs/{id}/pages:retry-failed`, `GET /jobs/{id}/export?format=md|tex|json` (a
`StreamingResponse` over the committed set with in-order placeholders + a `Content-Disposition`
filename), `GET /search?q=` (FTS). A SEPARATE `jobs_ws_router` carries `WS /jobs/{id}/events` and
does its OWN bearer validation (header path pre-`accept()`; message-token fallback post-`accept()`
under `ws_token_timeout_s`; `close(4401)` on mismatch/timeout) — the WS is NOT on the HTTP-dependency
router because `HTTPBearer` cannot run on a WebSocket scope. Error mapping mirrors `api/pages`:
bad path/format → 422, unknown id → 404, invalid-for-state action → 409, missing token → 401.
`JobManager` gained `pause`/`resume`/`cancel`/`reprioritize` + the WS subscriber registry
(`subscribe`/`unsubscribe`, preserved across task (re)starts). `app.py` builds the `JobManager` on
startup, `recover_on_boot()`s, starts the sweeper, mounts both routers, and `shutdown()`s the
manager + watch observer on app exit.

**New dependencies:** none. No LICENSES row.

**Tests** (`tests/test_jobs_api.py`, `tests/test_jobs_ws.py` — `TestClient` + a stub-deps
`JobManager` swapped onto `app.state` sharing the app's loop/conn): REST needs a token (401
without); a 5-page job runs to `done` and `GET …/export?format=md` returns `text/markdown` with a
filename; unknown id → 404; bad format/path → 422; resume a `done` job → 409; reprioritize clamps to
`[-100,100]`; `GET /search` validates (`q` empty → 422) and returns a list; retry-failed re-runs
only the failed page; a deps-build failure at job start fails the JOB (`error="models not ready: …"`,
no page leased) without crashing the task (MEDIUM-F4); mid-job export emits in-order placeholders for
pending pages. WS: header-mismatch closes 4401 pre-accept; fallback timeout closes 4401; a valid
header token receives the snapshot + a terminal `ProgressEvent`; a valid message-token (fallback)
receives the snapshot.

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> 118 files unchanged
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 69 source files
$ .venv/Scripts/python.exe -m pytest tests/test_jobs_api.py tests/test_jobs_ws.py  -> 15 passed
$ .venv/Scripts/python.exe -m pytest                  -> 213 passed, 12 skipped, 1 xfailed
```

---

## Task 4.6 — Batch intake + watch folder (watchdog settle/debounce)

**What landed.** `POST /jobs/batch` (already scaffolded in 4.4) accepts `{paths, options,
recursive}`: dirs expand non-recursively by default (`recursive:true` opt-in) to supported
extensions via the shared `jobs/paths.py`; each resolved file → its own enqueued job. New
`jobs/watch.py`: `WatchFolderIngest.process_candidate` (settle → confirm size stable → validate →
dedupe by resolved path+mtime → enqueue) + `_WatchHandler` (marshals created/moved events onto the
engine loop via `loop.call_soon_threadsafe` → the loop executor, so the Observer thread never
touches the DB) + `start_watch_observer`. `app.py` starts the Observer at startup when
`settings.watch_dir` is set and stops it on shutdown.

**New dependency:** `watchdog==4.0.2` (Apache-2.0, shipped) — added to `engine/requirements.txt`,
`engine/pyproject.toml` `dependencies` + the mypy override list, and a `docs/LICENSES.md` runtime
row, ALL in this change. Verified present on PyPI (cp-agnostic `py3-none-win_amd64` wheel, published
2024-08-11).

**Tests** (`tests/test_jobs_batch.py`, `tests/test_jobs_watch.py`): a folder of two PDFs via
`POST /jobs/batch` → two jobs; mixed files+dirs → correct count; a bad path → 422; non-recursive by
default (1 job) vs `recursive:true` (2 jobs); dropping a fully-written PDF through
`process_candidate` → a job row with the dropped file as its source; same path+mtime de-dupes to one
enqueue; an unsupported `.txt` is skipped. The settle wrapper is deterministic given a fully-written
fixture (no live FS race needed).

**Gate (green on this host):**

```
$ .venv/Scripts/python.exe -m ruff check .            -> All checks passed!
$ .venv/Scripts/python.exe -m black --check . --line-length 100  -> 121 files unchanged
$ .venv/Scripts/python.exe -m mypy texora_engine      -> Success: no issues found in 70 source files
$ .venv/Scripts/python.exe -m pytest tests/test_jobs_batch.py tests/test_jobs_watch.py  -> 7 passed
$ .venv/Scripts/python.exe -m pytest                  -> 220 passed, 12 skipped, 1 xfailed
```





