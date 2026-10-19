# M4 Design — Job queue, checkpoint/resume, batch + watch folder (5,000-page proof)

Status: Design v4 (converged after a third review `m4-design-review.md`, verdict
CHANGES_REQUESTED: 0 HIGH, 3 MEDIUM, 3 NIT). The architecture scored as SOUND and source-verified;
v4 is a single convergence pass applying the three remaining MEDIUMs (empty-fragment byte-equivalence
when a committed page renders zero blocks; the missing unconditional boot-revert DAO method distinct
from the TTL sweeper; the unanchored JSON export + `result_json` fidelity) and the three NITs
(`get_or_build_deps` tolerating a missing/None `pipeline_deps` attribute; the `FtsHit`/rowid search
contract; the `anyio` LICENSES question). **No settled v3 decision was re-opened.** The v3 round's
4 MEDIUM / 2 NIT and the v2 round's 3 HIGH / 4 MEDIUM / 4 NIT remain resolved. Every finding is
resolved below; the point-by-point responses are in §18. Each fix was checked against the **actual** M2/M3
source (`ingest/pdf.py` `render_pdf_page`/`open_pdf`, `api/pages._get_deps`, the authoritative
`design.md §4` ER, export leaf modules, `assemble_page`, `db/schema.py`, `settings.py`,
`security.py`), not taken on a prior draft's word.
Worktree: `c:\data\kucing\texora\.worktrees\m4-jobs`.
Scope: tasks **4.1–4.8** in `.kiro/specs/texora/tasks.md`. Requirements traced:
`R-JOB-1/2/3/4/5/6/7`, `R-UI-1/6`, `R-SEC-3`, and `DoD-1/2`.

> **This milestone backs the headline promise:** *unlimited PDF pages (10 or 10,000) via streaming
> + per-page SQLite checkpoint/resume with approximately constant memory.* M3 built the
> **single-document, synchronous** pipeline (`assemble_page` over `iter_pdf_pages`). M4 wraps that
> exact per-page unit in an **asynchronous, crash-safe, resumable job runner** with a control API,
> progress WebSocket, batch + watch-folder intake, and a CI proof. M4 **reuses M3 recognition
> unchanged** — it never reinvents the pipeline; it schedules it.

---

## 0. Overview

M4 adds one new engine package and extends four existing ones, all under
`engine/texora_engine/`, and keeps every M2/M3 seam intact:

- **`db/`** (extend) — add the full M4 schema (`JOB`, `PAGE`, `REGION`, `FORMULA_CANDIDATE`,
  `CORRECTION`) + an FTS5 index, as an **additive migration v1→v2**. The existing `MODEL`/`SETTING`
  tables and the `connect`/`migrate`/`init_db` pattern are **extended, never replaced**. New typed
  DAOs (`jobs_dao.py`, `pages_dao.py`, `fts_dao.py`) sit beside `models_dao.py`/`settings_dao.py`.
  (4.1)
- **`jobs/`** (new package) — the streaming runner, the per-page lease state machine, the
  checkpoint/resume logic, the idempotent per-page export writer, the failure-isolation guard, and
  the watch-folder watcher. This is where all M4 scheduling logic lives. (4.2, 4.3, 4.5, 4.6)
- **`api/jobs.py`** (new) — the bearer-protected job-control REST routes + the progress WebSocket,
  mounted exactly like the existing `pages_router`. (4.4)
- **`scripts/`** + **`benchmarks/`** (extend) — a synthetic-PDF generator and the CI memory/resume
  proof harness. (4.7)
- **`apps/desktop/src`** (extend) — the Batch/Queue screen, job functions on the single typed
  `engineClient`, a Rust→webview event bridge for live progress, and `id`/`en` i18next strings.
  (4.8)

**Hard sequencing constraint honored throughout.** Implementation runs **strictly sequentially —
exactly one coder writing the single worktree at any instant.** The design is therefore a single
ordered dependency chain (4.1 → 4.2 → 4.3 → 4.5 → 4.4 → 4.6 → 4.7 → 4.8); no feature requires two
writers at once, and each task compiles/tests green before the next begins. (§14 states the chain
and why it is race-free.)

**Honesty invariants carried from M2/M3, enforced here too.** No fabricated output anywhere in a
production path. A page that cannot be processed becomes `failed`; a region the pipeline cannot
recognize stays `needs_review`/`failed` (already enforced inside `assemble_page`). The 5,000-page
claim is proven on **this host at a scaled page count** and promoted to a **CI nightly** job at the
full count — documented honestly as *CI-scaled*, never faked (§12). SQLite (WAL) + FTS5 are
accessed **only** through `db/` DAOs — no raw SQL in routes or the runner (§4). The engine stays
loopback-only with a bearer token on every non-health route, including the WebSocket (§9).

---

## 1. Technology stack (LOCKED on approval)

No new recognition models. M4 is scheduling + persistence + UI, so the additions are small,
permissive, and already-pinnable.

| Concern | Choice | Version (pin) | License | Verdict / why |
|---|---|---|---|---|
| Persistence | **SQLite via stdlib `sqlite3`** (WAL) + **FTS5** | Python 3.11 stdlib; FTS5 is compiled into the CPython/PyInstaller SQLite | Public Domain (SQLite) | Already the M2 choice; FTS5 ships in the bundled SQLite. No new dep. |
| Async runtime | **`asyncio`** (stdlib) + FastAPI's existing event loop | 3.11 stdlib | PSF | FastAPI already runs an asyncio loop; the runner is an asyncio task. |
| CPU-bound offload | **stdlib `concurrent.futures.ThreadPoolExecutor` + `loop.run_in_executor`** (no `anyio` import) | Python 3.11 stdlib | PSF | `assemble_page` is sync/CPU-bound; it runs in a bounded thread pool via the stdlib executor, never blocking the loop. Stdlib-only, so no new/`anyio` LICENSES question (NIT-6). |
| WebSocket | **FastAPI/Starlette `WebSocket`** (already present) | as pinned by fastapi | BSD-3-Clause | No new dep; one `WS /jobs/{id}/events` route. |
| Watch folder | **`watchdog`** | 4.0.2 | Apache-2.0 | Cross-platform FS events (Windows `ReadDirectoryChangesW`), permissive. Debounced + settle-check wrapper (§8). |
| Synthetic PDF gen | **`reportlab`** | 4.2.2 | BSD-3-Clause (ReportLab Open-Source) | Generates the N-page synthetic math PDF for the proof; permissive. **Test/CI dependency only**, not shipped in the installer. |
| Memory assertion (CI) | **`psutil`** | 6.0.0 | BSD-3-Clause | RSS sampling for the memory-flat assertion. **Test/CI dependency only.** |
| Rust WS bridge | **`tungstenite`** (sync) — a **new** transport (today `src-tauri` has `ureq` only); reuses the Tauri-event re-emit pattern, not the HTTP poller (§9.3, NIT-F5) | tungstenite 0.23 | MIT/Apache-2.0 | Rust reads the engine WS on a new blocking thread and re-emits Tauri events; permissive. |

Each new row (`watchdog`, `reportlab`, `psutil`, `tungstenite`) is added to `docs/LICENSES.md` **in
the same change** that introduces it (steering: "new dependency → add a row to LICENSES.md"), with
the test-only vs shipped verdict recorded. `reportlab`/`psutil` are declared under a `[test]`/`dev`
extra so they are **not** frozen into the PyInstaller sidecar; this "test-only extra + LICENSES rows
same change" rule is promoted to an explicit **4.7 done-check** (§12). **No `anyio` row is needed
(NIT-6):** the CPU-bound offload uses the stdlib `concurrent.futures.ThreadPoolExecutor` +
`loop.run_in_executor` path the §3.1 loop already shows, so the runner never imports `anyio`
directly and `anyio` stays a pure transitive Starlette dependency — there is no first-party import
to require a LICENSES row.

**Decision — asyncio task runner, not a separate process/thread framework.** The engine already
has an asyncio event loop (FastAPI). A job is a long-lived asyncio task that pulls pages, offloads
each `assemble_page` call to a bounded thread pool, and checkpoints to SQLite. Alternatives
considered and rejected: (a) a `multiprocessing` worker pool — rejected because it would duplicate
the loaded torch/ONNX models per process (large memory, breaks the constant-memory goal) and
complicate the single-user loopback model; (b) an external queue (Celery/RQ + broker) — rejected
as massive overkill for a single-user offline desktop app and a new runtime dependency. One
asyncio task per running job, with global concurrency bounded by a semaphore, keeps memory flat and
needs zero new infrastructure. (R-JOB-1/4)

**Decision — single-loop SQLite access (MEDIUM-3).** `db.connect` opens exactly one connection with
`check_same_thread=False` and relies on app-level serialization (verified in `schema.py`). M4 adds a
sweeper and a watch-folder thread, so the design pins an explicit, enforced rule: **every SQLite
call — the `_run_job` coroutine, every DAO, and the periodic sweeper — executes on the engine's
single asyncio event loop; thread-pool workers running `assemble_page` never touch `conn`; the
watchdog `Observer` thread only calls `loop.call_soon_threadsafe` to marshal enqueue work onto the
loop.** The sweeper is an `asyncio` task (not a `threading.Timer`). Because all writes run on one
loop, concurrent write transactions are impossible by construction, preserving the M2 serialization
assumption. The hot path already obeys this: `assemble_page` runs in a worker thread while
`lease_next`/`mark_done`/`mark_failed` are awaited on the loop — the worker returns a `PageResult`
and the loop performs all DB mutation.

---

## 2. What M4 changes vs. what it reuses

**Reused unchanged (the recognition core):**

- `pipeline.assemble_page(rendered, image, deps)` — the per-page unit. It is already pure per page
  (no cross-page state), already frees its bitmap in a `finally`, and already applies per-region
  timeouts. The runner calls it exactly as `api/pages.py` does.
- `ingest.render_pdf_page(pdf, index, cfg)` — a **public, indexed** single-page renderer (verified
  in `ingest/pdf.py`): given an open `pdfium.PdfDocument` and a page index it renders exactly that
  page (with the adaptive-DPI + one-shot small-font raise), returns `(RenderedPage, PIL.Image)`, and
  the caller owns/closes the image. `ingest.open_pdf(path)` is the context manager that opens the
  document once. `ingest.iter_pdf_pages(path, cfg)` is a thin lazy wrapper that `open_pdf`s and then
  `render_pdf_page`s indices `0..len(pdf)` **in order**. **The runner does NOT drive the sequential
  `iter_pdf_pages` for PDFs** — it would re-render and discard the whole `done` prefix on resume
  (MEDIUM-F1). Instead the runner opens the document once via `open_pdf` and calls
  `render_pdf_page(pdf, index, cfg)` for **only the indices it still owns** (the `pending` set), so a
  resumed 5,000-page job that already did pages 0..4,998 renders exactly one page (4,999), not 5,000.
  See §3.1 and §6.2. **Images are NOT lazy today**:
  `ingest.images.load_image_pages(path, settings)` returns a fully materialized
  `list[tuple[RenderedPage, Image.Image]]` holding every frame's RGB bitmap at once. M4 adds a new
  lazy `iter_image_pages` for the streaming path (see §2.1 and MEDIUM-1 resolution); the existing
  `load_image_pages` stays for the synchronous `api/pages.py` callers unchanged.
- `PipelineDeps` (built once, cached on `app.state`). The real `api/pages._get_deps(request:
  Request)` reads `request.app.state.{pipeline_deps,settings,model_store}`, builds the layout/text/
  formula engines, caches on `app.state.pipeline_deps`, and raises `ModelNotReady` /
  `TesseractUnavailable` / the factory misconfig errors that the route maps to 409/500. The runner
  has **no `Request`**, so M4 factors the body into a `Request`-free shared provider
  `pipeline.deps.get_or_build_deps(app_state) -> PipelineDeps` (§11, MEDIUM-F4) that both the route
  and the runner call.
- The **recognition** core of the export leaf modules is reused, but the export leaf modules
  **expose only whole-document entry points today** — `document_to_markdown(doc: DocumentResult,
  opts)` and `document_to_latex(doc: DocumentResult, opts)`; the per-page renderer `_render_page`
  is module-private in both. The runner **cannot call a per-page exporter because none is public.**
  M4 therefore adds two thin **public per-page body emitters** (`render_page_markdown`,
  `render_page_latex_body`) that wrap the existing private `_render_page`, and performs a single
  document wrap at concat time (§7.1). M4 adds the **idempotent write wrapper** around those
  emitters (§7).
- `db.connect`/`migrate`/`init_db`, `security.require_token`, `logging_config.get_logger`,
  `Settings` (pydantic-settings), the Rust proxy pattern.

**Extended:**

- `db/schema.py` — migration v1→v2 adds the M4 tables + FTS5 (§4).
- `settings.py` — new bounded job settings (concurrency, lease TTL, page timeout, watch dir) (§3.4).
- `app.py` — construct the `JobManager` once on startup, store on `app.state`, recover orphaned
  leases on boot, mount `jobs_router`, start the watch-folder watcher if configured, and shut the
  manager down gracefully on app exit.
- `engineClient.ts` + Rust `lib.rs`/`supervisor.rs` — job commands + a progress event bridge (§9).

**New:** `jobs/` package, `api/jobs.py`, `scripts/make_synthetic_pdf.py`,
`benchmarks/job_proof/`, the Batch/Queue UI, plus one additive helper in each of
`ingest/images.py` (`iter_image_pages`), `export/markdown.py` (`render_page_markdown`),
`export/latex.py` (`render_page_latex_body`), and a new `export/json_export.py`
(`document_to_json`, the reference JSON exporter the json concat is proven against — §7.1, MEDIUM-3).

### 2.1 Streaming image intake (MEDIUM-1 resolution)

The constant-memory guarantee (R-JOB-1) must hold for multi-page TIFFs too, so the runner cannot
use `load_image_pages` (it eagerly decodes and holds **all** frame bitmaps — verified in source).
M4 adds a **lazy** frame iterator beside it, mirroring `iter_pdf_pages`:

```python
# ingest/images.py  (new, additive — load_image_pages is left untouched for api/pages.py)
def iter_image_pages(path: str | Path, settings: Settings) -> Iterator[tuple[RenderedPage, Image.Image]]:
    """Yield one (RenderedPage, RGB Image) per frame, loading+converting ONE frame at a time.

    Uses ImageSequence.Iterator (already used by load_image_pages), calls frame.load() then
    _to_rgb() per frame, applies the same ImageBounds guards, and never holds more than the
    current frame's bitmap. The caller owns and must close each yielded image (same contract as
    iter_pdf_pages).
    """
```

The runner's render seam (§3.1) dispatches on source kind. **PDFs use the indexed primitive**
`render_pdf_page(pdf, index, cfg)` (the producer skips `done` indices *before* rendering — the
skip-capable path, MEDIUM-F1); **images use the sequential lazy `iter_image_pages`**. `iter_image_pages`
is necessarily sequential because TIFF frames are walked in order by `ImageSequence.Iterator` and
cannot be randomly seeked, so on a resumed image job the frames **before** the resume point are
decoded-and-skipped (not recognized). This is accepted and cheap: frame decode is a fraction of a
recognition pass, exactly one frame bitmap is in flight at a time (the iterator holds no more), and
it is closed immediately if skipped — so constant memory still holds. Both paths run under the
semaphore, so a 10,000-frame TIFF streams with the same flat memory as a 10,000-page PDF.
`load_image_pages` is **not** described as lazy anywhere; it remains the eager helper for the
synchronous single-image snip/page routes where the frame count is small by construction.

---

## 3. The streaming job runner (4.2) — `jobs/runner.py`, `jobs/manager.py`

### 3.1 Model

A **`JobManager`** (one instance, on `app.state.job_manager`) owns:

- a global **`asyncio.Semaphore(max_concurrent_pages)`** — the single back-pressure valve across
  *all* running jobs (so a 2nd job cannot blow memory);
- a bounded **`ThreadPoolExecutor(max_workers=page_workers)`** for the CPU-bound `assemble_page`
  calls. **Correctness note (HIGH-2):** `assemble_page` builds its *own* per-call
  `ThreadPoolExecutor(max_workers=region_concurrency)` and invokes the **shared** torch/ONNX
  singletons (`deps.formula`/`deps.text`). `region_concurrency` therefore serializes regions
  **only within a single page** — it does **not** serialize across pages. Two concurrent
  `assemble_page` calls (i.e. `page_workers > 1`) would enter the shared pix2tex/torch model from
  two threads at once; PyTorch eager modules and pix2tex are not guaranteed thread-safe for
  concurrent `forward`, and the project ships `snip_concurrency=1`/`region_concurrency=1`
  (settings.py comment: "1 serializes the shared torch model") precisely to prevent that. **M4
  therefore defaults `job_page_workers=1`** and scopes page-level parallelism against the single
  shared model **out of M4** (documented as an M7 performance seam, alongside GPU batch scheduling).
  The `le` bound stays so a future M7 change can widen it, but only once a global per-model
  inference lock (or per-worker model instances) exists; M4 does not add that. With the default,
  `assemble_page` runs one-at-a-time on the pool and the render/offload path still stays off the
  event loop.
- a registry `dict[str, JobHandle]` of running jobs, each with an `asyncio.Task`, an
  `asyncio.Event` pause gate, a `cancel` flag, and a `JobProgress` accumulator;
- a `WeakSet`/list of connected WebSocket progress subscribers per job (§9).

Each running job is **one `asyncio.Task`** (`_run_job`). Its loop:

```
for each page index the job still owns (streamed, in priority/range order):
    await pause_gate.wait()                 # paused jobs block here, holding no page
    if cancel_requested: break
    async with semaphore:                   # global back-pressure: cap in-flight pages
        page_id = pages_dao.lease_next(conn, job_id, lease_token, lease_ttl)
        if page_id is None: continue         # already done/leased by prior run
        # PDF: render_pdf_page(pdf, page_index, cfg) on the single open_pdf handle — indexed, so
        #      a resumed job renders ONLY owned indices (never the done prefix).
        # Image: next frame from iter_image_pages; frames before the resume point are
        #        decoded-and-skipped (sequential, cheap, one frame in flight).
        rendered, image = render_one(job, page_index)
        try:
            result = await loop.run_in_executor(pool, assemble_page, rendered, image, deps)
            write_page_outputs_idempotent(job, page_index, result)   # §7 temp+rename
            pages_dao.mark_done(conn, page_id, lease_token, result_summary)
        except PageTimeout | PageResourceError | Exception as exc:
            pages_dao.mark_failed(conn, page_id, lease_token, str(exc))   # §5 isolation
        finally:
            image.close()                    # assemble_page also closes; double-close safe
        emit_progress(job)                   # §9 WS event
finalize_job(job)                            # status=done|failed|canceled; close export files
```

**Key properties:**

- **Constant memory (R-JOB-1):** at most `max_concurrent_pages` bitmaps exist at once (the
  semaphore caps it); each page's bitmap and intermediates are freed in `finally` (and inside
  `assemble_page`). Pages are pulled lazily from `iter_pdf_pages` — the whole PDF is never loaded.
  The runner holds only small `PageResult` summaries transiently; full results stream to disk
  (§7) and to SQLite as compact JSON, not kept in a growing in-memory list. (§12 proves this.)
- **Streaming render seam (render primitive pinned — MEDIUM-F1).** The producer dispatches on
  source kind, and the two kinds use **different** render primitives because PDFs can be randomly
  indexed and image frames cannot:
  - **PDF:** the producer opens the document **once** via `ingest.open_pdf(path)` (one
    `pdfium.PdfDocument` handle per job; pdfium handles are not thread-safe) and calls
    `ingest.render_pdf_page(pdf, index, cfg)` for **only the indices it still owns** — i.e. the
    `pending` index set it computes from `pages_dao.counts`/a `done` index set before rendering.
    It never drives the sequential `iter_pdf_pages`, so a resumed job renders only the pages it
    still owns and never re-renders-and-discards a `done` prefix. This is the "skip-before-render"
    path, now concrete: `render_pdf_page` *is* the indexed seam that makes skipping real.
  - **Image:** the producer walks `iter_image_pages` (§2.1), which is inherently sequential (TIFF
    frames must be iterated in order). On resume, frames before the first owned index are
    decoded-and-skipped (each closed immediately), which is cheap relative to recognition and keeps
    exactly one frame bitmap in flight — constant memory holds.

  Two concurrency designs were considered:
  - **(A) single render producer + a worker pool that consumes rendered pages**, and
  - **(B) N workers each opening the source and seeking to their own page.**
  **Chosen: (A)** — one source handle per job, a single producer coroutine renders each owned page
  (indexed for PDFs, sequential-skip for images) and hands each `(rendered, image)` to the executor
  under the semaphore. Render stays serial (cheap relative to recognition); with `page_workers=1`
  (default, HIGH-2) recognition is serial too, which is correct against the shared model. (B) was
  rejected: multiple `pdfium.PdfDocument` handles are thread-unsafe to share and opening N handles
  wastes memory, defeating the constant-memory goal.
- **Back-pressure (R-JOB-1/4):** the producer `await`s the semaphore before rendering the next
  page, so it cannot out-run the workers and pile up bitmaps. The queue between producer and
  workers is implicitly bounded by the semaphore (permit count == max in-flight pages).
- **Bounded concurrency sizes (R-JOB-4):** `max_concurrent_pages` defaults to 2 (the memory valve)
  and `page_workers` defaults to **1** (HIGH-2: one safe entry into the shared model). Both are
  `Settings` fields (§3.4). GPU batch scheduling across pages **and** multi-worker recognition
  against one shared model are **out of scope for M4** (M7 performance concerns); the assembler's
  per-region serialization is correct within a page, and the design leaves a documented seam
  (`job_page_workers`, bounded `le=64`) to widen later only once a global per-model inference lock
  or per-worker model instances exist. M4 ships the honest safe default and does not claim
  cross-page model parallelism it cannot deliver.

### 3.2 Per-page lease state machine (R-JOB-2/4)

Each `PAGE` row is an atomic SQLite state transition:

```
          lease_next (UPDATE ... WHERE status='pending')
pending ─────────────────────────────────────────────▶ leased
   ▲                                                      │
   │ revert_expired_leases (lease_expires_at < now)       │ mark_done
   │ (on boot + periodic sweep)                           ▼
   └──────────────────────────────────────────────────  done
                                                          │ mark_failed (also from leased)
                                                          ▼
                                                        failed ──retry-failed──▶ pending
                                        (assemble_page may roll content quality up to
                                         rollup_status=needs_review in the PageResult;
                                         page.status stays `done` — the two columns are
                                         orthogonal, §4.2 MEDIUM-F2)
```

`lease_next` is a single atomic statement so two workers can never lease the same page:

```sql
-- in pages_dao.lease_next (conn is WAL; the UPDATE...RETURNING is atomic)
UPDATE page
   SET status='leased', lease_token=:tok,
       lease_expires_at=:now_plus_ttl, attempts=attempts+1
 WHERE id = (
     SELECT id FROM page
      WHERE job_id=:job AND status='pending'
      ORDER BY page_index     -- range/list order is enforced by which rows exist (see §6)
      LIMIT 1
 )
RETURNING id, page_index;
```

`UPDATE ... RETURNING` with the subquery-selected single row is atomic under WAL + the engine's
serialized single-connection access (the M2 note on `check_same_thread=False` + app-level
serialization holds; the runner uses the shared connection from a single asyncio loop, and DAO
writes use `with conn:` transactions). Even if a future change widens connection use, the
`WHERE status='pending'` guard + `RETURNING` guarantees exactly-once lease per row.

### 3.3 Progress accounting

`JobProgress` is computed from DAO counts (`pages_dao.counts(conn, job_id)` →
`{pending, leased, done, failed, needs_review}`), plus an EWMA of per-page durations kept in memory
per job for **pages/min** and **ETA** (`eta = remaining / pages_per_min`). Counts are the source of
truth (survive restart); the rate/ETA are best-effort runtime estimates reset on resume. (R-JOB-5)

### 3.4 New settings (bounded, pydantic-validated — §3.4)

Added to `Settings` (env prefix `TEXORA_ENGINE_`, same as today); no magic constants in code:

| Field | Default | Bound | Purpose |
|---|---|---|---|
| `job_max_concurrent_pages` | 2 | `ge=1, le=64` | global in-flight page cap (the memory valve). |
| `job_page_workers` | **1** | `ge=1, le=64` | thread-pool size for `assemble_page`. Default 1 serializes the shared torch model (HIGH-2); >1 is an M7 seam gated on a per-model inference lock. |
| `job_lease_ttl_s` | 300.0 | `gt=0` | lease lifetime; a crashed lease older than this reverts. **Must be `> job_page_timeout_s`** (validated, HIGH-3). |
| `job_page_timeout_s` | 120.0 | `gt=0` | whole-page wall-clock timeout (§5), distinct from per-region. **Must be `< job_lease_ttl_s`** so a live page never outlives its lease. |
| `job_lease_sweep_s` | 30.0 | `gt=0` | interval of the background expired-lease sweeper (an asyncio task, MEDIUM-3). |
| `job_output_dir` | `output` | — | root for streamed per-page export artifacts (§7). |
| `watch_dir` | `None` | — | watch-folder path; `None` disables watch mode (§8). |
| `watch_settle_s` | 2.0 | `gt=0` | quiet period a new file must be stable before enqueue (§8). |
| `ws_token_timeout_s` | 5.0 | `gt=0` | fallback-path wait for the first WS token frame before `close(4401)` (MEDIUM-4). |

**Cross-field validator (HIGH-3).** A Pydantic v2 `@model_validator(mode="after")` on `Settings`
enforces `job_page_timeout_s < job_lease_ttl_s` and raises a `ValueError` (startup config error) if
violated. This is the invariant that makes lease renewal unnecessary: a page is force-failed by its
wall-clock timeout strictly before its lease could expire, so the sweeper can only ever reclaim a
lease from a **crashed** process, never from a live in-flight page (see §6.2).

---

## 4. Data model + migrations (4.1) — `db/schema.py`, new DAOs

### 4.1 Migration mechanism (extend, don't replace)

`schema.py` already has a `user_version`-guarded `migrate`. M4 converts the single `_SCHEMA_SQL`
blob into an **ordered migration list** keyed by target version, preserving v1 exactly:

```python
SCHEMA_VERSION = 2

# _V1_SQL IS the current _SCHEMA_SQL verbatim (CREATE TABLE IF NOT EXISTS model / setting).
# Re-running it is harmless by construction (IF NOT EXISTS), which is what makes a fresh DB
# safely run step 1 then step 2.
_MIGRATIONS: dict[int, str] = {
    1: _V1_SQL,   # the existing model + setting tables, VERBATIM (no change)
    2: _V2_SQL,   # JOB/PAGE/REGION/FORMULA_CANDIDATE/CORRECTION + FTS5 + triggers
}

def migrate(conn):
    current = _user_version(conn)
    for version in range(current + 1, SCHEMA_VERSION + 1):
        assert version in _MIGRATIONS, f"missing migration step v{version}"  # gap guard
        logger.info("applying migration -> v%d", version)
        with conn:                       # one transaction per step
            conn.executescript(_MIGRATIONS[version])
            conn.execute(f"PRAGMA user_version={version};")
```

**Stated invariants (MEDIUM-2).** (a) `_MIGRATIONS` must contain **every** key in the inclusive
range `2..SCHEMA_VERSION` (the `assert` guards against a future gap and fails loudly rather than
silently skipping a step). (b) The v1→v2 refactor intentionally drops the old
`if current >= SCHEMA_VERSION: return` fast-path because the loop is *already* a no-op when
`current == SCHEMA_VERSION`: `range(SCHEMA_VERSION + 1, SCHEMA_VERSION + 1)` is empty. (c) `_V1_SQL`
is `_SCHEMA_SQL` **verbatim**, and because it uses `CREATE TABLE IF NOT EXISTS`, running step 1 on a
fresh DB and then step 2 is harmless and order-correct. So: a fresh DB (`user_version==0`) runs 1
then 2; a v1 DB (an M2/M3 user, `user_version==1`) runs only 2; a v2 DB is a no-op. `init_db` and
`connect` are unchanged. Existing `MODEL`/`SETTING` data survives untouched.

### 4.2 M4 tables (v2 DDL)

Follows the ER diagram in `.kiro/specs/texora/design.md §4`, made concrete. All timestamps are ISO
8601 text (UTC); all JSON blobs are `TEXT`. Foreign keys cascade on job delete.

```sql
-- _V2_SQL (abbreviated DDL; full form in db/schema.py)
CREATE TABLE job (
    id            TEXT PRIMARY KEY,                -- uuid4 hex
    source_path   TEXT NOT NULL,                   -- sanitized absolute path
    source_name   TEXT NOT NULL,
    status        TEXT NOT NULL,                   -- queued|running|paused|done|failed|canceled
    options_json  TEXT NOT NULL,                   -- export formats, dpi, range/list, etc.
    total_pages   INTEGER NOT NULL DEFAULT 0,
    priority      INTEGER NOT NULL DEFAULT 0,       -- higher = sooner (reprioritize)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_job_status_priority ON job(status, priority DESC, created_at);

CREATE TABLE page (
    id               TEXT PRIMARY KEY,             -- uuid4 hex
    job_id           TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    page_index       INTEGER NOT NULL,             -- 0-based source index
    status           TEXT NOT NULL,                -- LEASE LIFECYCLE: pending|leased|done|failed
    lease_token      TEXT,
    lease_expires_at TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    rollup_status    TEXT,                          -- CONTENT QUALITY: ok|needs_review|failed
    result_json      TEXT,                          -- the page's serialized PageResult (Pydantic v2 model_dump_json) — FULL, lossless
    avg_confidence   REAL,
    error            TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    UNIQUE(job_id, page_index)
);
CREATE INDEX idx_page_job_status ON page(job_id, status, page_index);

CREATE TABLE region (
    id             TEXT PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,
    bbox_json      TEXT NOT NULL,
    det_confidence REAL,
    reading_order  INTEGER NOT NULL,
    content        TEXT,                            -- text or latex (for FTS)
    rec_confidence REAL,
    validation     TEXT                             -- ok|needs_review|failed
);
CREATE INDEX idx_region_page ON region(page_id, reading_order);

CREATE TABLE formula_candidate (
    id          TEXT PRIMARY KEY,
    region_id   TEXT NOT NULL REFERENCES region(id) ON DELETE CASCADE,
    engine_id   TEXT NOT NULL,
    latex       TEXT NOT NULL,
    confidence  REAL,
    latex_valid INTEGER NOT NULL DEFAULT 0          -- M5 ensemble fills this; table exists now
);

CREATE TABLE correction (
    id          TEXT PRIMARY KEY,
    region_id   TEXT REFERENCES region(id) ON DELETE SET NULL,
    original    TEXT NOT NULL,
    corrected   TEXT NOT NULL,
    created_at  TEXT NOT NULL                        -- M5 review UI fills this; table exists now
);

-- FTS5 full-text index over recognized content for the Library search (R-UI-1).
CREATE VIRTUAL TABLE region_fts USING fts5(
    content,
    region_id UNINDEXED,
    job_id    UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
```

**FTS population via triggers** (so the index can never drift from `region`, and routes/runner
never touch FTS directly):

```sql
CREATE TRIGGER region_ai AFTER INSERT ON region BEGIN
  INSERT INTO region_fts(rowid, content, region_id, job_id)
  SELECT new.rowid, new.content, new.id, (SELECT job_id FROM page WHERE id = new.page_id)
  WHERE new.content IS NOT NULL;
END;
CREATE TRIGGER region_ad AFTER DELETE ON region BEGIN
  DELETE FROM region_fts WHERE rowid = old.rowid;
END;
CREATE TRIGGER region_au AFTER UPDATE ON region BEGIN
  DELETE FROM region_fts WHERE rowid = old.rowid;
  INSERT INTO region_fts(rowid, content, region_id, job_id)
  SELECT new.rowid, new.content, new.id, (SELECT job_id FROM page WHERE id = new.page_id)
  WHERE new.content IS NOT NULL;
END;
```

`FORMULA_CANDIDATE` and `CORRECTION` are created now (4.1 lists them) but written by M5; M4 leaves
them empty. This is honest: the tables exist per the task list, and no M4 code fabricates rows in
them.

**PAGE status split — intentional refinement of the authoritative ER (MEDIUM-F2).** The
authoritative `.kiro/specs/texora/design.md §4` models PAGE with a **single** `status` column whose
domain is `pending|leased|done|failed|needs_review`. M4 **deliberately refines** this into **two
orthogonal columns** because the lease lifecycle and content quality are independent concerns that a
single enum conflates:

- `page.status` is the **lease lifecycle** `pending|leased|done|failed` — it drives the state
  machine (§3.2), leasing, resume, and retry. A page that was recognized successfully is `done`
  regardless of whether its content needs human review.
- `page.rollup_status` is the **content quality** `ok|needs_review|failed` rolled up from the
  `PageResult` (a page can be `status='done'` *and* `rollup_status='needs_review'` when a region
  could not be confidently recognized — the honesty invariant).

Consequences the design pins so M5 does not query the wrong column:

1. **The review/library surface (M5 task 5.2) MUST filter `rollup_status = 'needs_review'`, NOT
   `status = 'needs_review'`.** The value `needs_review` never lands in `page.status`; a query
   against `status` would return zero rows. This is called out here and will be re-stated in the M5
   design so the M5 coder uses `rollup_status`.
2. **Spec erratum.** This is a documented divergence from the authoritative ER, flagged the same way
   M2/M3 flagged errata: a one-line erratum comment is added to `.kiro/specs/texora/design.md §4`
   (and mirrored in `tasks.md` near 4.1) stating *"M4 refinement: PAGE.status is the lease lifecycle
   (`pending|leased|done|failed`); content quality lives in `rollup_status`
   (`ok|needs_review|failed`); the review surface queries `rollup_status`."* The erratum is written
   in the same change as 4.1 (it is a doc edit inside the worktree, no new writer). See M4-ADR-9.

### 4.3 New DAOs (typed, no raw SQL outside `db/`)

- **`jobs_dao.py`** — `JobRow` dataclass; `create_job`, `get_job`, `list_jobs`, `set_status`,
  `set_priority`, `update_timestamps`, `delete_job`.
- **`pages_dao.py`** — `PageRow` dataclass; `bulk_insert_pending(job_id, indices)`, `lease_next`,
  `mark_done`, `mark_failed`, `revert_expired_leases(now)`, `revert_all_leased_for_active_jobs()`,
  `reset_failed_to_pending(job_id)`, `counts(job_id)`, `get_page`. The two revert methods are
  **distinct operations (MEDIUM-2)** and must not be conflated:
  - `revert_expired_leases(now)` — the **TTL sweeper / crash-recovery** method. Reverts only
    `leased` rows whose `lease_expires_at < now`:
    `UPDATE page SET status='pending', lease_token=NULL, lease_expires_at=NULL
       WHERE status='leased' AND lease_expires_at < :now`. Called by the periodic sweeper (§6.2).
  - `revert_all_leased_for_active_jobs()` — the **boot-only** method. Reverts **all** `leased` rows
    for non-terminal jobs **unconditionally**, regardless of `lease_expires_at`:
    `UPDATE page SET status='pending', lease_token=NULL, lease_expires_at=NULL
       WHERE status='leased'
         AND job_id IN (SELECT id FROM job WHERE status IN ('running','paused','queued'))`.
    Called exactly once by `recover_on_boot` (§6.2). **Precondition (single-process, NIT-2):** this
    unconditional revert is correct only because exactly one engine process exists (single-user
    loopback model); a freshly booted process owns no outstanding leases and no other live process
    can hold a valid lease, so reverting every `leased` row cannot steal a lease from a concurrent
    worker. Using this at boot (instead of the TTL method) makes resume **deterministic and
    immediate** — a page leased by the killed process is reclaimable at once, not after its TTL
    elapses — which is what the §13 interrupt-resume test depends on.
- **`regions_dao.py`** — `insert_regions(page_id, regions)` (populates `region`, triggers fill FTS).
- **`fts_dao.py`** — `search(query, limit, offset) -> list[FtsHit]` using FTS5 `MATCH` with
  `bm25()` ranking and `snippet()`; parameters bound, query string treated as untrusted (§10).
  **`FtsHit` fields + rowid contract (NIT-5):** `FtsHit` is a Pydantic model with
  `region_id: str`, `job_id: str`, `snippet: str`, `score: float`. `search` selects these directly
  from `region_fts` — the `region_id`/`job_id` UNINDEXED columns plus `snippet(region_fts, 0, …)`
  and `bm25(region_fts)` — and **never exposes the implicit FTS `rowid`** nor joins back on it.
  (`region.id` is a `TEXT` PK, so `region.rowid` is a separate implicit integer the triggers key the
  FTS table on; it stays an internal detail of the triggers and is never returned to a caller.)

All DAOs take `conn` and return typed dataclasses/Pydantic rows — **no untyped dict crosses a
module boundary** (coding-standards). The runner and routes call DAOs only.

### 4.4 Testability (4.1 done-check)

- **Migration tests (two, MEDIUM-2):** (1) *fresh DB* — open a fresh temp DB → `init_db` → assert
  `user_version==2` and that **both** v1 tables (`model`, `setting`) and v2 tables
  (`job`/`page`/`region`/`formula_candidate`/`correction`/`region_fts`) exist. (2) *v1-seeded
  preservation* — open a DB pre-seeded at `user_version=1` with a `MODEL` row → `migrate` → assert
  the row survives verbatim and the v2 tables appear (proves the step is additive and
  non-destructive).
- **FTS test:** insert pages+regions with known `content`, run `fts_dao.search("integral")`, assert
  the expected `region_id`/`job_id` rows come back ranked. Unit-level, no models needed.

---

## 5. Failure isolation (4.5) — `jobs/guard.py`, `R-JOB-6`, `R-SEC-3`

Two layers, both already partly present and extended here:

1. **Per-region timeout (existing):** `assemble_page` already runs each region under
   `settings.region_timeout_s` via its internal executor; a slow region is marked `failed` and the
   page continues. Unchanged.
2. **Per-page wall-clock timeout + resource guard (new):** the runner wraps the whole
   `assemble_page` call in `asyncio.wait_for(run_in_executor(...), timeout=job_page_timeout_s)`. On
   `asyncio.TimeoutError` the page is marked `failed` with `error="page timeout"`. A hostile PDF
   page that hangs a region past its region timeout but somehow stalls assembly is still bounded by
   the page timeout. **Resource guard:** before rendering, the runner rejects pages whose rendered
   pixel area would exceed `max_snip_pixels` (reuse the existing decompression-bomb bound) and
   logs+fails that page; `Image.MAX_IMAGE_PIXELS` is already set globally in `app.py`.

   > **Note on cancelling a stuck thread.** A Python thread running `assemble_page` cannot be
   > force-killed; `wait_for` abandons the future and the runner moves on, so a truly wedged native
   > call could occupy a worker slot until it returns. This is bounded by `page_workers` and the
   > per-region timeout inside the assembler, and is the standard trade-off for in-process CPU work.
   > It is documented here rather than hidden. (The alternative — a subprocess per page — was
   > rejected in §1 for the model-duplication memory cost.)

**Failure never kills the job.** Any exception from a page is caught, logged with page context via
the shared rotating logger (`get_logger("jobs.runner")`), the page row is set `failed`, and the
loop continues (R-JOB-6). The job finishes `done` if every page is `done`, else `failed` **only if
it was aborted**; a job with some failed pages but all pages attempted finishes with
`status=done` and a non-zero `failed` count surfaced in progress (so "the job still completes" per
the 4.5 done-check, with honest per-page failure reporting).

**Retry-failed-only (R-JOB-6):** `POST /jobs/{id}/pages:retry-failed` calls
`pages_dao.reset_failed_to_pending(job_id)` (sets `failed → pending`, clears `error`, keeps
`attempts`) and re-enqueues the job. Only `failed` rows move; `done` rows are untouched, so no
completed page is re-run. The hostile-page fixture test (§13) proves: one poisoned page fails, the
other pages complete, and a subsequent retry re-attempts only the poisoned page.

---

## 6. Checkpoint / resume (4.3) — `R-JOB-2`, `DoD-2`

### 6.1 Enrollment

When a job is created, the runner computes the owned page index set from the job options
(full document, a `page_start..page_end` range, or an explicit `pages: [..]` list) and calls
`pages_dao.bulk_insert_pending(job_id, indices)` in **one transaction**. For a PDF, `total_pages`
and the index universe come from `len(pdf)`; for images, from the frame count.

**Enrollment runs exactly once, at job create (NIT-F6).** `bulk_insert_pending` is called a single
time for a fresh `uuid4` job id, so a `UNIQUE(job_id, page_index)` collision is impossible by
construction. **`recover_on_boot` NEVER re-enrolls** — it only reverts leased rows
(the unconditional boot-revert `revert_all_leased_for_active_jobs`, §4.3/§6.2) and re-enqueues the
already-existing `page` rows for non-terminal jobs; it inserts nothing. Likewise retry-failed (§5) flips existing `failed` rows back to `pending` and does
not insert. Consequently the §15 `bulk_insert_pending`-collision → 500 mapping is purely an
invariant-violation backstop (it can only fire on a code bug that re-runs enrollment), logged ERROR
with the colliding `(job_id, page_index)`. **Two cheap opens by
design (NIT-3):** enrollment opens the source once to count pages/frames, then the producer (§3.1)
opens it again to stream-render — this is intentional and cheap (a `len()`/frame-count open does not
decode page bitmaps). So the `page` rows are the authoritative work list — the range/list is
materialized once,
and the lease loop simply drains `pending` rows in `page_index` order. This makes range/list
support fall out of enrollment with no special-casing in the hot loop (R-JOB-3).

### 6.2 Resume algorithm

On engine **boot** (`app.py` startup) and on every **job start/resume**:

1. **On boot only**, `recover_on_boot` calls `pages_dao.revert_all_leased_for_active_jobs()` — the
   **unconditional** boot-revert (§4.3): every `leased` row of a non-terminal job reverts to
   `pending` **regardless of `lease_expires_at`**, so a page left `leased` by the killed process is
   reclaimable **immediately**, not after its TTL elapses. This is what makes the immediate-resume
   path deterministic: a test that kills the runner and re-boots at once finds those pages already
   `pending` (their TTL would still be in the future, so a TTL-only revert would leave them `leased`
   and the resume would stall until the TTL passed). **Precondition (NIT-2):** this unconditional
   revert is safe *only because exactly one engine process exists* (the single-user loopback model —
   tech.md / product.md): a freshly started process owns no outstanding leases, and no other live
   process can hold a valid lease at boot, so reverting every `leased` row cannot steal a lease from
   a concurrent worker. (The periodic **sweeper**, below, uses the *other* method,
   `revert_expired_leases(now)`, which is TTL-gated — it is the only one that may run while pages are
   legitimately in flight, and the `page_timeout_s < lease_ttl_s` invariant guarantees it only ever
   reclaims a crashed lease.)
2. For each job with `status in (running, paused, queued)`, re-enqueue it (paused stays paused).
3. The lease loop resumes draining `pending` rows. `done` pages are skipped (never re-leased, never
   re-rendered). For PDFs this is exact: the producer computes the owned (`pending`) index set from
   `pages_dao` and calls `render_pdf_page(pdf, index, cfg)` only for those indices — a `done` page's
   bitmap is never produced (MEDIUM-F1). For images, `iter_image_pages` is sequential, so frames
   before the first owned index are decoded-and-skipped (one in-flight frame, closed immediately);
   the recognition cost — the expensive part — is still paid only for owned frames.

Because leasing is atomic and `done` is terminal, resume yields **no lost pages** (every non-`done`
page is still `pending` and will be leased) and **no duplicate pages** (a `done` page is never
re-leased, and export is idempotent per §7). This satisfies `DoD-2`.

A background **sweeper** (an `asyncio` task on the engine loop, interval `job_lease_sweep_s`,
MEDIUM-3) calls `revert_expired_leases(now)` so a lease left behind by a crash is reclaimed after
its TTL.

**No lease renewal — the timeout/TTL ordering makes it unnecessary (HIGH-3).** The v1 draft said
"workers renew their lease," but in the §3.1 loop the worker *thread* is blocked inside native
`assemble_page` and touches no SQLite, and nothing on the loop was specified to re-stamp the lease —
so a legitimately slow page could be reverted to `pending` by the sweeper and re-leased by a second
worker, a **duplicate-processing** path that would violate DoD-2. The chosen fix removes renewal
entirely and relies on the enforced invariant **`job_page_timeout_s < job_lease_ttl_s`** (the §3.4
Pydantic cross-field validator, default 120 s < 300 s): the per-page wall-clock timeout (§5)
force-fails a page strictly *before* its lease could expire, so a live in-flight page can never
outlive its lease. Consequently the sweeper (and the boot revert) only ever reclaim leases from a
**crashed** process — never from a running page — and a second worker can never lease a page that is
still being processed. Token-guarded terminal writes remain the backstop: `mark_done`/`mark_failed`
carry `WHERE id AND lease_token=:tok`, so even a hypothetically reverted-then-reacquired row cannot
be double-committed by a stale owner (the `WHERE lease_token` clause fails → no-op). The ordering
constraint `page_timeout_s < lease_ttl_s` is the single invariant this depends on, and it is
enforced at config-load time, not left to operator discipline. A unit test asserts that a page which
runs right up to `job_page_timeout_s` is marked `failed` (not reverted) and is never leased by a
second worker while in flight.

### 6.3 Graceful shutdown

`design.md §1.1` requires in-flight pages checkpoint before exit. On app shutdown
(`FastAPI` shutdown event / Tauri stop), `JobManager.shutdown()` signals cancel to all job tasks,
`await`s the current in-flight pages to reach `done`/`failed` (bounded by `job_page_timeout_s`),
and stops the executor. Pages still `leased` at a hard kill are handled by §6.2 on next boot.

---

## 7. Idempotent per-page export (4.3) — `jobs/output.py`

### 7.1 The fragment model: body-only per page, single document wrap at concat (HIGH-1)

The v1 draft claimed the runner "calls the same per-page/per-document exporters" and concatenates
per-page `.tex` fragments. **Both are wrong against the source** (verified): the export leaf modules
expose only `document_to_markdown(doc, opts)` / `document_to_latex(doc, opts)` — whole-document
functions; `_render_page` is private. And `document_to_latex` wraps the body **once** with
`preamble_for(opts.preamble)` + `\begin{document}` ... `\end{document}`, so concatenating N per-page
`.tex` fragments would yield a file with no (or N duplicated) preambles and **would not compile**.
`document_to_markdown` likewise owns the `"\n\n"` block join and the single trailing-newline rule.

M4 fixes this with an explicit **body-fragment + single-wrap-at-concat** model:

1. **Add two thin public per-page body emitters** (additive, wrapping the existing private
   `_render_page`), returning the page's body **with no document wrapper and no trailing-newline
   normalization**:
   ```python
   # export/markdown.py
   def render_page_markdown(page: PageResult, opts: MarkdownOptions | None = None) -> str:
       """Join one page's blocks with '\n\n' (no leading/trailing newline rule) — a body fragment."""
       options = opts or MarkdownOptions()
       blocks = _render_page(page, options)
       return "\n\n".join(b for b in blocks if b != "")

   # export/latex.py
   def render_page_latex_body(page: PageResult, opts: LatexOptions | None = None) -> str:
       """Join one page's blocks with '\n\n' — body ONLY, no preamble/document environment."""
       options = opts or LatexOptions()
       blocks = _render_page(page, options)
       return "\n\n".join(b for b in blocks if b != "")
   ```
2. **Store the body fragment per page.** Each completed page writes its `md`/`tex` body fragment
   (and its JSON `result_json`) via the idempotent writer (§7.2). Fragments are body-only text.
3. **Single wrap at concat (export time).** `GET /jobs/{id}/export?format=…` joins the committed
   fragments in `page_index` order and applies the exporter's own document rule exactly once, so the
   result is byte-identical to the whole-document exporter run over **the set of pages whose
   fragments are committed** (see the mid-job + failed-page contract in §7.3 — the
   golden-equivalence invariant is stated precisely there):
   - **md:** `body = "\n\n".join(f for f in fragments if f != ""); return body + "\n" if body else "\n"`
     — matches `document_to_markdown`'s join + trailing-newline rule. **The empty-fragment filter
     (`if f != ""`) is required (MEDIUM-1):** `document_to_markdown` builds one *flat* block list
     across all pages and joins `b for b in blocks if b != ""`, so an empty block never contributes
     a separator. A **committed** page can legitimately render to an empty body (a blank page, or a
     page whose only regions all render to `""`); its fragment is `""`. Without the filter the
     per-page concat would keep that empty fragment and emit a stray `"\n\n"`, diverging from the
     whole-document exporter by two bytes. Filtering empty fragments at concat makes the per-page
     concat byte-identical to the flat-list filter the exporter already does. (Non-`done` pages are a
     distinct case — they emit an honest placeholder per §7.3(b), which is non-empty and is kept.)
   - **tex:** `preamble_for(opts.preamble).rstrip("\n")` + `""` + `\begin{document}` + `""` +
     (`"\n\n".join(f for f in fragments if f != "")`, then `""`) + `\end{document}`, joined by
     `"\n"`, plus a trailing `"\n"` — the *exact* assembly `document_to_latex` performs (verified
     against its `parts` list). **The fragment body join uses `"\n\n"` (a blank line between
     fragments), NOT `"\n"`:** `document_to_latex` computes `body = "\n\n".join(b for b in blocks if
     b != "")` over the *flat* block list spanning every page, and each per-page fragment is itself
     `"\n\n".join(blocks)`; so to be byte-identical the fragments must rejoin with the same `"\n\n"`
     separator the exporter uses between blocks (joining with a single `"\n"` would drop one byte at
     every page boundary and fail the golden). The body join applies the **same empty-fragment
     filter** as md, for the same reason: a committed page rendering zero blocks must not inject a
     blank body line that the whole-document exporter would never produce. The assembled `parts`
     list is then joined with `"\n"` exactly as `document_to_latex` does — i.e. `"\n".join([preamble,
     "", r"\begin{document}", "", <body>, "", r"\end{document}"]) + "\n"` when the body is non-empty,
     dropping the `<body>`+`""` entries when every fragment is empty.
   - **json:** anchored to an explicit **reference JSON exporter with a documented fidelity
     contract (MEDIUM-3).** Because `export/` has **no** JSON module today (only `latex.py`,
     `markdown.py`, `mathml.py`, `templates.py`), M4 **adds `export/json_export.py`** with one
     public whole-document function:
     ```python
     # export/json_export.py  (new, additive — the reference the concat is proven against)
     def document_to_json(doc: DocumentResult, opts: JsonOptions | None = None) -> str:
         """Serialize the FULL DocumentResult (Pydantic v2) losslessly.
            Returns doc.model_dump_json(indent=opts.indent) — the complete PageResult per page,
            not a compact summary."""
     ```
     **Fidelity contract (pinned):** the JSON export is the serialized `DocumentResult`
     `{"source_name": str, "pages": [<full PageResult>, ...]}` where **each committed page's object
     is the complete `PageResult`** (every region's content/latex/mathml, confidences, bboxes,
     reading order, `rollup_status`) — the SAME structure stored in `page.result_json` (which is
     `PageResult.model_dump_json()`, §4.2). It is **not** an ambiguous compact summary.

     Two shapes, one serializer:
     - **Complete-document / committed-only (the golden anchor).** When every page in the requested
       set is committed, the concat path reconstructs `DocumentResult(source_name=job.source_name,
       pages=[...])` by `model_validate`-ing each committed page's stored `result_json` back into a
       `PageResult` (in `page_index` order) and returns `document_to_json(doc)`. The golden test
       asserts this is byte-identical to running `document_to_json` over the same `DocumentResult`
       built directly from the in-memory `PageResult`s — exactly mirroring the md/tex anchor.
     - **Mid-job / with non-committed pages.** A `pending`/`leased`/`failed` page has no
       `PageResult`, so it cannot be a `PageResult` in `doc.pages`. The export then emits a
       top-level object `{"source_name": job.source_name, "pages": [...]}` whose `pages` array
       carries, in `page_index` order, each committed page's full serialized `PageResult` **and**,
       for each non-committed index, the §7.3(b) placeholder object
       `{"index": N, "status": "failed|pending|leased", "error": <str|null>}` at its ordinal
       position — never a silent gap (honesty invariant). The placeholder objects are
       distinguishable from a real `PageResult` by their `status`/`index` keys. This mid-job shape
       is not run through `document_to_json`'s typed `DocumentResult` (placeholders are not valid
       `PageResult`s); it is assembled by the concat builder and serialized with the same JSON
       settings (indent/ordering), so the committed-only subset of its `pages` is byte-identical to
       the committed-only `document_to_json` output.
4. **Golden-equivalence test (HIGH-1 + MEDIUM-3 done-check).** For a small multi-page fixture,
   assert that the fragment-concat output for `md`, `tex`, **and `json`** is **byte-identical** to
   `document_to_markdown(doc)` / `document_to_latex(doc)` / `document_to_json(doc)` over the same
   `DocumentResult`, and that the json output round-trips back to a `DocumentResult`
   (`DocumentResult.model_validate_json(out)` succeeds and equals `doc`). Without
   this assertion the "reuse the M3 exporters" claim is unproven; with it, the reuse is exact. **The
   fixture MUST include a committed page that renders to an empty body (zero renderable blocks)**, so
   the test exercises the empty-fragment filter above (MEDIUM-1) and would fail if the concat kept a
   stray `"\n\n"`/blank body line that the whole-document exporter drops.

This keeps recognition and rendering logic entirely in the M3 leaf modules (the emitters are thin
`_render_page` wrappers) while making the per-page seam real and the `.tex` output compilable.

### 7.2 Idempotent per-page writes (temp + atomic rename)

Each page writes its export artifacts **atomically and idempotently** so a resumed/re-run page can
never duplicate or corrupt output (R-JOB-2, R-JOB-5 incremental output):

- **Per-page files (temp + atomic rename).** For the per-page artifacts (JSON page dump, the
  `md`/`tex` **body fragments** from §7.1, figure PNGs via the assembler's existing `asset_dir`),
  the writer writes to `output/<job_id>/pages/<index>.<ext>.tmp` then `os.replace()` to the final
  name.
  `os.replace` is atomic on Windows and POSIX; a crash mid-write leaves only a `.tmp` (ignored on
  resume and overwritten). Writing the final name is the page's commit point **and it happens
  before `mark_done`**, so a page marked `done` always has its artifact on disk; a page whose
  artifact write failed is marked `failed`, never `done`.
- **Idempotency.** The final filename is deterministic from `(job_id, page_index, format)`. Re-
  running a page (e.g. retry-failed) overwrites the same temp→final path — no append, no duplicate.
- **Incremental document assembly (R-JOB-5).** The headline PDF→Markdown output is a single
  document file. To stream it incrementally **without** racing, the design uses a
  **manifest-of-fragments** model: each page commits its fragment file; a monotonic
  `output/<job_id>/manifest.json` (written temp+rename) records which page fragments are complete;
  a `GET /jobs/{id}/export?format=md|tex|json` endpoint **concatenates the committed body fragments
  (§7.1) in page order on demand** with the single document wrap applied exactly once (and can be
  called repeatedly as pages land — results appear as they complete). The final single-file export
  is produced by the same concatenation at job completion. This avoids
  in-place patching of a shared file from multiple workers (which would need a writer lock and
  violate the one-writer discipline at the data level). Concatenation order is page index, so
  out-of-order completion still yields correct document order.

**Why fragments + on-demand concat rather than live in-place patching?** In-place patching of one
growing `.md` from concurrent page workers needs byte-offset bookkeeping + a file lock and is
fragile under crash/resume. Fragment files are each independently atomic, trivially idempotent, and
compose deterministically. The cost is a concat pass on export, which is cheap (I/O-bound, linear)
and happens off the hot path. Chosen for crash-safety and the one-writer constraint.

### 7.3 Export response contract: mid-job, failed pages, response type (MEDIUM-F3)

`GET /jobs/{id}/export?format=md|tex|json` is callable at any time — mid-job or after completion —
so three behaviors are pinned explicitly:

- **(a) Mid-job = partial over the committed set.** When the job is not yet complete, export
  returns the document assembled over **exactly the pages whose fragments are committed on disk**
  (every page the manifest marks complete). It never blocks and never errors merely because pages
  are still `pending`/`leased`. The **golden-equivalence invariant is therefore stated precisely**
  (HIGH-1 + MEDIUM-F3): the concat output is byte-identical to the whole-document exporter
  (`document_to_markdown` / `document_to_latex`) run over **the `DocumentResult` consisting of just
  the committed page set, in `page_index` order**. The complete-document guarantee is the special
  case where every page is committed. The golden test asserts both: a full-set case and a
  committed-subset case.

- **(b) Non-`done` pages emit an honest placeholder in page order — never a silent gap.** A page
  that is `failed` (or still `pending`/`leased` during a mid-job export) has **no body fragment**
  (the fragment is written *before* `mark_done`, and a non-`done` page is never `mark_done`).
  Silently skipping it would drop a numbered page from the document — silent data loss, which
  violates the honesty steering ("a region that can't be recognized is marked `needs_review`/
  `failed`, never ... shown as confident"; the same principle forbids a vanished page). So
  concatenation walks the **full enrolled index range** and, for each non-committed index, emits a
  format-appropriate placeholder **in page order**:
  - **md:** `<!-- texora: page {index} {status} (no output){: error} -->`
  - **tex:** `% texora: page {index} {status} (no output){: error}` (a LaTeX comment line, so the
    document still compiles)
  - **json:** an object `{"index": N, "status": "failed|pending|leased", "error": <str|null>}` in the
    `pages` array at its ordinal position
  The placeholder carries the page `status`/`rollup_status` and `error` so the gap is visible and
  auditable, not guessed content. A `done` page with `rollup_status='needs_review'` emits its real
  fragment (it has committed content) — review-flagging is surfaced via `rollup_status` in the
  JSON/metadata, not by suppressing the body.

- **(c) Response type = `StreamingResponse` fed by a generator.** A 10,000-page export must not
  build the whole string in memory (that would defeat the constant-memory theme at the export
  boundary). The route returns a Starlette `StreamingResponse` whose generator yields, in
  `page_index` order: the format's opening wrap (md: nothing; tex: `preamble_for(...).rstrip("\n")`
  + `\n\begin{document}\n`), then each committed fragment or placeholder separated by the format's
  joiner (**`"\n\n"` for md *and* for the tex body** — the same blank-line separator
  `document_to_latex` puts between blocks; a single `"\n"` would drop one byte per page boundary and
  break byte-identity), then the closing wrap (md: the trailing-newline rule; tex: `\end{document}\n`
  preceded by the `"\n\n"` body/closing separator so the final bytes match the single-shot
  `parts` join). **To stay byte-identical to the single-shot concat, the generator
  applies the same empty-fragment filter (§7.1): an empty *committed* fragment (`""`, a page that
  rendered zero blocks) is skipped and contributes no joiner.** Non-committed pages are different —
  their §7.3(b) placeholder is non-empty and is always emitted in order, so a page is never silently
  dropped; only a genuinely blank committed page is filtered, exactly as the whole-document exporter
  filters an empty block. The generator reads one fragment file at a time, so peak memory is one
  fragment, not the whole document. The byte sequence the generator produces is defined to equal the
  single-shot concat of §7.1 (the golden test runs against the fully-materialized concat of the
  generator's output, so streaming and non-streaming agree byte-for-byte). `Content-Type` is `text/markdown`,
  `application/x-tex`, or `application/json` accordingly; a `Content-Disposition` attachment
  filename is derived from `job.source_name`.

---

## 8. Batch + watch folder (4.6) — `jobs/watch.py`, `R-JOB-7`

- **Batch intake:** `POST /jobs/batch` accepts `{paths: [file-or-dir, ...], options}`. Directories
  are expanded (non-recursive by default; `recursive: true` opt-in) to supported extensions
  (`_PDF_EXTS ∪ _IMAGE_EXTS`, reused from `api/pages.py`). Each resolved file becomes its own `JOB`
  row enqueued at the given priority. Path sanitization reuses `api/pages._validate_path` (no `..`,
  must exist, must be a supported regular file) — factored into a shared `jobs/paths.py` helper so
  both routes use one validator (§10).
- **Watch folder:** when `settings.watch_dir` is set, `app.py` starts a `watchdog` `Observer` on
  that directory at startup. A new/renamed file event triggers a **settle check**: the watcher
  waits `watch_settle_s`, confirms the file size is stable (a still-copying file is skipped until
  stable), validates the extension + path, and enqueues a job. A per-path debounce + an in-memory
  "already enqueued" set (keyed by resolved path + mtime) prevents duplicate jobs from the
  multiple events an OS emits for one file write. The watcher runs on the `Observer`'s own thread
  and submits enqueue requests onto the asyncio loop via `loop.call_soon_threadsafe` so all job
  creation goes through the single `JobManager` (no second writer).
- **Done-check (4.6):** a unit/integration test drops a fixture PDF into a temp watch dir and
  asserts a `JOB` row appears `queued`; a second test enqueues a folder of two PDFs via
  `POST /jobs/batch` and asserts two jobs. No live FS race needed for the test (the settle wrapper
  is deterministic given a fully-written fixture).

---

## 9. Job control API + progress WebSocket (4.4) — `api/jobs.py`, `R-JOB-3/5`

### 9.1 REST routes (all on a `jobs_router` with `Depends(require_token)`)

| Method + path | Body / query | Returns | Req |
|---|---|---|---|
| `POST /jobs` | `JobCreateRequest` (path, options, range/list, priority) | `JobView` | R-JOB-3 |
| `POST /jobs/batch` | `BatchCreateRequest` (paths[], options) | `list[JobView]` | R-JOB-7 |
| `GET /jobs` | `?status=&limit=&offset=` | `JobListView` | R-UI-6 |
| `GET /jobs/{id}` | — | `JobView` (incl. `JobProgress`) | R-JOB-5 |
| `POST /jobs/{id}:pause` | — | `JobView` | R-JOB-3 |
| `POST /jobs/{id}:resume` | — | `JobView` | R-JOB-3 |
| `POST /jobs/{id}:cancel` | — | `JobView` | R-JOB-3 |
| `POST /jobs/{id}:reprioritize` | `{priority:int}` | `JobView` | R-JOB-3 |
| `POST /jobs/{id}/pages:retry-failed` | — | `JobView` | R-JOB-6 |
| `GET /jobs/{id}/export?format=` | `format in {md,tex,json}` | `StreamingResponse` (committed-set partial allowed mid-job; non-`done` pages → honest placeholders in order; §7.3) | R-JOB-5 |
| `GET /search?q=&limit=&offset=` | FTS query | `list[FtsHit]` | R-UI-1 |
| `WS /jobs/{id}/events` | — (token in first message, §9.2) | progress events | R-JOB-5 |

All request/response bodies are **Pydantic v2 models** (`JobCreateRequest`, `JobView`,
`JobProgress`, `BatchCreateRequest`, `FtsHit`, `ProgressEvent`). Control actions mutate state via
the `JobManager` (pause sets the pause gate; cancel sets the cancel flag + marks `canceled`;
reprioritize updates `job.priority` and the manager re-orders its queued set). Error mapping mirrors
`api/pages.py`: bad path/range/format → 422; unknown job id → 404; action invalid for current state
(e.g. resume a `done` job) → 409.

### 9.2 WebSocket auth (R-SEC-2: token on every non-health route, incl. the WS) — explicit accept/close ordering (MEDIUM-4)

FastAPI/Starlette WS connections can't use the HTTP `Depends(require_token)` cleanly, and a
WebSocket must be `accept()`-ed before the server can read a client text frame — which the v1
"close `4401` before any data" phrasing glossed over. The handler validates against
`app.state.engine_token` with the same `secrets.compare_digest` as `security.require_token`, and the
two paths have **distinct, explicit sequences**:

- **Header path (the normal one, used by the Rust bridge §9.3).** Starlette exposes request headers
  on the WS handshake. If an `Authorization: Bearer <token>` header is present, validate it
  **before** `accept()`:
  - match → `await ws.accept()` and begin streaming events;
  - mismatch/malformed → `await ws.close(code=4401)` **without** `accept()` (no data is ever sent).
- **Fallback path (bare clients / tests that cannot set handshake headers).** When no
  `Authorization` header is present:
  - `await ws.accept()` (required before any frame can be read);
  - `await asyncio.wait_for(ws.receive_text(), timeout=ws_token_timeout_s)` — read **exactly one**
    frame `{"token": "..."}`;
  - validate with `compare_digest`; on **mismatch or timeout**, `await ws.close(code=4401)` and
    send nothing further;
  - on match, begin streaming events.

`ws_token_timeout_s` (default 5 s, §3.4) bounds the fallback wait so a client that accepts but never
sends a token cannot hold the socket open. **`4401`** is the chosen application close code
(application codes live in the 4000–4999 range; the reserved 1000-range is not used). A unit test
exercises both paths: header-mismatch closes 4401 pre-accept; fallback timeout closes 4401; a valid
token (either path) receives a `ProgressEvent`.

### 9.3 Progress delivery to the UI — Rust event bridge (reuses the model-download pattern)

**Critical architectural constraint:** the webview never learns the engine port or token (they stay
in Rust; see `supervisor.rs`), and `engineClient.ts` makes **no `fetch`** and opens **no
WebSocket** directly. The established M2 pattern for streaming progress is: **Rust talks to the
engine and re-emits Tauri events** (`start_model_poll` → `engine://model-progress`). M4 follows
the same pattern for jobs:

- The engine exposes `WS /jobs/{id}/events` emitting `ProgressEvent` JSON
  (`{jobId, pageIndex, pageStatus, done, failed, total, pagesPerMin, etaSeconds}`) on each page
  completion and on state changes (paused/resumed/canceled/finished).
- **Rust `start_job_events(app, id)`** (in `supervisor.rs`). This reuses the **proven Rust→webview
  Tauri-event re-emit pattern** (the half that `start_model_poll` → `engine://model-progress`
  already establishes) but introduces a **new transport**: where the model-progress path is a
  `ureq` HTTP 500 ms **poller**, the job-events path is a **sync WebSocket read loop** using a new
  `tungstenite` client (NIT-F5 — `src-tauri`'s `Cargo.toml` has `ureq` only today; `tungstenite`
  0.23 is a new dependency, handled in §1's table + the LICENSES-same-change rule). Concretely:
  `start_job_events` spawns a **new blocking read thread** that opens an authenticated WS to the
  engine (bearer token on the handshake), then loops reading frames and re-emitting each as a Tauri
  `engine://job-progress` event. **Thread lifecycle:** the thread is spawned on `job_subscribe` and
  stops (joins/returns) when the job reaches a terminal state (`done|failed|canceled`) **or** the
  socket closes/errors — so the Rust work is a real new client + thread, not merely a config tweak
  to the existing poller.
- A new `#[tauri::command] job_subscribe(id)` (in `lib.rs`) starts that bridge; the job control
  commands (`job_create`, `job_pause`, `job_resume`, `job_cancel`, `job_reprioritize`,
  `job_retry_failed`, `job_list`, `job_get`, `job_search`) are thin `engine_request` proxies
  exactly like `recognize_snip`.
- `engineClient.ts` gains typed `createJob/listJobs/getJob/pauseJob/.../searchContent` functions
  (invoke proxies) and `subscribeJobProgress(cb)` (listens to `engine://job-progress`), mirroring
  `subscribeModelProgress`. **Components never call invoke/listen directly** — only the client does.

> **Decision — WS at the engine, Tauri-event bridge to the webview, not a direct webview WS.**
> A direct webview→engine WebSocket would require leaking the port+token into JS, breaking the
> security model (`R-SEC-2`) that `supervisor.rs` is built around. Re-emitting through Rust keeps
> the token in Rust, **reuses the proven Rust→webview Tauri-event re-emit pattern** (not the
> transport — the transport is a **new** `tungstenite` sync WebSocket read loop replacing the
> `ureq` HTTP poller, NIT-F5), and keeps the typed client the single integration seam. The engine
> still speaks a real WS (not polling) so the 4.4
> done-check "WS emits progress" is met at the engine boundary and unit-tested there; the webview
> receives the same stream via the bridge. (Polling the engine from Rust was the fallback, but a WS
> gives lower-latency per-page events for the live queue view — chosen.)

---

## 10. Input validation & security (R-SEC-3)

| Input | Rule | On failure |
|---|---|---|
| Job `path` / batch `paths` | reject `..`; `resolve(strict=True)`; must be a regular file (or dir for batch); extension in `_PDF_EXTS ∪ _IMAGE_EXTS` | 422 (shared `jobs/paths.py`, factored from `api/pages._validate_path`) |
| `page_start`/`page_end`/`pages[]` | ints ≥ 0; `start ≤ end`; indices within `total_pages` (out-of-range indices dropped with a logged note, not an error) | 422 on malformed; silent drop of OOB indices |
| `priority` | int, clamped to `[-100, 100]` | clamp (no error) |
| export `format` | enum `{md, tex, json}` | 422 |
| FTS `q` | non-empty, length-bounded (≤ 256 chars); passed as a **bound parameter** to FTS5 `MATCH`; no SQL built by string interpolation | 422 on empty/oversize |
| WS token | `secrets.compare_digest` vs `app.state.engine_token`; header path validates pre-`accept()`, fallback path reads one frame under `ws_token_timeout_s` post-`accept()` (§9.2) | close `4401` (no data sent) |
| watch-folder file | settle (stable size) + extension + path validation before enqueue | skip (logged), never crash the watcher |

Resource guards: `job_max_concurrent_pages` caps memory; `job_page_timeout_s` + the existing
`region_timeout_s` cap per-page/-region time; the pixel-area bound rejects decompression-bomb
pages. A hostile document is isolated to a failed page, never the job (R-JOB-6/R-SEC-3). All SQLite
access is parameterized inside DAOs; **no raw SQL in routes or the runner.**

---

## 11. Engine startup/shutdown wiring (`app.py`)

- On startup: `init_db` (now migrates to v2); build `JobManager(conn, deps_provider, settings)`;
  store on `app.state.job_manager`; call `job_manager.recover_on_boot()` (revert leases, re-enqueue
  non-terminal jobs — §6.2); if `settings.watch_dir`, start the `watchdog` observer; mount
  `jobs_router`.
- On shutdown (FastAPI `shutdown` event): `await job_manager.shutdown()` (graceful checkpoint, §6.3)
  and stop the observer.
- **Shared deps provider (MEDIUM-F4).** The `PipelineDeps` are built lazily (first job or first sync
  request) and cached on `app.state.pipeline_deps`, via a single `Request`-free helper:

  ```python
  # pipeline/deps.py  (new, additive)
  def get_or_build_deps(app_state) -> PipelineDeps:
      """Return the cached PipelineDeps or build+cache it on app_state.pipeline_deps.

      Takes Starlette app.state (NOT a FastAPI Request), reads app_state.{settings, model_store},
      builds layout/text/formula engines + loads pipeline_config, caches on
      app_state.pipeline_deps. Raises the SAME typed errors the route already maps:
      ModelNotReady / TesseractUnavailable / {Unknown*Engine, *StageNotConfigured}.
      """
      cached = getattr(app_state, "pipeline_deps", None)   # tolerate a missing attr (NIT-4)
      if cached is not None:
          return cached
      deps = _build_deps(app_state.settings, app_state.model_store)   # may raise the typed errors
      setattr(app_state, "pipeline_deps", deps)
      return deps
  ```

  **Read via `getattr(..., None)`, cache via `setattr` (NIT-4).** `create_app` sets
  `app.state.pipeline_deps = None` at startup (verified), so the production path never hits a
  missing attribute; but the runner and the §13 unit test call `get_or_build_deps` with an
  `app_state` that did **not** run `create_app`. Reading `app_state.pipeline_deps` directly would
  raise `AttributeError` there instead of returning `None`, so the helper uses
  `getattr(app_state, "pipeline_deps", None)` and writes back with `setattr`. The §13 unit test must
  seed `settings` and `model_store` on its stub `app_state` (those two are read, not defaulted).

  `api/pages._get_deps(request)` becomes a thin wrapper: `return get_or_build_deps(request.app.state)`
  (and keeps its existing `except → HTTP 409/500` mapping, unchanged). The runner calls
  `get_or_build_deps(app.state)` directly. Both share **one** cached deps instance — one set of
  loaded models, constant memory.

- **Job-start deps failure is a graceful job failure, never a crashed background task (MEDIUM-F4).**
  A job whose first `get_or_build_deps(app.state)` raises (`ModelNotReady` — weights absent;
  `TesseractUnavailable`; or a factory misconfig error) must fail the **job**, not raise an
  unhandled exception in the asyncio task. `_run_job` calls `get_or_build_deps` inside its top-level
  guard: on any of those typed errors the job is set `status=failed` with
  `error="models not ready: <detail>"` (or `"pipeline misconfiguration: <detail>"`), **no PAGE rows
  are leased** (the failure is pre-page), the WS emits a terminal failure `ProgressEvent`, and the
  error is logged ERROR with the job id. The §15 table has the explicit row.

---

## 12. The 5,000-page proof (4.7) — `scripts/make_synthetic_pdf.py`, `benchmarks/job_proof/`

- **Synthetic generator** (`scripts/make_synthetic_pdf.py`, `reportlab`): emits an N-page PDF with
  mixed text + simple math-like content per page, deterministic given a seed. CLI:
  `python -m scripts.make_synthetic_pdf --pages N --out path.pdf`. Also emits a **"hostile" variant**
  (one page with a pathological oversize image / degenerate content) for the §13 isolation test.
- **Memory-flat assertion:** a pytest (`benchmarks/job_proof/test_memory_flat.py`, `psutil`) runs a
  job over a scaled synthetic PDF, samples RSS every K pages, and asserts the slope of RSS vs. pages
  processed is below a threshold (flat within noise) and peak RSS stays under a bound — proving
  constant memory (R-JOB-1). It runs with a **fast stub `FormulaRecognizer`/`TextRecognizer`** *in
  the test harness only* (the production path stays real, honesty intact) so memory behavior of the
  **runner/streaming** is measured without model load noise; a second `@pytest.mark.model` variant
  uses the real engines.
- **Resume correctness assertion:** `test_interrupt_resume.py` starts a job, kills the runner task
  mid-way (simulating crash: cancel the task + drop the manager without graceful shutdown so some
  pages stay `leased`), reopens the DB, runs `recover_on_boot`, resumes, and asserts the final set
  of `done` pages == the full index set with **no duplicates** (each page processed exactly once,
  checked via a per-page processing counter in the stub) — this is `DoD-2` at test scale.
- **Scaling honesty (explicit):** on *this* host the memory + resume invariants are proven on a
  **scaled** synthetic PDF (e.g. 200–500 pages — enough to see the RSS slope and a mid-job kill),
  fast enough for local CI. The **full 5,000-page run** is wired as a **CI nightly** job
  (`.github/workflows` nightly matrix) that generates the 5,000-page PDF and runs the same
  assertions at full count. `docs/m4-verification.md` records this split verbatim: *invariants
  proven locally at scaled count; full 5,000-page run is the nightly CI gate; never faked.* This is
  the honest DoD-1/2 story the steering demands.
- **Packaging/licensing done-check (4.7, NIT-4):** `reportlab` and `psutil` are declared under a
  `[test]`/dev extra (e.g. `project.optional-dependencies.test` in the engine `pyproject.toml`) so
  the PyInstaller spec — which freezes only the runtime dependency set — **never bundles them into
  the shipped sidecar**; a 4.7 done-check asserts the extra exists and that both packages appear in
  `docs/LICENSES.md` (added in the same change) marked *test/CI only, not shipped*. `anyio` is
  already a transitive runtime dependency of FastAPI/Starlette and needs **no new** LICENSES row.
  `watchdog` (shipped, Apache-2.0) and the Rust `tungstenite` (shipped, MIT/Apache-2.0) get runtime
  rows in the same change that introduces them.

---

## 13. Testing strategy (R-QA-3)

**Unit (pytest, no models):** migration v1→v2 — fresh-DB (`user_version==2`, v1+v2 tables) **and**
v1-seeded preservation (MEDIUM-2); FTS search (4.1); `pages_dao.lease_next` atomicity (two
concurrent lease attempts → distinct pages); `revert_expired_leases` reverts only expired;
`revert_all_leased_for_active_jobs` reverts **every** leased row of a non-terminal job even with a
future `lease_expires_at` and leaves terminal-job leases untouched (MEDIUM-2 boot-revert); the
timeout/TTL ordering test (a page running to `job_page_timeout_s` is `failed`, never reverted/
re-leased while in flight — HIGH-3); `reset_failed_to_pending` touches only failed; idempotent
writer (write twice → one file, same bytes); **fragment-concat golden-equivalence** over a **full**
page set, a **committed-subset** (mid-job) set, *and* a set containing a **committed page that
renders an empty body** (`md`/`tex`/`json` concat == whole-document exporter over that exact set,
byte-identical — HIGH-1 + MEDIUM-F3 + this round's MEDIUM-1 empty-fragment filter + MEDIUM-3 json
anchor); **json fidelity** — the json export is the full `DocumentResult`/`PageResult`
(`document_to_json`) and **round-trips** (`DocumentResult.model_validate_json(out) == doc`), with
`page.result_json` confirmed to store the complete `PageResult.model_dump_json()` (MEDIUM-3);
**export placeholder emission**
(a `failed`/`pending` page yields an in-order md/tex comment or json `{index,status,error}`, never
a dropped page — MEDIUM-F3); export `StreamingResponse` generator output equals the single-shot
concat byte-for-byte (MEDIUM-F3); `iter_image_pages` yields one frame at a time over a multi-frame
TIFF without materializing all frames (MEDIUM-1); **resume renders only owned PDF indices** — a
stub `render_pdf_page` counter asserts a resumed job never re-renders a `done` index (MEDIUM-F1);
`get_or_build_deps(app_state)` builds+caches once and raises the typed errors with no `Request`
(MEDIUM-F4); manifest concat order; path validator; FTS query binding; JobProgress ETA math.

**Integration (pytest, stub recognizers in-harness):** full small job end-to-end over a 5-page
synthetic PDF → all pages `done`, fragments on disk, concat matches expected; pause/resume/cancel
transitions; retry-failed re-runs only the failed page; **mid-job export** returns the committed
subset with an in-order placeholder for a not-yet-done page (MEDIUM-F3); **deps-build-at-job-start
failure** (`get_or_build_deps` raises `ModelNotReady`) → job `failed` with `error="models not
ready: …"`, no page leased, terminal WS event, task does not crash (MEDIUM-F4); hostile-page
fixture → that page `failed`, job `done` with `failed==1` (4.5); **immediate-resume determinism** —
simulate a crash mid-job (leave rows `leased` with a *future* `lease_expires_at`), reopen the DB,
run `recover_on_boot`, and assert those pages are `pending` **at once** (not waiting for TTL) and the
resumed job reaches `done` over the full set (MEDIUM-2); watch-folder drop → job enqueued
(4.6); WS auth both
paths (header-mismatch closes `4401` pre-accept; fallback timeout closes `4401`; valid token
receives a `ProgressEvent`) and WS emits a `ProgressEvent` per page (4.4, MEDIUM-4, tested with a
bare Starlette WS test client using the message-token fallback).

**Proof (CI):** §12 memory-flat + interrupt-resume; scaled locally, 5,000 nightly.

**Frontend (vitest):** `engineClient` job functions map snake→camel correctly and call the right
invoke command (mocked `invoke`); `subscribeJobProgress` parses `engine://job-progress` payloads;
the Batch/Queue component renders progress from a mocked client, shows per-page/overall status,
throughput, errors, and a retry-failed button, and all strings resolve via i18next `id`/`en`
(locale completeness test). **The interactive live window (real WS → live DOM updates) is
host-limited** → the client/WS wiring + component are proven with vitest and the running-window
confirmation is documented **PENDING** in `docs/m4-verification.md` (same honest pattern as M2's
hotkey/popup and M3's latex-compile).

**Rust (cargo test):** `start_job_events` terminal-state detection + event re-emit (one-shot stub
WS server, mirroring the existing `engine_request_reaches_stub_with_bearer` test); job proxy
commands build the right body/path.

---

## 14. Strictly-sequential build order (anti-race) — one writer, one chain

The milestone is implemented by **exactly one coder at a time**, so the design is a single linear
dependency chain with each step independently buildable + testable before the next:

```
4.1 db schema+migrations+DAOs+FTS         (foundation; no runtime deps)
  └─ 4.2 runner + manager + lease loop     (needs PAGE DAO; reuses assemble_page)
       └─ 4.3 checkpoint/resume + idempotent export writer   (needs runner + lease sm)
            └─ 4.5 failure isolation (page timeout + resource guard + retry-failed)
                 └─ 4.4 control API + WS   (exposes runner/manager over HTTP+WS)
                      └─ 4.6 batch + watch folder   (needs POST /jobs + manager enqueue)
                           └─ 4.7 5,000-page proof (synthetic gen + CI memory/resume)
                                └─ 4.8 Queue UI + incremental output + Rust bridge
```

(4.5 is pulled before 4.4 vs. the task file's numeric order because the control API's
`retry-failed` and the WS failure events are cleaner to expose once isolation exists; both depend
only on 4.2/4.3 and the chain stays linear. tasks.md lists `4.5 dep:4.2` and `4.4 dep:4.2`, so
either order is valid — this one minimizes rework.) No two tasks need concurrent writers; each
edits a distinct new file or extends an existing one additively, and the engine/UI build stays
green at every step.

**Build-green-standalone confirmation (NIT-1).** The two reordered steps have independent
done-checks and each leaves the engine build + `pytest` green on its own: 4.5 adds the per-page
timeout/resource guard and `reset_failed_to_pending` + its tests against the runner from 4.2/4.3
(no API surface needed); 4.4 then adds the REST/WS surface and its tests on top. Neither step
depends on the other's artifacts — 4.4's `retry-failed` route simply exposes the DAO call 4.5
already shipped and tested — so the ordering is a convenience, and reverting to numeric order would
also build green. Every step ends with `ruff`/`black --check`/`mypy`/`pytest` clean (and, for 4.8,
`pnpm --filter desktop lint/test/build`).

---

## 15. Error handling (concrete, per failing operation)

| Operation | Failure | Recoverable? | Caller receives | Logged |
|---|---|---|---|---|
| `migrate` v1→v2 | SQL error mid-step | fatal (startup aborts) | engine fails to start, supervisor surfaces unhealthy | ERROR + abort (transaction rolls back, DB stays v1) |
| `get_or_build_deps` at job start | `ModelNotReady` / `TesseractUnavailable` / factory misconfig | job-level (no page leased) | job → `failed`, `error="models not ready: …"` / `"pipeline misconfiguration: …"`; WS emits terminal failure; task never crashes (MEDIUM-F4) | ERROR w/ job id |
| `bulk_insert_pending` | duplicate `(job_id,index)` | invariant violation (impossible by construction) | job create 500 (backstop only — enrollment runs exactly once per fresh uuid4 job; `recover_on_boot` never re-enrolls, NIT-F6) | ERROR w/ colliding `(job_id,index)` |
| `lease_next` | no `pending` rows | not an error | producer stops leasing, job finalizes | DEBUG |
| render a page | `IngestError` (corrupt page) | page-local | page `failed`, job continues | WARNING w/ page ctx |
| `assemble_page` | exception / region timeout | page-local | page `failed` (R-JOB-6) | WARNING w/ page ctx |
| page wall-clock timeout | `asyncio.TimeoutError` | page-local | page `failed error="page timeout"` | WARNING |
| idempotent write | `OSError` (disk full) | page-local | page `failed` (not `done` — artifact absent) | ERROR |
| `mark_done` with stale token | lease stolen/expired | self-correcting | no-op (`WHERE lease_token` fails) → page stays for the new owner | DEBUG |
| control action wrong state | e.g. resume `done` | caller error | 409 | INFO |
| unknown job id | — | caller error | 404 | INFO |
| WS bad/missing token | — | caller error | close `4401` before data | WARNING |
| watch-folder enqueue | invalid/unstable file | skip | nothing enqueued | INFO (skipped: reason) |
| FTS query | malformed/oversize | caller error | 422 | INFO |

Invariants & ownership:
- **Exactly-once page processing** — owned by the DB layer (atomic `lease_next` + terminal `done` +
  token-guarded `mark_done`). Not the runner's job to enforce in Python.
- **Constant memory** — owned by the runner (semaphore + per-page `finally` close + lazy render).
- **No fabricated output** — owned by `assemble_page` (already), unchanged by M4.
- **Loopback + bearer on every non-health route incl. WS** — owned by `security.require_token` +
  the WS token check.

---

## 16. Requirement traceability

| Req / DoD | Where satisfied |
|---|---|
| R-JOB-1 (constant memory, 5,000 pages) | §3 runner (semaphore+lazy render), §12 proof |
| R-JOB-2 (checkpoint/resume, no lost/dup) | §3.2 lease sm, §6 resume, §7 idempotent export, §12 |
| R-JOB-3 (pause/resume/cancel/reprio, range/list) | §9 API, §6.1 enrollment |
| R-JOB-4 (bounded concurrency/worker pool) | §3.1, §3.4 settings |
| R-JOB-5 (per-page status, ETA, pages/min, incremental output) | §3.3, §7 fragments, §9 WS |
| R-JOB-6 (per-page failure, continue, retry-failed) | §5 isolation, §9 retry route |
| R-JOB-7 (batch + watch folder) | §8 |
| R-UI-1 (FTS library search) | §4.2 FTS5 + triggers, §4.3 `fts_dao`, §9 `/search` |
| R-UI-6 (Batch/Queue screen) | §9.3 client, §13 UI tests, §14 (4.8) |
| R-SEC-2 (loopback + token on every request, incl. WS) | §9.2 WS auth, §9.3 Rust bridge, §10 |
| R-SEC-3 (path sanitize, resource limits, per-page timeout, isolate hostile page) | §5, §10 |
| DoD-1 (1,000+ page end-to-end, no cap) | §3 streaming + §12 (5,000 superset) |
| DoD-2 (kill mid-job → resume correctly) | §6, §12 interrupt-resume test |

---

## 17. Key decisions (ADR summary for this milestone)

- **M4-ADR-1 — asyncio task runner + bounded thread pool, no multiprocessing/broker; all SQLite on
  the single loop.** Keeps one copy of the loaded models (constant memory), zero new infra. The
  runner, DAOs, and sweeper all touch `conn` only on the event loop; worker threads never do;
  the watchdog thread marshals via `call_soon_threadsafe` — so concurrent write transactions are
  impossible by construction (MEDIUM-3). **`job_page_workers` defaults to 1** because
  `assemble_page` enters the shared torch model and `region_concurrency` only serializes within a
  page; cross-page model parallelism is an M7 seam (HIGH-2). (§1, §3)
- **M4-ADR-2 — per-page SQLite lease state machine with TTL + token-guarded transitions, no
  renewal.** Atomic exactly-once leasing + crash-safe resume with no lost/dup pages. The enforced
  invariant `job_page_timeout_s < job_lease_ttl_s` (Pydantic cross-field validator) means a live
  page is force-failed before its lease could expire, so the sweeper only reclaims crashed leases
  and no renewal mechanism is needed (HIGH-3). (§3.2, §3.4, §6)
- **M4-ADR-3 — additive migration v1→v2, v1 SQL verbatim, gap-guarded, no fast-path.** `_MIGRATIONS`
  covers every key in `2..SCHEMA_VERSION`; the loop is a no-op at the current version; `_V1_SQL ==
  _SCHEMA_SQL` verbatim. Extends `schema.py`, never replaces `MODEL`/`SETTING` (MEDIUM-2). (§4.1)
- **M4-ADR-4 — body-only per-page fragments + single document wrap at concat for incremental
  output.** New thin public per-page emitters (`render_page_markdown`/`render_page_latex_body`) wrap
  the private `_render_page`; concat applies md's trailing-newline rule / tex's single
  preamble+document wrap, proven byte-identical to the whole-document exporters by a golden test.
  Crash-safe, idempotent, one-writer-safe (HIGH-1). (§7)
- **M4-ADR-8 — lazy `iter_image_pages` for streaming image jobs.** `load_image_pages` is eager and
  stays for the small-image sync routes; the runner streams multi-page TIFFs one frame at a time so
  constant memory holds for images too (MEDIUM-1). (§2.1)
- **M4-ADR-5 — engine WebSocket, Rust→webview Tauri-event bridge (not a direct webview WS).** Keeps
  port+token in Rust (R-SEC-2), reuses the proven `model-progress` pattern, keeps `engineClient` the
  single seam. (§9.3)
- **M4-ADR-6 — 5,000-page proof scaled locally, full count on CI nightly; documented honestly.**
  Never faked; the invariants (flat memory, correct resume) are the real gate. (§12)
- **M4-ADR-7 — `watchdog` for cross-platform watch folder with a settle/debounce wrapper.**
  Permissive, Windows-native events, de-duped. (§8)
- **M4-ADR-9 — PAGE status split: `status` (lease lifecycle) + `rollup_status` (content quality),
  a deliberate refinement of the authoritative ER.** The authoritative `design.md §4` single-column
  `status` (incl. `needs_review`) is split into orthogonal lease-lifecycle and content-quality
  columns; the M5 review surface queries `rollup_status='needs_review'`, and a one-line erratum is
  added to the spec in the same change (MEDIUM-F2). (§4.2)
- **M4-ADR-10 — `Request`-free shared deps provider `pipeline.deps.get_or_build_deps(app_state)`.**
  Both `api/pages._get_deps` (thin wrapper) and the job runner call it; a deps-build failure at job
  start fails the **job** gracefully (never crashes the asyncio task) and emits a terminal WS event
  (MEDIUM-F4). (§2, §11, §15)
- **M4-ADR-11 — Export is a `StreamingResponse` over the committed page set; non-`done` pages emit
  honest in-order placeholders.** Mid-job export is a partial document (byte-identical to the
  whole-document exporter over the committed set); a `failed`/`pending` page is a visible
  placeholder, never a silent gap, honoring the no-fabrication / no-silent-loss steering
  (MEDIUM-F3). (§7.3)
- **M4-ADR-12 — PDF resume uses the indexed `render_pdf_page`, not the sequential `iter_pdf_pages`;
  image resume decodes-and-skips sequential frames.** A resumed PDF job renders only owned indices
  (no re-render of the `done` prefix); image frames before the resume point are cheaply skipped —
  constant memory holds for both (MEDIUM-F1). (§2, §3.1, §6.2)
```

---

## 18. Responses to the design review

### 18.1 Third round (v3 → v4) — the current revision

Review: `m4-design-review.md`, verdict **CHANGES_REQUESTED** (HIGH=0, MEDIUM=3, NIT=3). The reviewer
re-verified the v3 source-level claims against the real M2/M3 code and found them true (indexed
`render_pdf_page` skip seam, eager `load_image_pages`, whole-document-only exporters, shared-model
serialization, settings validator cleanliness, WS auth scheme, startup wiring, migration
idempotency, ER rollup split, path validator, new-dep LICENSES obligations). The architecture is
SOUND; this round is a single convergence pass applying the three MEDIUMs + three NITs and
**re-opening no settled decision**. None backlogged, none ignored.

| Finding | Severity | Resolution | Where |
|---|---|---|---|
| 1. Golden-equivalence breaks when a committed page renders ZERO blocks | MEDIUM | **Addressed.** The per-page concat now filters empty fragments exactly as `document_to_markdown` filters empty blocks over its flat list: md `"\n\n".join(f for f in fragments if f != "")` + the same `if body else "\n"` trailing rule; tex body `"\n\n".join(f for f in fragments if f != "")` (the same blank-line block separator `document_to_latex` uses — joining fragments with a single `"\n"` would diverge by one byte per page boundary). The streaming generator (§7.3c) applies the identical filter and joiner (empty *committed* fragment skipped; non-committed placeholders are non-empty and kept). The golden fixture now MUST include a committed page that renders an empty body, so the test fails if a stray `"\n\n"`/blank body line diverges from the whole-document exporter. | §7.1 (md/tex concat + item 4), §7.3(c), §13 |
| 2. Unconditional boot-revert has no DAO method (only TTL-expiry revert defined) | MEDIUM | **Addressed.** Added `pages_dao.revert_all_leased_for_active_jobs()` — a boot-only method that reverts **all** `leased` rows of non-terminal jobs **unconditionally** (regardless of `lease_expires_at`), distinct from the TTL-gated `revert_expired_leases(now)` the periodic sweeper uses. `recover_on_boot` calls the new method; the single-process precondition is documented; §6.2 step 1 and §6.1 updated to name it. This makes the immediate-resume test deterministic (not TTL-delayed). Added unit + integration tests in §13. | §4.3, §6.1, §6.2, §13 |
| 3. JSON export unanchored; `result_json` fidelity ambiguous | MEDIUM | **Addressed.** Pinned `page.result_json` = the page's **full** `PageResult.model_dump_json()` (lossless, dropped the misleading "compact summary … not full bitmaps" wording). Added a reference exporter `export/json_export.py::document_to_json(doc)` serializing the complete `DocumentResult`/`PageResult`, with a documented fidelity contract and both shapes (committed-only golden anchor + mid-job placeholder array). Added a json golden case asserting byte-identity to `document_to_json` and a `DocumentResult` round-trip, mirroring md/tex. | §4.2, §7.1 (json rule + item 4), §2 (new module), §13 |
| 4. `get_or_build_deps(app_state)` must tolerate a missing/None `pipeline_deps` attribute | NIT | **Addressed.** §11 sketch now reads via `getattr(app_state, "pipeline_deps", None)` and caches via `setattr`, with a note that the §13 unit test must seed `settings`/`model_store` on the stub `app_state`. | §11, §13 |
| 5. `FtsHit` fields + rowid↔`region.id` search mapping underspecified | NIT | **Addressed.** §4.3 now pins `FtsHit` = `{region_id: str, job_id: str, snippet: str, score: float}` and states `search` reads the UNINDEXED `region_id`/`job_id` columns (+ `snippet()`/`bm25()`) directly from `region_fts`, never exposing or joining on the implicit FTS rowid. | §4.3 |
| 6. `anyio` characterized as needing no LICENSES row — confirm it is actually declared | NIT | **Addressed.** Removed the `anyio.to_thread` citation entirely; the CPU-bound offload uses the stdlib `concurrent.futures.ThreadPoolExecutor` + `loop.run_in_executor` path the §3.1 loop already shows, so the runner imports no `anyio` directly and `anyio` stays a pure transitive Starlette dependency — no first-party import, no LICENSES-row question. §1 table row + footnote updated. | §1 |

No findings are deferred. All resolutions stay within the original M4 requirements and the
strictly-sequential one-writer constraint, add no new runtime (shipped) dependency beyond the
already-pinned set, and preserve every v3 decision (asyncio runner + bounded thread pool + global
semaphore; `job_page_workers=1` default; per-page lease state machine with TTL + token-guarded
transitions; additive v1→v2 migration; idempotent temp+`os.replace` fragment export + on-demand
manifest concat; indexed `render_pdf_page` resume primitive; lazy `iter_image_pages`; engine WS →
Rust `tungstenite` bridge → `engine://job-progress`; CI-scaled 5,000-page proof; watch-folder
settle/debounce; PAGE `status`/`rollup_status` split with M5 directed to `rollup_status`).

### 18.2 Second round (v2 → v3) — prior revision, retained for history

Review: `m4-design-review.json` / `m4-design-review.md`, verdict **CHANGES_REQUESTED**
(HIGH=0, MEDIUM=4, NIT=2). The review re-verified every v2 source-level claim against the real
M2/M3 code and found them all true (export whole-document-only, shared-model serialization,
timeout<TTL, eager images, migration idempotency, single-loop SQLite, WS accept/close); the
remaining issues are buildability/contract specifics, all **addressed** below (none backlogged,
none ignored). Each fix was re-verified against the source named in the finding
(`ingest/pdf.py`, `api/pages._get_deps`, the authoritative `design.md §4` ER).

| Finding | Severity | Resolution | Where |
|---|---|---|---|
| M4-F1 Resume render primitive contradicts "skip-before-render"; not pinned to a concrete API | MEDIUM | **Addressed.** Pinned the render seam: PDFs open once via `open_pdf` and call the public indexed `render_pdf_page(pdf, index, cfg)` for **only owned (`pending`) indices** — never the sequential `iter_pdf_pages` — so a resumed job never re-renders the `done` prefix. Images use the sequential `iter_image_pages`; pre-resume frames are decoded-and-skipped (one in-flight frame, constant memory holds). Named `render_pdf_page` in §3.1 and §6.2. | §2, §2.1, §3.1, §6.1, §6.2, ADR-12 |
| M4-F2 PAGE status model diverges from the authoritative ER (`design.md §4`) | MEDIUM | **Addressed.** Kept the two-column split (lease lifecycle vs content quality) and documented it as a **deliberate refinement**: added an ADR line, pinned that the M5 review surface queries `rollup_status='needs_review'` (never `status`), and specified a one-line erratum added to `design.md §4` + `tasks.md` in the same change. | §3.2, §4.2, ADR-9 |
| M4-F3 Mid-job / failed-page export contract + response type unspecified | MEDIUM | **Addressed.** Added §7.3: mid-job export returns the committed-fragment subset and the golden-equivalence invariant is stated as byte-identical to the whole-document exporter over **the committed page set**; non-`done` pages emit honest in-order placeholders (md comment / tex comment / json `{index,status,error}`), never a silent gap; response is a `StreamingResponse` fed by a generator reading one fragment at a time (constant memory). | §7.1, §7.3, §9.1, ADR-11, §13 |
| M4-F4 Shared `PipelineDeps` provider signature + job-start failure mapping undefined | MEDIUM | **Addressed.** Defined `pipeline.deps.get_or_build_deps(app_state) -> PipelineDeps` (takes `app.state`, not `Request`; caches on `app.state.pipeline_deps`; raises the same typed `ModelNotReady`/misconfig errors); `api/pages._get_deps` becomes a thin wrapper. Added a §15 row: deps build at job start fails → job `failed` with `error="models not ready: …"`, WS terminal failure, logged ERROR, never crashes the task. | §2, §11, §15, ADR-10 |
| M4-F5 "Reuses the exact proven model-progress mechanism" overstates a new Rust WS transport | NIT | **Addressed.** Reworded §9.3/ADR-5 and §1's row: reuses the **Rust→webview Tauri-event re-emit pattern**, with a **new** `tungstenite` sync WebSocket read loop replacing the `ureq` HTTP poller; made the new blocking read thread's lifecycle (spawn on `job_subscribe`, stop on terminal state/socket close) explicit. | §1, §9.3, ADR-5 |
| M4-F6 `bulk_insert_pending` enrollment-once vs re-enrollment not stated | NIT | **Addressed.** Stated enrollment runs **exactly once** at job create and `recover_on_boot`/retry-failed **never re-enroll** (only revert leases / flip existing rows); kept the collision→500 as an invariant-violation backstop logged ERROR with the colliding `(job_id, page_index)`. | §6.1, §15 |

No findings are deferred. All resolutions stay within the original M4 requirements (R-JOB-1..7,
R-UI-1/6, R-SEC-2/3, DoD-1/2) and the strictly-sequential one-writer constraint; none change the
milestone scope. The only scope note is the M4-F2 erratum (a doc edit reconciling the authoritative
ER with the intentional two-column refinement), which is honest and within the single-worktree
one-writer rule.

### 18.3 First round (v1 → v2) — prior revision, retained for history

Review: prior `m4-design-review.json`, verdict **CHANGES_REQUESTED** (HIGH=3, MEDIUM=4, NIT=4). All
**addressed** in v2; the second-round review above re-verified each as fixed.

| Finding | Severity | Resolution | Where |
|---|---|---|---|
| HIGH-1 Export reuse not buildable; `.tex` concat won't compile | HIGH | **Addressed.** Added public body-only per-page emitters `render_page_markdown` / `render_page_latex_body` (thin wrappers over private `_render_page`); fragments store body only; concat applies md's trailing-newline rule once and wraps tex body once with `preamble_for()` + `\begin{document}…\end{document}`; added a byte-identical golden-equivalence test. | §2, §7.1, §13 |
| HIGH-2 `page_workers=2` breaks shared-model serialization | HIGH | **Addressed.** Defaulted `job_page_workers=1`; scoped cross-page model parallelism out of M4 (M7 seam gated on a per-model inference lock); corrected the false claim that `region_concurrency` serializes across pages. | §1, §3.1, §3.4 |
| HIGH-3 Lease renewal unspecified / racy with sweeper | HIGH | **Addressed.** Removed renewal; enforce `job_page_timeout_s < job_lease_ttl_s` via a Pydantic `@model_validator`, so a live page is force-failed before its lease could expire and the sweeper only reclaims crashed leases; added a test. | §3.4, §6.2, §13 |
| MEDIUM-1 Image intake not streaming (multi-page TIFF) | MEDIUM | **Addressed.** Added lazy `iter_image_pages`; the runner consumes it for images; `load_image_pages` stays for small-image sync routes. | §2, §2.1, §13 |
| MEDIUM-2 Fresh-DB migration invariant underspecified | MEDIUM | **Addressed.** Stated `_MIGRATIONS` completeness + gap-assert + no-op-at-current; `_V1_SQL == _SCHEMA_SQL` verbatim; added fresh-DB + v1-seeded tests. | §4.1, §4.4, §13 |
| MEDIUM-3 Multi-writer SQLite rule not stated | MEDIUM | **Addressed.** Pinned: all SQLite on the event loop, worker threads never touch `conn`, watchdog only `call_soon_threadsafe`, sweeper is an asyncio task. | §1 (ADR-1), §3.1, §6.2 |
| MEDIUM-4 WS first-message token accept/close ordering | MEDIUM | **Addressed.** Specified header path (validate pre-`accept()`) vs fallback path (`accept()`, one frame under `ws_token_timeout_s`); `4401` as the app close code. | §9.2, §3.4, §10, §13 |
| NIT-1..4 | NIT | **Addressed.** Reordered-steps build-green note; single-process boot-revert precondition; two-opens note; test-only extras + LICENSES done-check. | §14, §6.2, §6.1, §1/§12 |

