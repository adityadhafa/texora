"""SQLite db-layer tests: WAL mode, MODEL upsert/read, SETTING upsert/read."""

from __future__ import annotations

from pathlib import Path

from texora_engine.db import (
    ModelRow,
    get_model,
    get_setting,
    init_db,
    set_setting,
    set_status,
    upsert_model,
)


def test_init_db_enables_wal(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "texora.db")
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_model_upsert_and_read(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "texora.db")
    try:
        row = ModelRow(
            id="pix2tex",
            version="v0.0.1",
            status="ready",
            license="MIT",
            target_dir=str(tmp_path / "models" / "pix2tex"),
            sha256="abc",
            size=123,
        )
        upsert_model(conn, row)
        read = get_model(conn, "pix2tex")
        assert read is not None
        assert read.status == "ready"
        assert read.size == 123

        set_status(conn, "pix2tex", "corrupt", detail="hash mismatch")
        read2 = get_model(conn, "pix2tex")
        assert read2 is not None
        assert read2.status == "corrupt"
        assert read2.detail == "hash mismatch"

        assert get_model(conn, "absent") is None
    finally:
        conn.close()


def test_setting_upsert_and_read(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "texora.db")
    try:
        assert get_setting(conn, "device") is None
        set_setting(conn, "device", "cpu")
        assert get_setting(conn, "device") == "cpu"
        set_setting(conn, "device", "cuda")
        assert get_setting(conn, "device") == "cuda"
    finally:
        conn.close()
