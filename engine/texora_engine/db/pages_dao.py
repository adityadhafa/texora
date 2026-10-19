"""Typed data-access helpers for the ``page`` lease state machine (design §3.2, §4.3).

The per-page lease lifecycle (``pending → leased → done|failed``) is enforced entirely in SQL:
``lease_next`` is a single atomic ``UPDATE ... RETURNING`` so two workers can never lease the same
page; ``mark_done``/``mark_failed`` carry a ``WHERE lease_token`` guard so a stale owner can never
double-commit. Two distinct revert methods exist and must not be conflated (design §4.3):

* :func:`revert_expired_leases` — the TTL-gated sweeper / crash-recovery method (only expired
  leases).
* :func:`revert_all_leased_for_active_jobs` — the boot-only method reverting **all** leased rows of
  non-terminal jobs **unconditionally** (single-process precondition; makes resume immediate).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from texora_engine.db.jobs_dao import ACTIVE_JOB_STATUSES


@dataclass(frozen=True)
class PageRow:
    """A persisted row of the ``page`` table."""

    id: str
    job_id: str
    page_index: int
    status: str
    attempts: int
    lease_token: str | None = None
    lease_expires_at: str | None = None
    rollup_status: str | None = None
    result_json: str | None = None
    avg_confidence: float | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class PageCounts:
    """Aggregate lease-lifecycle counts for a job (the progress source of truth)."""

    pending: int
    leased: int
    done: int
    failed: int
    needs_review: int  # rollup_status='needs_review' among done pages
    total: int


@dataclass(frozen=True)
class LeasedPage:
    """The ``(id, page_index)`` pair returned by an atomic :func:`lease_next`."""

    id: str
    page_index: int


def _row_to_page(row: sqlite3.Row) -> PageRow:
    return PageRow(
        id=row["id"],
        job_id=row["job_id"],
        page_index=row["page_index"],
        status=row["status"],
        attempts=row["attempts"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
        rollup_status=row["rollup_status"],
        result_json=row["result_json"],
        avg_confidence=row["avg_confidence"],
        error=row["error"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def bulk_insert_pending(
    conn: sqlite3.Connection,
    job_id: str,
    page_ids_indices: list[tuple[str, int]],
) -> None:
    """Enroll a job's owned page indices as ``pending`` rows in ONE transaction.

    ``page_ids_indices`` is a list of ``(page_id, page_index)`` pairs (the caller allocates the
    uuid4 page ids). Runs exactly once at job create; ``recover_on_boot``/retry never re-enroll
    (design §6.1), so a ``UNIQUE(job_id, page_index)`` collision is an invariant-violation bug.
    """

    with conn:
        conn.executemany(
            """
            INSERT INTO page (id, job_id, page_index, status, attempts)
            VALUES (?, ?, ?, 'pending', 0)
            """,
            [(pid, job_id, idx) for pid, idx in page_ids_indices],
        )


def lease_next(
    conn: sqlite3.Connection,
    job_id: str,
    lease_token: str,
    lease_expires_at: str,
) -> LeasedPage | None:
    """Atomically lease the next ``pending`` page (lowest ``page_index``) or return ``None``.

    The ``UPDATE ... WHERE id = (SELECT ... LIMIT 1) RETURNING`` is a single atomic statement, so
    two concurrent attempts can never lease the same row (design §3.2).
    """

    with conn:
        row = conn.execute(
            """
            UPDATE page
               SET status='leased', lease_token=:tok,
                   lease_expires_at=:exp, attempts=attempts+1
             WHERE id = (
                 SELECT id FROM page
                  WHERE job_id=:job AND status='pending'
                  ORDER BY page_index
                  LIMIT 1
             )
            RETURNING id, page_index
            """,
            {"tok": lease_token, "exp": lease_expires_at, "job": job_id},
        ).fetchone()
    if row is None:
        return None
    return LeasedPage(id=row["id"], page_index=row["page_index"])


def mark_done(
    conn: sqlite3.Connection,
    page_id: str,
    lease_token: str,
    *,
    rollup_status: str,
    result_json: str,
    avg_confidence: float | None,
    finished_at: str,
) -> bool:
    """Mark a leased page ``done`` (token-guarded). Returns ``True`` if the row was updated."""

    with conn:
        cur = conn.execute(
            """
            UPDATE page
               SET status='done', rollup_status=:rollup, result_json=:result,
                   avg_confidence=:conf, error=NULL, finished_at=:finished
             WHERE id=:id AND lease_token=:tok
            """,
            {
                "rollup": rollup_status,
                "result": result_json,
                "conf": avg_confidence,
                "finished": finished_at,
                "id": page_id,
                "tok": lease_token,
            },
        )
    return cur.rowcount > 0


def mark_failed(
    conn: sqlite3.Connection,
    page_id: str,
    lease_token: str,
    *,
    error: str,
    finished_at: str,
) -> bool:
    """Mark a leased page ``failed`` (token-guarded). Returns ``True`` if the row was updated."""

    with conn:
        cur = conn.execute(
            """
            UPDATE page
               SET status='failed', rollup_status='failed', error=:error, finished_at=:finished
             WHERE id=:id AND lease_token=:tok
            """,
            {"error": error, "finished": finished_at, "id": page_id, "tok": lease_token},
        )
    return cur.rowcount > 0


def revert_expired_leases(conn: sqlite3.Connection, now: str) -> int:
    """TTL-gated sweeper: revert only ``leased`` rows whose lease expired before ``now``.

    Called by the periodic sweeper (design §6.2). Returns the number of rows reverted. Because
    ``job_page_timeout_s < job_lease_ttl_s`` is enforced at config load, a live in-flight page is
    force-failed before its lease could expire, so this only ever reclaims a crashed lease.
    """

    with conn:
        cur = conn.execute(
            """
            UPDATE page
               SET status='pending', lease_token=NULL, lease_expires_at=NULL
             WHERE status='leased' AND lease_expires_at < :now
            """,
            {"now": now},
        )
    return cur.rowcount


def revert_all_leased_for_active_jobs(conn: sqlite3.Connection) -> int:
    """Boot-only: revert ALL ``leased`` rows of non-terminal jobs, regardless of TTL.

    Distinct from :func:`revert_expired_leases` (design §4.3, MEDIUM-2). Called exactly once by
    ``recover_on_boot`` so a page left ``leased`` by a killed process is reclaimable immediately,
    not after its TTL elapses. Correct only because exactly one engine process exists (single-user
    loopback model): a freshly booted process owns no outstanding leases, so reverting every leased
    row cannot steal a lease from a concurrent worker. Returns the number of rows reverted.
    """

    placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
    with conn:
        cur = conn.execute(
            f"""
            UPDATE page
               SET status='pending', lease_token=NULL, lease_expires_at=NULL
             WHERE status='leased'
               AND job_id IN (SELECT id FROM job WHERE status IN ({placeholders}))
            """,
            ACTIVE_JOB_STATUSES,
        )
    return cur.rowcount


def reset_failed_to_pending(conn: sqlite3.Connection, job_id: str) -> int:
    """Flip a job's ``failed`` pages back to ``pending`` (clears ``error``, keeps ``attempts``).

    ``done`` rows are untouched, so no completed page is re-run (design §5 retry-failed-only).
    Returns the number of rows reset.
    """

    with conn:
        cur = conn.execute(
            """
            UPDATE page
               SET status='pending', error=NULL, lease_token=NULL,
                   lease_expires_at=NULL, rollup_status=NULL, finished_at=NULL
             WHERE job_id=:job AND status='failed'
            """,
            {"job": job_id},
        )
    return cur.rowcount


def counts(conn: sqlite3.Connection, job_id: str) -> PageCounts:
    """Return the aggregate lease-lifecycle counts for a job (progress source of truth)."""

    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(status='pending'), 0) AS pending,
            COALESCE(SUM(status='leased'), 0) AS leased,
            COALESCE(SUM(status='done'), 0) AS done,
            COALESCE(SUM(status='failed'), 0) AS failed,
            COALESCE(SUM(status='done' AND rollup_status='needs_review'), 0) AS needs_review
        FROM page WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    return PageCounts(
        pending=int(row["pending"]),
        leased=int(row["leased"]),
        done=int(row["done"]),
        failed=int(row["failed"]),
        needs_review=int(row["needs_review"]),
        total=int(row["total"]),
    )


def get_page(conn: sqlite3.Connection, page_id: str) -> PageRow | None:
    """Return the page row for ``page_id`` or ``None`` when absent."""

    row = conn.execute("SELECT * FROM page WHERE id = ?", (page_id,)).fetchone()
    return _row_to_page(row) if row is not None else None


def list_pages(conn: sqlite3.Connection, job_id: str) -> list[PageRow]:
    """Return all page rows of a job in ``page_index`` order."""

    rows = conn.execute(
        "SELECT * FROM page WHERE job_id = ? ORDER BY page_index",
        (job_id,),
    ).fetchall()
    return [_row_to_page(r) for r in rows]
