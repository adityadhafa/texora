"""Tests for the ``job`` DAO (create/get/list/status/priority/timestamps/delete)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from texora_engine.db import init_db, jobs_dao
from texora_engine.db.jobs_dao import JobRow


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "texora.db")
    yield c
    c.close()


def _job(job_id: str, *, status: str = "queued", priority: int = 0) -> JobRow:
    return JobRow(
        id=job_id,
        source_path=f"/docs/{job_id}.pdf",
        source_name=f"{job_id}.pdf",
        status=status,
        options_json="{}",
        total_pages=0,
        priority=priority,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )


def test_create_and_get(conn: sqlite3.Connection) -> None:
    jobs_dao.create_job(conn, _job("j1"))
    got = jobs_dao.get_job(conn, "j1")
    assert got is not None
    assert got.source_name == "j1.pdf"
    assert got.status == "queued"
    assert jobs_dao.get_job(conn, "absent") is None


def test_list_orders_by_priority_desc(conn: sqlite3.Connection) -> None:
    jobs_dao.create_job(conn, _job("low", priority=-5))
    jobs_dao.create_job(conn, _job("high", priority=10))
    jobs_dao.create_job(conn, _job("mid", priority=0))
    ids = [j.id for j in jobs_dao.list_jobs(conn)]
    assert ids == ["high", "mid", "low"]


def test_list_filters_by_status(conn: sqlite3.Connection) -> None:
    jobs_dao.create_job(conn, _job("a", status="done"))
    jobs_dao.create_job(conn, _job("b", status="running"))
    done = [j.id for j in jobs_dao.list_jobs(conn, status="done")]
    assert done == ["a"]


def test_set_status_and_priority_and_timestamps(conn: sqlite3.Connection) -> None:
    jobs_dao.create_job(conn, _job("j"))
    jobs_dao.set_status(conn, "j", "failed", updated_at="2025-01-02T00:00:00Z", error="boom")
    jobs_dao.set_priority(conn, "j", 7, updated_at="2025-01-03T00:00:00Z")
    jobs_dao.update_timestamps(conn, "j", updated_at="2025-01-04T00:00:00Z", total_pages=12)
    got = jobs_dao.get_job(conn, "j")
    assert got is not None
    assert got.status == "failed"
    assert got.error == "boom"
    assert got.priority == 7
    assert got.total_pages == 12
    assert got.updated_at == "2025-01-04T00:00:00Z"


def test_delete_cascades_pages(conn: sqlite3.Connection) -> None:
    from texora_engine.db import pages_dao

    jobs_dao.create_job(conn, _job("j"))
    pages_dao.bulk_insert_pending(conn, "j", [("p0", 0), ("p1", 1)])
    assert pages_dao.counts(conn, "j").total == 2
    jobs_dao.delete_job(conn, "j")
    assert jobs_dao.get_job(conn, "j") is None
    assert pages_dao.counts(conn, "j").total == 0
