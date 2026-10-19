"""SQLite schema + connection management for the Texora engine.

All SQLite access in the engine goes through the ``db/`` package — route handlers and
business logic never run raw SQL (see ``.kiro/steering/structure.md``). M2 shipped the
``MODEL`` registry + a generic ``SETTING`` key/value table (schema v1). M4 adds the job
queue tables (``JOB``/``PAGE``/``REGION``/``FORMULA_CANDIDATE``/``CORRECTION``) + an FTS5
full-text index over recognized region content, as an **additive v1→v2 migration** (design
§4.1, M4-ADR-3).

The migration mechanism is an ordered ``_MIGRATIONS`` map keyed by target version. ``_V1_SQL``
is the original v1 schema verbatim (``CREATE TABLE IF NOT EXISTS`` makes re-running it on a
fresh DB harmless), so a fresh DB runs step 1 then step 2, a v1 DB runs only step 2, and a v2
DB is a no-op. The database is opened in WAL mode.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from texora_engine.logging_config import get_logger

logger = get_logger("db")

# Bump when the schema changes; `migrate` applies additive steps up to this version.
SCHEMA_VERSION = 2

# --- v1 (M2): MODEL registry + generic SETTING key/value. Preserved VERBATIM. ---
_V1_SQL = """
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

# --- v2 (M4): job queue + per-page lease state machine + FTS5 over region content. ---
# PAGE carries two ORTHOGONAL status columns (design §4.2, M4-ADR-9):
#   * ``status``        — the LEASE LIFECYCLE: pending|leased|done|failed (drives the state
#                         machine / resume / retry).
#   * ``rollup_status`` — the CONTENT QUALITY rolled up from the PageResult: ok|needs_review|
#                         failed. A page can be status='done' AND rollup_status='needs_review'.
# The review surface (M5) queries ``rollup_status``, never ``status``.
_V2_SQL = """
CREATE TABLE job (
    id            TEXT PRIMARY KEY,
    source_path   TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    status        TEXT NOT NULL,              -- queued|running|paused|done|failed|canceled
    options_json  TEXT NOT NULL,
    total_pages   INTEGER NOT NULL DEFAULT 0,
    priority      INTEGER NOT NULL DEFAULT 0, -- higher = sooner
    error         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_job_status_priority ON job(status, priority DESC, created_at);

CREATE TABLE page (
    id               TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    page_index       INTEGER NOT NULL,        -- 0-based source index
    status           TEXT NOT NULL,           -- LEASE LIFECYCLE: pending|leased|done|failed
    lease_token      TEXT,
    lease_expires_at TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    rollup_status    TEXT,                     -- CONTENT QUALITY: ok|needs_review|failed
    result_json      TEXT,                     -- full PageResult.model_dump_json() (lossless)
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
    content        TEXT,                       -- text or latex (fed to FTS via triggers)
    rec_confidence REAL,
    validation     TEXT                        -- ok|needs_review|failed
);
CREATE INDEX idx_region_page ON region(page_id, reading_order);

CREATE TABLE formula_candidate (
    id          TEXT PRIMARY KEY,
    region_id   TEXT NOT NULL REFERENCES region(id) ON DELETE CASCADE,
    engine_id   TEXT NOT NULL,
    latex       TEXT NOT NULL,
    confidence  REAL,
    latex_valid INTEGER NOT NULL DEFAULT 0     -- M5 ensemble fills this; table exists now
);

CREATE TABLE correction (
    id          TEXT PRIMARY KEY,
    region_id   TEXT REFERENCES region(id) ON DELETE SET NULL,
    original    TEXT NOT NULL,
    corrected   TEXT NOT NULL,
    created_at  TEXT NOT NULL                  -- M5 review UI fills this; table exists now
);

-- FTS5 full-text index over recognized content for the Library search (R-UI-1).
CREATE VIRTUAL TABLE region_fts USING fts5(
    content,
    region_id UNINDEXED,
    job_id    UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Keep the FTS index in lock-step with ``region`` so routes/runner never touch FTS directly.
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
"""

# Ordered migration steps keyed by TARGET version. ``_MIGRATIONS`` must contain every key in
# the inclusive range ``2..SCHEMA_VERSION`` (the gap-guard assert in ``migrate`` enforces this).
_MIGRATIONS: dict[int, str] = {
    1: _V1_SQL,
    2: _V2_SQL,
}


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode connection to ``db_path``, creating parent dirs as needed.

    Rows are returned as :class:`sqlite3.Row` for name-based access. Foreign keys are
    enabled for the richer M4 schema (``ON DELETE CASCADE`` on job delete).
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI runs sync routes in a threadpool, so the shared
    # connection is accessed from worker threads. Access is serialized at the app level
    # (single-user loopback engine; all M4 SQLite runs on the one asyncio loop — design
    # §1 M4-ADR-1); WAL + the default per-connection lock keep writes safe.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version;").fetchone()
    return int(row[0]) if row is not None else 0


def migrate(conn: sqlite3.Connection) -> None:
    """Apply ordered additive migration steps up to :data:`SCHEMA_VERSION`.

    Each step runs in its own transaction and bumps ``PRAGMA user_version``. The loop is a
    no-op when the DB is already current (``range(SCHEMA_VERSION + 1, SCHEMA_VERSION + 1)`` is
    empty), so no fast-path early return is needed. The ``assert`` guards against a future gap
    in :data:`_MIGRATIONS` (fail loudly rather than silently skip a step).
    """

    current = _user_version(conn)
    for version in range(current + 1, SCHEMA_VERSION + 1):
        assert version in _MIGRATIONS, f"missing migration step v{version}"  # gap guard
        logger.info("applying migration -> v%d", version)
        with conn:
            conn.executescript(_MIGRATIONS[version])
            conn.execute(f"PRAGMA user_version={version};")


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open the database and ensure the schema is present/migrated."""

    conn = connect(db_path)
    migrate(conn)
    return conn
