"""SQLite schema + connection management for the Texora engine.

All SQLite access in the engine goes through the ``db/`` package — route handlers and
business logic never run raw SQL (see ``.kiro/steering/structure.md``). M2 needs a minimal
subset of the full M4 schema: the ``MODEL`` registry table and a generic ``SETTING``
key/value table. The database is opened in WAL mode with a tiny ``user_version`` migration
guard so later milestones can evolve the schema additively.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from texora_engine.logging_config import get_logger

logger = get_logger("db")

# Bump when the schema changes; `migrate` applies additive steps up to this version.
SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model (
    id          TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    status      TEXT NOT NULL,
    license     TEXT NOT NULL,
    target_dir  TEXT NOT NULL,
    sha256      TEXT,
    size        INTEGER,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode connection to ``db_path``, creating parent dirs as needed.

    Rows are returned as :class:`sqlite3.Row` for name-based access. Foreign keys are
    enabled for forward-compatibility with the richer M4 schema.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI runs sync routes in a threadpool, so the shared
    # connection is accessed from worker threads. Access is serialized at the app level
    # (single-user loopback engine); WAL + the default per-connection lock keep writes safe.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version;").fetchone()
    return int(row[0]) if row is not None else 0


def migrate(conn: sqlite3.Connection) -> None:
    """Create tables and advance ``user_version`` to :data:`SCHEMA_VERSION`.

    Idempotent: running against an up-to-date database is a no-op.
    """

    current = _user_version(conn)
    if current >= SCHEMA_VERSION:
        return
    logger.info("migrating db schema from v%d to v%d", current, SCHEMA_VERSION)
    with conn:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION};")


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open the database and ensure the schema is present/migrated."""

    conn = connect(db_path)
    migrate(conn)
    return conn
