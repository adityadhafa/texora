"""Typed data-access helpers for the ``job`` table (design §4.3).

Callers use these helpers rather than embedding SQL; the DAO returns typed :class:`JobRow`
dataclasses so no untyped dict crosses a module boundary. All SQLite access runs on the engine's
single asyncio loop (design §1 M4-ADR-1).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Non-terminal job lifecycle states (re-enqueued on boot, mutable by control actions).
ACTIVE_JOB_STATUSES = ("queued", "running", "paused")
TERMINAL_JOB_STATUSES = ("done", "failed", "canceled")


@dataclass(frozen=True)
class JobRow:
    """A persisted row of the ``job`` table."""

    id: str
    source_path: str
    source_name: str
    status: str
    options_json: str
    total_pages: int
    priority: int
    created_at: str
    updated_at: str
    error: str | None = None


def _row_to_job(row: sqlite3.Row) -> JobRow:
    return JobRow(
        id=row["id"],
        source_path=row["source_path"],
        source_name=row["source_name"],
        status=row["status"],
        options_json=row["options_json"],
        total_pages=row["total_pages"],
        priority=row["priority"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error=row["error"],
    )


def create_job(conn: sqlite3.Connection, job: JobRow) -> None:
    """Insert a new job row."""

    with conn:
        conn.execute(
            """
            INSERT INTO job (
                id, source_path, source_name, status, options_json,
                total_pages, priority, error, created_at, updated_at
            ) VALUES (
                :id, :source_path, :source_name, :status, :options_json,
                :total_pages, :priority, :error, :created_at, :updated_at
            )
            """,
            {
                "id": job.id,
                "source_path": job.source_path,
                "source_name": job.source_name,
                "status": job.status,
                "options_json": job.options_json,
                "total_pages": job.total_pages,
                "priority": job.priority,
                "error": job.error,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            },
        )


def get_job(conn: sqlite3.Connection, job_id: str) -> JobRow | None:
    """Return the job row for ``job_id`` or ``None`` when absent."""

    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row is not None else None


def list_jobs(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[JobRow]:
    """Return jobs ordered by the queue index (status, priority desc, created_at)."""

    if status is not None:
        rows = conn.execute(
            """
            SELECT * FROM job WHERE status = ?
            ORDER BY priority DESC, created_at
            LIMIT ? OFFSET ?
            """,
            (status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM job
            ORDER BY priority DESC, created_at
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def set_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    updated_at: str,
    error: str | None = None,
) -> None:
    """Update a job's lifecycle ``status`` (+ optional ``error``) and ``updated_at``."""

    with conn:
        conn.execute(
            "UPDATE job SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, updated_at, job_id),
        )


def set_priority(conn: sqlite3.Connection, job_id: str, priority: int, *, updated_at: str) -> None:
    """Update a job's scheduling ``priority`` and ``updated_at``."""

    with conn:
        conn.execute(
            "UPDATE job SET priority = ?, updated_at = ? WHERE id = ?",
            (priority, updated_at, job_id),
        )


def update_timestamps(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    updated_at: str,
    total_pages: int | None = None,
) -> None:
    """Refresh ``updated_at`` (and optionally ``total_pages`` once enrollment counts pages)."""

    with conn:
        if total_pages is not None:
            conn.execute(
                "UPDATE job SET updated_at = ?, total_pages = ? WHERE id = ?",
                (updated_at, total_pages, job_id),
            )
        else:
            conn.execute(
                "UPDATE job SET updated_at = ? WHERE id = ?",
                (updated_at, job_id),
            )


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    """Delete a job and (via ``ON DELETE CASCADE``) its pages/regions."""

    with conn:
        conn.execute("DELETE FROM job WHERE id = ?", (job_id,))
