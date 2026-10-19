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


