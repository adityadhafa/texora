"""Migration v1→v2 tests (design §4.4, MEDIUM-2): fresh DB + v1-seeded preservation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from texora_engine.db import SCHEMA_VERSION, init_db
from texora_engine.db.schema import _V1_SQL, connect, migrate

_V1_TABLES = {"model", "setting"}
_V2_TABLES = {"job", "page", "region", "formula_candidate", "correction", "region_fts"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table')").fetchall()
    return {r[0] for r in rows}


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version;").fetchone()[0])


def test_fresh_db_migrates_to_v2_with_all_tables(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "texora.db")
    try:
        assert _user_version(conn) == SCHEMA_VERSION == 2
        tables = _table_names(conn)
        assert _V1_TABLES <= tables
        assert _V2_TABLES <= tables
    finally:
        conn.close()


def test_v1_seeded_db_preserves_data_and_gains_v2_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "texora.db"
    # Seed a DB at user_version=1 with the v1 schema + a MODEL row, exactly like an M2/M3 user.
    conn = connect(db_path)
    try:
        with conn:
            conn.executescript(_V1_SQL)
            conn.execute("PRAGMA user_version=1;")
            conn.execute(
                """
                INSERT INTO model (id, version, status, license, target_dir, sha256, size, detail)
                VALUES ('pix2tex', 'v1', 'ready', 'MIT', '/m/pix2tex', 'deadbeef', 42, 'ok')
                """
            )
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        assert _user_version(conn) == 1
        migrate(conn)
        assert _user_version(conn) == 2
        # The pre-existing MODEL row survives verbatim.
        row = conn.execute("SELECT * FROM model WHERE id='pix2tex'").fetchone()
        assert row is not None
        assert row["status"] == "ready"
        assert row["sha256"] == "deadbeef"
        assert row["size"] == 42
        # The v2 tables now exist.
        assert _V2_TABLES <= _table_names(conn)
    finally:
        conn.close()


def test_migrate_is_noop_at_current_version(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "texora.db")
    try:
        before = _user_version(conn)
        migrate(conn)  # no-op: range(3, 3) is empty
        assert _user_version(conn) == before == 2
    finally:
        conn.close()
