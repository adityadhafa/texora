"""Typed data-access helpers for the ``model`` table.

Callers use these helpers rather than embedding SQL; the DAO returns typed
:class:`ModelRow` dataclasses so no untyped dict crosses a module boundary.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRow:
    """A persisted row of the ``model`` registry table."""

    id: str
    version: str
    status: str
    license: str
    target_dir: str
    sha256: str | None = None
    size: int | None = None
    detail: str | None = None


def _row_to_model(row: sqlite3.Row) -> ModelRow:
    return ModelRow(
        id=row["id"],
        version=row["version"],
        status=row["status"],
        license=row["license"],
        target_dir=row["target_dir"],
        sha256=row["sha256"],
        size=row["size"],
        detail=row["detail"],
    )


def get_model(conn: sqlite3.Connection, model_id: str) -> ModelRow | None:
    """Return the model row for ``model_id`` or ``None`` when absent."""

    row = conn.execute("SELECT * FROM model WHERE id = ?", (model_id,)).fetchone()
    return _row_to_model(row) if row is not None else None


def upsert_model(conn: sqlite3.Connection, model: ModelRow) -> None:
    """Insert or replace the row for ``model.id``."""

    with conn:
        conn.execute(
            """
            INSERT INTO model (id, version, status, license, target_dir, sha256, size, detail)
            VALUES (:id, :version, :status, :license, :target_dir, :sha256, :size, :detail)
            ON CONFLICT(id) DO UPDATE SET
                version=excluded.version,
                status=excluded.status,
                license=excluded.license,
                target_dir=excluded.target_dir,
                sha256=excluded.sha256,
                size=excluded.size,
                detail=excluded.detail
            """,
            {
                "id": model.id,
                "version": model.version,
                "status": model.status,
                "license": model.license,
                "target_dir": model.target_dir,
                "sha256": model.sha256,
                "size": model.size,
                "detail": model.detail,
            },
        )


def set_status(
    conn: sqlite3.Connection, model_id: str, status: str, detail: str | None = None
) -> None:
    """Update just the ``status`` (and optional ``detail``) of an existing row."""

    with conn:
        conn.execute(
            "UPDATE model SET status = ?, detail = ? WHERE id = ?",
            (status, detail, model_id),
        )
