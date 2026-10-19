# M4 review — job queue, checkpoint/resume, batch + watch folder, 5,000-page proof

The M4 engine backbone that backs the headline "unlimited pages / no work lost" promise is
implemented and verified: an additive v1→v2 SQLite schema with a per-page lease state machine, a
streaming asyncio runner that reuses the M3 assembler unchanged, crash-safe checkpoint/resume with
an immediate boot-revert, idempotent per-page export, per-page failure isolation with
retry-failed-only, a bearer-protected job-control REST + WebSocket API, batch + watch-folder intake,
and a memory/resume proof wired as a nightly 5,000-page CI gate with a real scaled-local measurement.
Tasks 4.1–4.7 are each `[x]` with recorded green-gate evidence in `docs/m4-verification.md`. Task
4.8 (Queue UI + incremental output) is honestly left `[ ]` — no `apps/desktop` or Rust changes exist
in the diff and the verification log stops at 4.7.

Watch for: 4.8 is not implemented (confirmed) — the milestone as scoped in the plan (tasks 4.1–4.8)
and `tasks.md §M4` is not fully complete, and its `done:` criterion ("E2E shows live per-page
progress") has no evidence. The engine correctness criteria are all met; the gap is UI wiring, which
does not affect the correctness-critical guarantees but does leave the milestone short of its listed
task set.

**Verdict**: CHANGES_REQUESTED

## High-level view

The correctness core is sound. The per-page lease lifecycle (`pending→leased→done|failed`) is
enforced entirely in SQL — `lease_next` is a single atomic `UPDATE … WHERE status='pending' …
RETURNING`, and `mark_done`/`mark_failed` carry a `WHERE lease_token` guard so a stale owner cannot
double-commit. Two revert methods are kept deliberately distinct: a TTL-gated sweeper
(`revert_expired_leases`) and an unconditional boot-revert (`revert_all_leased_for_active_jobs`) that
makes resume immediate rather than TTL-delayed. A real kill-and-resume test proves no page is lost or
duplicated and that a resumed PDF job renders only owned indices.

The runner schedules, it does not reinvent. It reuses `assemble_page`, `render_pdf_page`, and
`open_pdf` from M3; PDFs are rendered by index on a single document handle (skip-before-render), and
images stream through a new lazy `iter_image_pages` with pre-resume frames decoded-and-skipped.
Constant memory is held by a global semaphore and `page_workers=1` (the honest safe default against
the shared torch model), and is demonstrated by a real 200-page RSS measurement (~88–95 MiB, slope
≈ −0.001 MiB/page). The full 5,000-page run is wired as a nightly CI job and documented as CI-scaled,
not claimed as a local pass.

Per-page export is idempotent (temp + `os.replace`, committed before `mark_done`), and the on-demand
concat is byte-identical to the M3 whole-document exporters with the empty-fragment filter and an
anchored reference JSON exporter. Failure isolation wraps the offload in `asyncio.wait_for`, guards
oversize pages, catches any per-page exception, and never kills the job; retry resets only `failed`
rows. All SQLite goes through `db/` DAOs, FTS5 queries bind the query as a parameter and never expose
the rowid, every REST route is bearer-protected, and the WebSocket validates the same token on both
the header and message-fallback paths. The three pre-resolved design findings are all implemented,
and LICENSES rows exist for all four new dependencies.

The single gap is scope: task 4.8 is not in the diff. Everything the review flagged as
correctness-critical holds; the milestone is simply not finished to its listed task set.

<details>
<summary>Issues (1)</summary>

1. **Task 4.8 not implemented** — the Queue UI + incremental-output task (single typed engineClient
   job functions, Rust `tungstenite` progress bridge, i18next id/en strings, Batch/Queue screen) has
   no `apps/desktop`/`src-tauri` changes in the diff and is marked `[ ]` in `tasks.md §M4`; its
   `done:` criterion ("E2E shows live per-page progress") is unmet. Implement 4.8 (or the workflow
   owner explicitly re-scopes M4 to the engine-only 4.1–4.7 and defers 4.8) before M4 is closed.

</details>

<details>
<summary>Details</summary>

### Lease state machine and the two distinct reverts

`db/pages_dao.py` implements the lease lifecycle in SQL. `lease_next` selects the lowest-index
`pending` row in a subquery and flips it to `leased` with a fresh token and expiry in one
`UPDATE … RETURNING`, so two concurrent attempts can never lease the same row (the `test_pages_dao`
atomicity case covers this). `mark_done` and `mark_failed` both gate on `WHERE id=:id AND
lease_token=:tok`, so a reclaimed-then-recommitted page cannot be stomped by its previous owner.

The two reverts are correctly separated, which was the MEDIUM-2 design concern.
`revert_expired_leases(now)` only touches `status='leased' AND lease_expires_at < now` — the periodic
sweeper's job, and (because `job_page_timeout_s < job_lease_ttl_s` is enforced at config load) it can
only ever reclaim a crashed lease, never a live in-flight page. `revert_all_leased_for_active_jobs()`
reverts every leased row of a non-terminal job regardless of TTL; it is called exactly once by
`recover_on_boot` and is correct only under the single-process precondition (a freshly booted engine
owns no outstanding leases). The docstrings state this precondition explicitly.

`recover_on_boot` runs the unconditional revert first, then re-enqueues each `running|paused|queued`
job (paused stays paused) and never re-enrolls — enrollment happens once at `create_job`
(`bulk_insert_pending` in one transaction, with a `UNIQUE(job_id, page_index)` guard). The
`reset_failed_to_pending` retry path flips only `failed` rows and leaves `done` untouched.

### Kill-and-resume is proven, not asserted

`tests/test_jobs_resume.py::test_kill_mid_job_then_resume_no_lost_no_dup` is a genuine
kill-and-resume: run 1 starts a 5-page job with fast stub recognizers and a real minimal PDF, lets
≥1 page reach `done` (with a lease outstanding), then hard-cancels the task without graceful
shutdown. Run 2 reopens the same DB, calls `recover_on_boot`, and runs to completion. It asserts
`done == 5`, `pending == 0`, each index appears exactly once and is `done` (no lost, no duplicate),
and a `render_pdf_page` counter proves the done prefix is never re-rendered — at most one index (the
page in flight at the crash) is rendered twice. `test_resume_renders_only_owned_indices` independently
confirms a resumed job renders only the still-owned indices (MEDIUM-F1). The verification log records
these passing, and the scaled 40–60-page interrupt-resume benchmark corroborates it at larger scale.

### Idempotent export and byte-identical concat

`jobs/output.py::write_page_outputs_idempotent` writes each fragment and the full-`PageResult` JSON to
`<index>.<ext>.tmp` then `os.replace`s to the final name, and the runner's `_commit_done` performs
this write before `mark_done`, so a `done` page always has its artifact on disk and a page whose write
fails is marked `failed`, never `done`. Re-running a page overwrites the same deterministic path (no
append, no duplicate).

`build_markdown`/`build_latex` reproduce `document_to_markdown`/`document_to_latex`'s assembly exactly
— the markdown path joins blocks with `"\n\n"`, filters empties, and ends `body + "\n" if body else
"\n"`; the latex path builds the identical `parts` list (`preamble.rstrip("\n")`, `""`,
`\begin{document}`, `""`, body, `""`, `\end{document}`) and ends with a single trailing newline.
Because per-page fragments are themselves `"\n\n"`-joins of that page's blocks, concatenating them
with `"\n\n"` is byte-identical to the flattened whole-document join. `build_json` anchors to
`document_to_json` when every requested page is committed and otherwise emits in-order placeholders
for non-committed pages. The empty-fragment filter means a committed zero-block page contributes
nothing, which keeps the concat identical to the exporter over that exact set — this is the HIGH-1 /
MEDIUM-F3 / empty-fragment / json-anchor bundle, and `test_export_fragment_concat.py` covers full,
subset, and empty-body cases plus a JSON round-trip.

### Failure isolation and retry

The runner wraps the whole `assemble_page` offload in `asyncio.wait_for(…, timeout=job_page_timeout_s)`
and marks the page `failed` with `error="page timeout"` on expiry (the abandoned-thread trade-off is
documented inline — a Python thread cannot be force-killed, bounded by `page_workers` + the per-region
timeout). `jobs/guard.py::check_page_resources` rejects an oversize page before recognition using the
M2 `max_snip_pixels` bound. Any per-page exception is caught, logged with page context, and the loop
continues; the job finalizes `done` once every page is attempted. The resource check runs after the
page is rendered rather than before, so a decompression-bomb-sized render is produced in memory before
rejection — but `Image.MAX_IMAGE_PIXELS` is set globally in `app.py`, so a true bomb raises during
decode, matching the M2 posture. `test_jobs_failure_isolation.py` covers the hostile-page isolation,
retry re-running only the failed index, and the timeout path.

### API surface, DB access boundary, and auth

Every REST route lives on `jobs_router = APIRouter(dependencies=[Depends(require_token)])`, so bearer
auth is enforced on every non-health job route (the `401 without token` case is tested). The
WebSocket is on a separate router without the HTTP dependency (HTTPBearer cannot run on a WS scope)
and does its own `secrets.compare_digest` validation: header path validated before `accept()`
(mismatch → `close(4401)` pre-accept), message-token fallback after `accept()` under
`ws_token_timeout_s` (timeout/mismatch → `close(4401)`). Both paths guard on a non-empty expected
token, so they fail closed. No raw SQL appears in any route handler or in the runner — all access is
through `db/` DAOs, and `fts_dao.search` binds the query to `MATCH` as a parameter and exposes only
`region_id`/`job_id`/`snippet`/`bm25()`, never the implicit FTS rowid.

### Runner reuses the M3 pipeline

`runner.py` imports and calls `assemble_page`, `render_pdf_page`, and `open_pdf` directly; the PDF
path opens the document once and renders owned indices by index, and the image path uses the new lazy
`iter_image_pages` (the eager `load_image_pages` is left untouched for the synchronous snip routes).
`pipeline/deps.py::get_or_build_deps` is the Request-free shared provider both the route and the
runner use, tolerating a missing/None `pipeline_deps` attribute (NIT-4), and `api/pages._get_deps` is
a thin wrapper over it. No recognizer is reinvented.

### Memory proof and CI scaling honesty

`benchmarks/job_proof/test_memory_flat.py` samples RSS every 20 pages over a scaled synthetic PDF and
asserts the least-squares slope and peak bound; the recorded 200-page run shows ~88–95 MiB with a
slope of −0.0012 MiB/page — flat within noise. `test_interrupt_resume.py` kills mid-job and asserts
the resumed `done` set equals the full index set. `.github/workflows/job-proof-nightly.yml` runs the
same assertions at the full 5,000-page count on a nightly schedule (and on dispatch), defaulting
`TEXORA_PROOF_PAGES`/`TEXORA_PROOF_RESUME_PAGES` to 5000. `docs/m4-verification.md` states plainly
that the full count is the CI gate and only the scaled count runs locally, with a PENDING note — the
synthetic PDF is a real document and the RSS numbers are a real measurement, consistent with the
honesty invariant.

### Dependencies and recorded gate

`watchdog==4.0.2` (shipped) and Rust `tungstenite==0.23` (shipped, listed for the 4.8 bridge) plus
`reportlab==4.2.2` / `psutil==6.0.0` (test/CI only) each have a `docs/LICENSES.md` row. The test-only
deps are under `[project.optional-dependencies] test`, not in `dependencies`, so the PyInstaller
sidecar (which freezes only `dependencies`) never bundles them; all three unstubbed modules are in the
mypy override list. The verification log records `ruff` / `black --check` / `mypy` / `pytest` green at
every task (ending at 220 passed, 12 skipped, 1 xfailed for 4.6/4.7), which the instructions direct me
to trust rather than re-run.

</details>

<details>
<summary>File map</summary>

- `engine/texora_engine/db/schema.py` — v1→v2 additive migration (ordered `_MIGRATIONS`, gap guard, WAL + FK); `job`/`page`/`region`/`formula_candidate`/`correction` + `region_fts` FTS5 + triggers.
- `engine/texora_engine/db/{jobs,pages,regions,fts}_dao.py` — typed DAOs: job CRUD, atomic lease state machine + two distinct reverts + retry, region insert feeding FTS, parameter-bound FTS search.
- `engine/texora_engine/jobs/{manager,runner,output,guard,watch,paths,models}.py` — JobManager (concurrency, enrollment, recover_on_boot, sweeper, control actions, WS registry), streaming lease loop, idempotent writer + concat builders, resource guard, watch-folder ingest, path validator, Pydantic models.
- `engine/texora_engine/api/jobs.py` — bearer-protected REST routes + separate bearer-validated WS router.
- `engine/texora_engine/app.py` — build manager on startup, recover_on_boot, start sweeper, mount routers, start/stop watch observer, graceful shutdown.
- `engine/texora_engine/pipeline/deps.py` — Request-free shared PipelineDeps provider.
- `engine/texora_engine/ingest/images.py` — lazy `iter_image_pages` + `image_frame_count`.
- `engine/texora_engine/export/{markdown,latex,json_export}.py` — public per-page body emitters + reference JSON exporter.
- `engine/texora_engine/settings.py` — bounded job settings + `job_page_timeout_s < job_lease_ttl_s` validator.
- `scripts/make_synthetic_pdf.py`, `benchmarks/job_proof/*`, `.github/workflows/job-proof-nightly.yml` — synthetic generator + memory/resume proofs + nightly 5,000-page CI gate.
- `engine/tests/*` — 13 new/extended test files covering the above; `docs/m4-verification.md` records the real gate output; `docs/LICENSES.md` / `engine/pyproject.toml` / `engine/requirements*.txt` pin the new deps.
- Not present: any `apps/desktop` or `src-tauri` change (task 4.8).

Full diff: `git -C c:\data\kucing\texora\.worktrees\m4-jobs diff main...feat/m4-jobs`.

</details>
