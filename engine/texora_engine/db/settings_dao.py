"""Typed data-access helpers for the ``setting`` key/value table.

Used by the hardware route to persist the selected execution device. Callers never run
raw SQL directly.
"""

from __future__ import annotations

import sqlite3


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the stored value for ``key`` or ``None`` when unset."""

    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row is not None else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or replace the value for ``key``."""

    with conn:
        conn.execute(
            """
            INSERT INTO setting (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
