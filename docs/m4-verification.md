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
